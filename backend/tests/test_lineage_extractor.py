"""血缘提取模块测试

新语义：所有表名规范化为 `schema.table` 全限定名，裸表名补 public。
跨 schema 同名表（public.orders vs reporting.orders）视为不同节点。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.lineage_extractor import extract_lineages, _extract_tables_via_ast
from app.models.lineage import ExtractionMethod, OperationType, TableType
from app.models.statement import Statement, StatementType


def _make_stmt(seq: int, stype: StatementType, text: str) -> Statement:
    """测试辅助：快速创建 Statement 对象"""
    return Statement(seq=seq, type=stype, text=text)


class TestExtractTablesViaAst:
    """AST 静态解析提取表名测试"""

    def test_simple_insert_select(self):
        ref, created, modified = _extract_tables_via_ast(
            "INSERT INTO target_table SELECT * FROM source_table;"
        )
        assert "public.source_table" in ref
        assert "public.target_table" in modified

    def test_insert_with_join(self):
        ref, created, modified = _extract_tables_via_ast(
            "INSERT INTO summary (id, name, total) SELECT u.id, u.name, SUM(o.amount) FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.id, u.name;"
        )
        assert "public.users" in ref
        assert "public.orders" in ref
        assert "public.summary" in modified

    def test_update_with_subquery(self):
        ref, created, modified = _extract_tables_via_ast(
            "UPDATE table_c SET col1 = (SELECT col1 FROM table_d);"
        )
        assert "public.table_d" in ref
        assert "public.table_c" in modified

    def test_create_table_as_select(self):
        ref, created, modified = _extract_tables_via_ast(
            "CREATE TABLE tmp_orders AS SELECT order_id, amount FROM orders;"
        )
        assert "public.orders" in ref
        assert "public.tmp_orders" in created

    def test_create_temp_table_as_select(self):
        ref, created, modified = _extract_tables_via_ast(
            "CREATE TEMP TABLE tmp AS SELECT * FROM src;"
        )
        assert "public.src" in ref
        assert "public.tmp" in created

    def test_delete(self):
        ref, created, modified = _extract_tables_via_ast(
            "DELETE FROM target_table WHERE id IN (SELECT id FROM source_table);"
        )
        assert "public.source_table" in ref
        assert "public.target_table" in modified


class TestExtractLineagesStatic:
    """静态解析血缘提取测试（不使用执行计划）"""

    def test_simple_insert_select(self):
        stmts = [_make_stmt(1, StatementType.INSERT, "INSERT INTO target SELECT * FROM source;")]
        lineages, type_map = extract_lineages(stmts)

        assert len(lineages) == 1
        assert lineages[0].source_table == "public.source"
        assert lineages[0].target_table == "public.target"
        assert lineages[0].operation_type == OperationType.INSERT
        assert lineages[0].extraction_method == ExtractionMethod.STATIC_ANALYSIS
        assert lineages[0].statement_seq == 1

    def test_multi_source_join(self):
        stmts = [
            _make_stmt(
                1,
                StatementType.INSERT,
                "INSERT INTO summary (id, name, total) SELECT u.id, u.name, SUM(o.amount) FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.id, u.name;",
            )
        ]
        lineages, type_map = extract_lineages(stmts)

        assert len(lineages) == 2
        sources = {l.source_table for l in lineages}
        assert "public.users" in sources
        assert "public.orders" in sources
        assert all(l.target_table == "public.summary" for l in lineages)

    def test_temp_table_flow(self):
        """测试用例4: 包含临时表的完整血缘链路"""
        stmts = [
            _make_stmt(
                1,
                StatementType.CREATE,
                "CREATE TEMP TABLE tmp_order_detail AS SELECT o.order_id, o.amount, c.name FROM orders o JOIN customers c ON o.customer_id = c.id;",
            ),
            _make_stmt(
                2,
                StatementType.INSERT,
                "INSERT INTO order_report (order_id, amount, customer_name) SELECT order_id, amount, name FROM tmp_order_detail;",
            ),
        ]
        lineages, type_map = extract_lineages(stmts)

        # 第一条语句：orders → tmp_order_detail, customers → tmp_order_detail
        seq1_lineages = [l for l in lineages if l.statement_seq == 1]
        seq1_sources = {l.source_table for l in seq1_lineages}
        seq1_targets = {l.target_table for l in seq1_lineages}
        assert "public.orders" in seq1_sources
        assert "public.customers" in seq1_sources
        assert "public.tmp_order_detail" in seq1_targets

        # 第二条语句：tmp_order_detail → order_report
        seq2_lineages = [l for l in lineages if l.statement_seq == 2]
        assert len(seq2_lineages) == 1
        assert seq2_lineages[0].source_table == "public.tmp_order_detail"
        assert seq2_lineages[0].target_table == "public.order_report"

    def test_multi_statement_script(self):
        """测试用例2: 多语句脚本"""
        stmts = [
            _make_stmt(1, StatementType.INSERT, "INSERT INTO table_a SELECT * FROM table_b;"),
            _make_stmt(2, StatementType.UPDATE, "UPDATE table_c SET col1 = (SELECT col1 FROM table_d);"),
        ]
        lineages, type_map = extract_lineages(stmts)

        assert len(lineages) == 2

        lin1 = [l for l in lineages if l.statement_seq == 1][0]
        assert lin1.source_table == "public.table_b"
        assert lin1.target_table == "public.table_a"
        assert lin1.operation_type == OperationType.INSERT

        lin2 = [l for l in lineages if l.statement_seq == 2][0]
        assert lin2.source_table == "public.table_d"
        assert lin2.target_table == "public.table_c"
        assert lin2.operation_type == OperationType.UPDATE

    def test_table_type_classification(self):
        """表类型分类测试"""
        stmts = [
            _make_stmt(1, StatementType.CREATE, "CREATE TEMP TABLE tmp AS SELECT * FROM src;"),
            _make_stmt(2, StatementType.INSERT, "INSERT INTO tgt SELECT * FROM tmp;"),
        ]
        _, type_map = extract_lineages(stmts)

        assert type_map["public.src"] == TableType.SOURCE
        assert type_map["public.tmp"] == TableType.INTERMEDIATE
        assert type_map["public.tgt"] == TableType.TARGET

    def test_statement_tables_populated(self):
        """验证语句的表引用信息被正确填充"""
        stmts = [_make_stmt(1, StatementType.INSERT, "INSERT INTO target SELECT * FROM source;")]
        extract_lineages(stmts)

        assert "public.source" in stmts[0].tables_referenced
        assert "public.target" in stmts[0].tables_modified


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_statements(self):
        lineages, type_map = extract_lineages([])
        assert lineages == []
        assert type_map == {}

    def test_invalid_sql_graceful(self):
        """无效 SQL 不应抛出异常"""
        stmts = [_make_stmt(1, StatementType.INSERT, "THIS IS NOT SQL;")]
        # 不应抛异常，只是提取不到表信息
        lineages, _ = extract_lineages(stmts)
        # 无目标表则无血缘
        assert len(lineages) == 0

    def test_update_no_source(self):
        """UPDATE 无子查询（无源表）"""
        stmts = [_make_stmt(1, StatementType.UPDATE, "UPDATE target SET col = 'constant';")]
        lineages, _ = extract_lineages(stmts)
        # 应记录目标表，source 为空
        assert len(lineages) == 1
        assert lineages[0].target_table == "public.target"
        assert lineages[0].source_table == ""


class TestSchemaPrefixedTables:
    """带 schema 前缀的表名处理测试（全限定名语义）"""

    def test_insert_with_schema_prefix(self):
        """INSERT 中源表带 schema 前缀 → 保留为 public.source_table"""
        ref, created, modified = _extract_tables_via_ast(
            "INSERT INTO target_table SELECT * FROM public.source_table;"
        )
        assert "public.source_table" in ref
        assert "public.target_table" in modified

    def test_insert_both_with_schema(self):
        """INSERT 源表和目标表都带 schema 前缀"""
        ref, created, modified = _extract_tables_via_ast(
            "INSERT INTO public.target_table SELECT * FROM public.source_table;"
        )
        assert "public.source_table" in ref
        assert "public.target_table" in modified

    def test_join_with_schema_prefix(self):
        """JOIN 中不同 schema 的表必须保留为独立节点（跨 schema 区分）"""
        ref, _, _ = _extract_tables_via_ast(
            "INSERT INTO report SELECT * FROM public.orders o JOIN analytics.customers c ON o.cid = c.id;"
        )
        assert "public.orders" in ref
        assert "analytics.customers" in ref

    def test_create_with_schema_prefix(self):
        """CREATE TABLE 带 schema 前缀"""
        ref, created, modified = _extract_tables_via_ast(
            "CREATE TABLE public.tmp_orders AS SELECT * FROM source;"
        )
        assert "public.source" in ref
        assert "public.tmp_orders" in created

    def test_schema_prefix_distinct_from_plain(self):
        """裸表名 src 与 public.src 应归一化为同一全限定名 public.src（不产生重复）"""
        ref, _, _ = _extract_tables_via_ast(
            "INSERT INTO t SELECT a.x FROM public.src a JOIN src b ON a.id = b.id;"
        )
        # 裸表名 src 补 public 后与 public.src 相同 → 去重后只剩一个
        assert ref.count("public.src") == 1

    def test_schema_lineage_qualified(self):
        """血缘关系中的表名应为全限定名"""
        stmts = [
            _make_stmt(1, StatementType.INSERT,
                       "INSERT INTO public.report SELECT * FROM public.orders;")
        ]
        lineages, type_map = extract_lineages(stmts)
        assert len(lineages) == 1
        assert lineages[0].source_table == "public.orders"
        assert lineages[0].target_table == "public.report"

    def test_cross_schema_lineage(self):
        """跨 schema 的血缘链路：不同 schema 的表保留各自 schema"""
        stmts = [
            _make_stmt(1, StatementType.CREATE,
                       "CREATE TEMP TABLE tmp AS SELECT * FROM staging.raw_data;"),
            _make_stmt(2, StatementType.INSERT,
                       "INSERT INTO public.report SELECT * FROM tmp;"),
        ]
        lineages, type_map = extract_lineages(stmts)
        assert len(lineages) == 2
        # staging.raw_data → public.tmp → public.report
        src_lin = [l for l in lineages if l.source_table == "staging.raw_data"][0]
        assert src_lin.target_table == "public.tmp"

    def test_cross_schema_same_name_distinct(self):
        """跨 schema 同名表必须区分（新设计核心价值）"""
        ref, _, _ = _extract_tables_via_ast(
            "INSERT INTO target SELECT * FROM public.orders o JOIN reporting.orders r ON o.id = r.id;"
        )
        # public.orders 与 reporting.orders 是两个独立节点
        assert "public.orders" in ref
        assert "reporting.orders" in ref
        assert ref.count("public.orders") == 1
        assert ref.count("reporting.orders") == 1
