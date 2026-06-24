"""参数映射测试：${param} 占位符替换 + 全局映射表。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.preprocessor import preprocess, replace_params
from app.services.lineage_extractor import extract_lineages
from app.models.statement import Statement, StatementType


# ============ replace_params 单元测试 ============

class TestReplaceParams:
    """${param} 占位符替换"""

    def test_schema_param_no_mapping(self):
        """无映射时，${icl_schema} 保留参数名当标识符"""
        out = replace_params("SELECT * FROM ${icl_schema}.orders")
        assert out == "SELECT * FROM icl_schema.orders"

    def test_schema_param_with_mapping(self):
        """有映射时，替换成实际值"""
        out = replace_params(
            "SELECT * FROM ${icl_schema}.orders",
            mapping={"icl_schema": "ods"},
        )
        assert out == "SELECT * FROM ods.orders"

    def test_param_in_table_name_concat(self):
        """${schema}_${env}.report 拼接成单标识符"""
        out = replace_params(
            "INSERT INTO ${schema}_${env}.report SELECT 1",
            mapping={"schema": "dw", "env": "prod"},
        )
        assert "dw_prod.report" in out

    def test_time_param_becomes_identifier(self):
        """${batch_date} 在 WHERE 被替换成 batch_date（当列名，对血缘无害）"""
        out = replace_params("WHERE dt = ${batch_date}")
        assert out == "WHERE dt = batch_date"

    def test_multiple_distinct_params(self):
        """多个不同参数各自替换"""
        out = replace_params(
            "INSERT INTO ${dst}.r SELECT * FROM ${src}.a JOIN ${src}.b ON 1=1",
            mapping={"dst": "dwh", "src": "ods"},
        )
        assert "dwh.r" in out
        assert "ods.a" in out
        assert "ods.b" in out

    def test_no_params_passthrough(self):
        """无 ${} 的 SQL 原样返回"""
        out = replace_params("SELECT * FROM public.orders")
        assert out == "SELECT * FROM public.orders"

    def test_empty_mapping_keeps_param_name(self):
        """空映射表 → 保留参数名"""
        out = replace_params("${x}.t", mapping={})
        assert out == "x.t"

    def test_param_only_in_mapping_partially(self):
        """部分参数有映射，部分没有"""
        out = replace_params(
            "${a}.t1 JOIN ${b}.t2",
            mapping={"a": "schema_a"},  # b 没映射
        )
        assert "schema_a.t1" in out
        assert "b.t2" in out  # b 保留原名


# ============ preprocess 集成测试 ============

class TestPreprocessWithParams:
    """preprocess 集成参数替换 + 去注释"""

    def test_params_replaced_before_parse(self):
        """参数替换在去注释之前生效"""
        sql = "-- 注释\nINSERT INTO ${icl_schema}.t SELECT * FROM ${icl_schema}.s"
        out = preprocess(sql, param_mapping={"icl_schema": "ods"})
        assert "ods.t" in out
        assert "ods.s" in out
        assert "${" not in out
        assert "--" not in out  # 注释也去了

    def test_preprocess_no_mapping_still_works(self):
        """无映射时 preprocess 仍能工作（保留参数名）"""
        sql = "INSERT INTO ${x}.t SELECT * FROM ${x}.s"
        out = preprocess(sql)
        assert "x.t" in out
        assert "${" not in out


# ============ 端到端：含参数的 SQL 能提取血缘 ============

class TestEndToEndParamLineage:
    """含 ${param} 的 SQL 经过替换后能正确提取表级血缘"""

    def test_schema_param_lineage(self):
        """${icl_schema} 替换后血缘正确（默认保留参数名）"""
        # 模拟 analyzer 的流程：preprocess（无映射）→ 直接 extract
        sql = "INSERT INTO ${icl_schema}.report SELECT * FROM ${icl_schema}.orders"
        cleaned = preprocess(sql)  # 无映射，${icl_schema} → icl_schema
        stmt = Statement(seq=1, type=StatementType.INSERT, text=cleaned)
        lineages, _ = extract_lineages([stmt])
        assert len(lineages) == 1
        assert lineages[0].source_table == "icl_schema.orders"
        assert lineages[0].target_table == "icl_schema.report"

    def test_schema_param_lineage_with_mapping(self):
        """${icl_schema}=ods 映射后血缘用实际 schema"""
        sql = "INSERT INTO ${icl_schema}.report SELECT * FROM ${icl_schema}.orders"
        cleaned = preprocess(sql, param_mapping={"icl_schema": "ods"})
        stmt = Statement(seq=1, type=StatementType.INSERT, text=cleaned)
        lineages, _ = extract_lineages([stmt])
        assert len(lineages) == 1
        assert lineages[0].source_table == "ods.orders"
        assert lineages[0].target_table == "ods.report"

    def test_cross_schema_param_lineage(self):
        """跨 schema 参数 ${dst}/${src} 区分"""
        sql = ("INSERT INTO ${dst}.report "
               "SELECT * FROM ${src}.orders o JOIN ${src}.customers c ON o.cid=c.id")
        cleaned = preprocess(sql, param_mapping={"dst": "dwh", "src": "ods"})
        stmt = Statement(seq=1, type=StatementType.INSERT, text=cleaned)
        lineages, _ = extract_lineages([stmt])
        # 两条边：ods.orders→dwh.report, ods.customers→dwh.report
        assert len(lineages) == 2
        sources = {l.source_table for l in lineages}
        assert "ods.orders" in sources
        assert "ods.customers" in sources
        assert all(l.target_table == "dwh.report" for l in lineages)

    def test_time_param_does_not_break_lineage(self):
        """${batch_date} 在 WHERE 不影响血缘提取"""
        sql = "INSERT INTO report SELECT * FROM orders WHERE dt = ${batch_date}"
        cleaned = preprocess(sql)
        stmt = Statement(seq=1, type=StatementType.INSERT, text=cleaned)
        lineages, _ = extract_lineages([stmt])
        assert len(lineages) == 1
        assert lineages[0].source_table == "public.orders"
        assert lineages[0].target_table == "public.report"

    def test_param_concat_in_table_name(self):
        """${schema}_${env}.report 拼接成单标识符"""
        sql = "INSERT INTO ${schema}_${env}.report SELECT * FROM src"
        cleaned = preprocess(sql, param_mapping={"schema": "dw", "env": "prod"})
        stmt = Statement(seq=1, type=StatementType.INSERT, text=cleaned)
        lineages, _ = extract_lineages([stmt])
        assert len(lineages) == 1
        assert lineages[0].target_table == "dw_prod.report"


# ============ store 参数映射读写测试 ============

class TestStoreParamMapping:
    """store 层参数映射持久化"""

    def test_get_empty_when_no_file(self):
        from app.services import store
        # 清空
        if store.PARAM_MAPPING_FILE.exists():
            store.PARAM_MAPPING_FILE.unlink()
        assert store.get_param_mapping() == {}

    def test_set_and_get(self):
        from app.services import store
        result = store.set_param_mapping({"icl_schema": "ods", "env": "prod"})
        assert result == {"icl_schema": "ods", "env": "prod"}
        assert store.get_param_mapping() == {"icl_schema": "ods", "env": "prod"}

    def test_set_filters_invalid_keys(self):
        """非法 key（非标识符）被过滤"""
        from app.services import store
        result = store.set_param_mapping({
            "valid_name": "ok",
            "invalid-name": "bad",  # 含连字符
            "": "empty",            # 空 key
            "also valid": "bad",    # 含空格
        })
        assert "valid_name" in result
        assert "invalid-name" not in result
        assert "" not in result
        assert "also valid" not in result

    def test_set_full_replace(self):
        """PUT 是全量替换，不是合并"""
        from app.services import store
        store.set_param_mapping({"a": "1", "b": "2"})
        store.set_param_mapping({"c": "3"})  # 全量替换，a/b 没了
        result = store.get_param_mapping()
        assert result == {"c": "3"}
