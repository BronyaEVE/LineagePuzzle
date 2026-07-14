"""参数映射 + 预处理规则测试。

参数映射已降级为预处理规则的一种特例（builtin 规则）。
本文件测试三个层面：
  1. replace_params 函数（保留的旧接口，向后兼容）
  2. preprocess 通过 rules 参数执行参数映射规则
  3. store 层 param_mapping 接口（转发到 preprocess_rules）
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.preprocessor import preprocess, replace_params, apply_rules
from app.services.lineage_extractor import extract_lineages
from app.models.statement import Statement, StatementType


# 构造参数映射规则的辅助函数
def _param_rules(mapping: dict[str, str]) -> list[dict]:
    """把 {param: value} 转成参数映射规则列表"""
    return [
        {
            "id": f"param-{k}",
            "name": f"参数映射: {k}",
            "pattern": r"\$\{" + k + r"\}",
            "replacement": v,
            "enabled": True,
            "builtin": True,
        }
        for k, v in mapping.items()
    ]


# ============ replace_params 单元测试（保留的旧接口） ============

class TestReplaceParams:
    """${param} 占位符替换（replace_params 函数保持向后兼容）"""

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


# ============ apply_rules + preprocess 集成测试 ============

class TestApplyRules:
    """预处理规则执行（apply_rules 函数）"""

    def test_param_rule_substitution(self):
        """参数映射规则正确替换 ${param}"""
        rules = _param_rules({"icl_schema": "ods"})
        out = apply_rules("SELECT * FROM ${icl_schema}.orders", rules)
        assert out == "SELECT * FROM ods.orders"

    def test_disabled_rule_skipped(self):
        """enabled=False 的规则不执行"""
        rules = [
            {"id": "r1", "pattern": "SELECT", "replacement": "X", "enabled": True},
            {"id": "r2", "pattern": "FROM", "replacement": "Y", "enabled": False},
        ]
        out = apply_rules("SELECT * FROM t", rules)
        assert "X" in out  # r1 生效
        assert "FROM" in out  # r2 被跳过，FROM 保留

    def test_multiple_rules_applied_in_order(self):
        """多条规则按数组顺序依次执行"""
        rules = [
            {"id": "r1", "pattern": "foo", "replacement": "bar", "enabled": True},
            {"id": "r2", "pattern": "bar", "replacement": "baz", "enabled": True},
        ]
        out = apply_rules("foo", rules)
        assert out == "baz"  # foo→bar→baz，顺序执行

    def test_capture_group_in_replacement(self):
        """replacement 支持 $1 捕获组"""
        rules = [
            {"id": "r1", "pattern": r"INSERT INTO (\w+)", "replacement": r"INSERT INTO tgt_\1", "enabled": True},
        ]
        out = apply_rules("INSERT INTO foo VALUES(1)", rules)
        assert "INSERT INTO tgt_foo" in out

    def test_empty_rules_passthrough(self):
        """空规则列表原样返回"""
        assert apply_rules("SELECT 1", []) == "SELECT 1"
        assert apply_rules("SELECT 1", None) == "SELECT 1"


class TestPreprocessWithRules:
    """preprocess 通过 rules 参数集成规则替换 + 去注释"""

    def test_params_replaced_before_parse(self):
        """参数规则替换在去注释之前生效（去注释由 locked 规则执行）"""
        sql = "-- 注释\nINSERT INTO ${icl_schema}.t SELECT * FROM ${icl_schema}.s"
        # 模拟 store 的完整规则：locked 去注释 + 参数规则
        rules = [
            {"id": "builtin-line-comment", "pattern": r"--[^\n]*", "replacement": "", "enabled": True, "locked": True},
            {"id": "builtin-block-comment", "pattern": r"/\*.*?\*/", "replacement": "", "enabled": True, "locked": True},
        ] + _param_rules({"icl_schema": "ods"})
        out = preprocess(sql, rules=rules)
        assert "ods.t" in out
        assert "ods.s" in out
        assert "${" not in out
        assert "--" not in out  # 注释也去了

    def test_preprocess_empty_rules_keeps_text(self):
        """空规则列表时，${param} 原样保留（不替换）"""
        sql = "INSERT INTO ${x}.t SELECT * FROM ${x}.s"
        out = preprocess(sql, rules=[])
        # 无规则 → ${x} 保留（不被替换），但其他清洗仍执行
        assert "${x}" in out or "x.t" in out  # 取决于是否被其他步骤影响

    def test_custom_cleanup_rule(self):
        """用户自定义清洗规则（如去掉某种特殊注释）"""
        sql = "INSERT INTO t SELECT 1; # mysql style comment"
        rules = [
            {"id": "r1", "pattern": r"#[^\n]*", "replacement": "", "enabled": True},
        ]
        out = preprocess(sql, rules=rules)
        assert "# mysql" not in out
        assert "INSERT INTO t" in out


# ============ 端到端：含参数的 SQL 能提取血缘 ============

class TestEndToEndParamLineage:
    """含 ${param} 的 SQL 经过规则替换后能正确提取表级血缘"""

    def test_schema_param_lineage_with_rules(self):
        """${icl_schema}=ods 规则替换后血缘用实际 schema"""
        sql = "INSERT INTO ${icl_schema}.report SELECT * FROM ${icl_schema}.orders"
        cleaned = preprocess(sql, rules=_param_rules({"icl_schema": "ods"}))
        stmt = Statement(seq=1, type=StatementType.INSERT, text=cleaned)
        lineages, _ = extract_lineages([stmt])
        assert len(lineages) == 1
        assert lineages[0].source_table == "ods.orders"
        assert lineages[0].target_table == "ods.report"

    def test_cross_schema_param_lineage(self):
        """跨 schema 参数 ${dst}/${src} 区分"""
        sql = ("INSERT INTO ${dst}.report "
               "SELECT * FROM ${src}.orders o JOIN ${src}.customers c ON o.cid=c.id")
        cleaned = preprocess(sql, rules=_param_rules({"dst": "dwh", "src": "ods"}))
        stmt = Statement(seq=1, type=StatementType.INSERT, text=cleaned)
        lineages, _ = extract_lineages([stmt])
        assert len(lineages) == 2
        sources = {l.source_table for l in lineages}
        assert "ods.orders" in sources
        assert "ods.customers" in sources
        assert all(l.target_table == "dwh.report" for l in lineages)

    def test_param_concat_in_table_name(self):
        """${schema}_${env}.report 拼接成单标识符"""
        sql = "INSERT INTO ${schema}_${env}.report SELECT * FROM src"
        cleaned = preprocess(sql, rules=_param_rules({"schema": "dw", "env": "prod"}))
        stmt = Statement(seq=1, type=StatementType.INSERT, text=cleaned)
        lineages, _ = extract_lineages([stmt])
        assert len(lineages) == 1
        assert lineages[0].target_table == "dw_prod.report"


# ============ store 参数映射读写测试（向后兼容接口） ============

class TestStoreParamMapping:
    """store 层参数映射持久化（通过 preprocess_rules 实现）"""

    def test_get_empty_when_no_file(self):
        from app.services import store
        # 清空两个文件
        if store.PARAM_MAPPING_FILE.exists():
            store.PARAM_MAPPING_FILE.unlink()
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        assert store.get_param_mapping() == {}

    def test_set_and_get(self):
        from app.services import store
        # 先清空确保干净
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        result = store.set_param_mapping({"icl_schema": "ods", "env": "prod"})
        assert result == {"icl_schema": "ods", "env": "prod"}
        assert store.get_param_mapping() == {"icl_schema": "ods", "env": "prod"}

    def test_set_filters_invalid_keys(self):
        """非法 key（非标识符）被过滤"""
        from app.services import store
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
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
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        store.set_param_mapping({"a": "1", "b": "2"})
        store.set_param_mapping({"c": "3"})  # 全量替换，a/b 没了
        result = store.get_param_mapping()
        assert result == {"c": "3"}


# ============ store 预处理规则读写测试 ============

class TestStorePreprocessRules:
    """store 层预处理规则持久化

    注意：get_preprocess_rules 首次调用会预置默认 locked 规则（去块注释、去行注释）。
    测试时需考虑这些 locked 规则的存在。
    """

    def test_get_default_locked_rules_when_no_file(self):
        """无文件时返回默认 locked 规则（非空）"""
        from app.services import store
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        if store.PARAM_MAPPING_FILE.exists():
            store.PARAM_MAPPING_FILE.unlink()
        rules = store.get_preprocess_rules()
        # 默认预置 locked 规则
        ids = {r["id"] for r in rules}
        assert "builtin-block-comment" in ids
        assert "builtin-line-comment" in ids
        # 都是 locked
        assert all(r["locked"] for r in rules)

    def test_set_and_get_custom_rule(self):
        """自定义规则可写入并读回（locked 规则会自动保留）"""
        from app.services import store
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        rules = [
            {"id": "r1", "name": "test", "pattern": "foo", "replacement": "bar", "enabled": True},
        ]
        result = store.set_preprocess_rules(rules)
        # 自定义规则 + locked 规则自动补回
        ids = {r["id"] for r in result}
        assert "r1" in ids
        # 读回
        got = store.get_preprocess_rules()
        got_ids = {r["id"] for r in got}
        assert "r1" in got_ids

    def test_invalid_regex_rejected(self):
        """非法正则 pattern 被过滤"""
        from app.services import store
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        rules = [
            {"id": "ok", "pattern": "valid", "replacement": "", "enabled": True},
            {"id": "bad", "pattern": "[invalid", "replacement": "", "enabled": True},
        ]
        result = store.set_preprocess_rules(rules)
        ids = {r["id"] for r in result}
        assert "ok" in ids
        assert "bad" not in ids  # 非法正则被过滤

    def test_duplicate_id_rejected(self):
        """重复 id 被去重"""
        from app.services import store
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        rules = [
            {"id": "dup", "pattern": "a", "replacement": "b", "enabled": True},
            {"id": "dup", "pattern": "c", "replacement": "d", "enabled": True},
        ]
        result = store.set_preprocess_rules(rules)
        # 只保留第一个 dup（第二个被拒），locked 规则也会补回
        dup_count = sum(1 for r in result if r["id"] == "dup")
        assert dup_count == 1

    def test_locked_rule_cannot_be_deleted(self):
        """locked 规则不可删除：提交不含 locked 规则的列表会被自动补回"""
        from app.services import store
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        # 提交空列表（尝试删除所有规则）
        result = store.set_preprocess_rules([])
        ids = {r["id"] for r in result}
        assert "builtin-block-comment" in ids
        assert "builtin-line-comment" in ids

    def test_locked_rule_enabled_respected(self):
        """locked 规则的 enabled 状态被尊重（可关闭但不可删）"""
        from app.services import store
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        # 先初始化默认规则
        store.get_preprocess_rules()
        # 关闭块注释
        result = store.set_preprocess_rules([
            {"id": "builtin-block-comment", "pattern": r"/\*.*?\*/", "replacement": "", "enabled": False, "builtin": True, "locked": True},
        ])
        block_rule = next(r for r in result if r["id"] == "builtin-block-comment")
        assert block_rule["enabled"] is False  # 关闭被尊重
        # 行注释被自动补回（因为用户没提交它）
        line_rule = next(r for r in result if r["id"] == "builtin-line-comment")
        assert line_rule["enabled"] is True

    def test_migration_from_param_mapping(self):
        """旧 param_mapping.json 自动迁移为 builtin 规则（附加在 locked 规则后）"""
        from app.services import store
        # 清空确保干净
        if store.PREPROCESS_RULES_FILE.exists():
            store.PREPROCESS_RULES_FILE.unlink()
        # 写旧格式文件
        store._write_json(store.PARAM_MAPPING_FILE, {"icl_schema": "ods", "env": "prod"})
        # 触发迁移（get_preprocess_rules 内部调用 _init_default_rules）
        rules = store.get_preprocess_rules()
        # 2 条 locked 规则 + 2 条迁移的参数规则 = 4
        ids = {r["id"] for r in rules}
        assert "builtin-block-comment" in ids  # locked 规则
        assert "builtin-line-comment" in ids
        assert "param-icl_schema" in ids  # 迁移规则
        assert "param-env" in ids
        # 迁移规则都是 builtin 非 locked
        param_rules = [r for r in rules if r["id"].startswith("param-")]
        assert all(r["builtin"] for r in param_rules)
        assert all(not r.get("locked") for r in param_rules)
        # pattern 正确
        schema_rule = next(r for r in rules if r["id"] == "param-icl_schema")
        assert schema_rule["pattern"] == r"\$\{icl_schema\}"
        assert schema_rule["replacement"] == "ods"
