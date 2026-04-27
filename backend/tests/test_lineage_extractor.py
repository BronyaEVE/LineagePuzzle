"""血缘提取模块测试"""
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
        assert "source_table" in ref
        assert "target_table" in modified

    def test_insert_with_join(self):
        ref, created, modified = _extract_tables_via_ast(
            "INSERT INTO summary (id, name, total) SELECT u.id, u.name, SUM(o.amount) FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.id, u.name;"
        )
        assert "users" in ref
        assert "orders" in ref
        assert "summary" in modified

    def test_update_with_subquery(self):
        ref, created, modified = _extract_tables_via_ast(
            "UPDATE table_c SET col1 = (SELECT col1 FROM table_d);"
        )
        assert "table_d" in ref
        assert "table_c" in modified

    def test_create_table_as_select(self):
        ref, created, modified = _extract_tables_via_ast(
            "CREATE TABLE tmp_orders AS SELECT order_id, amount FROM orders;"
        )
        assert "orders" in ref
        assert "tmp_orders" in created

    def test_create_temp_table_as_select(self):
        ref, created, modified = _extract_tables_via_ast(
            "CREATE TEMP TABLE tmp AS SELECT * FROM src;"
        )
        assert "src" in ref
        assert "tmp" in created

    def test_delete(self):
        ref, created, modified = _extract_tables_via_ast(
            "DELETE FROM target_table WHERE id IN (SELECT id FROM source_table);"
        )
        assert "source_table" in ref
        assert "target_table" in modified


class TestExtractLineagesStatic:
    """静态解析血缘提取测试（不使用执行计划）"""

    def test_simple_insert_select(self):
        stmts = [_make_stmt(1, StatementType.INSERT, "INSERT INTO target SELECT * FROM source;")]
        lineages, type_map = extract_lineages(stmts)

        assert len(lineages) == 1
        assert lineages[0].source_table == "source"
        assert lineages[0].target_table == "target"
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
        assert "users" in sources
        assert "orders" in sources
        assert all(l.target_table == "summary" for l in lineages)

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
        assert "orders" in seq1_sources
        assert "customers" in seq1_sources
        assert "tmp_order_detail" in seq1_targets

        # 第二条语句：tmp_order_detail → order_report
        seq2_lineages = [l for l in lineages if l.statement_seq == 2]
        assert len(seq2_lineages) == 1
        assert seq2_lineages[0].source_table == "tmp_order_detail"
        assert seq2_lineages[0].target_table == "order_report"

    def test_multi_statement_script(self):
        """测试用例2: 多语句脚本"""
        stmts = [
            _make_stmt(1, StatementType.INSERT, "INSERT INTO table_a SELECT * FROM table_b;"),
            _make_stmt(2, StatementType.UPDATE, "UPDATE table_c SET col1 = (SELECT col1 FROM table_d);"),
        ]
        lineages, type_map = extract_lineages(stmts)

        assert len(lineages) == 2

        lin1 = [l for l in lineages if l.statement_seq == 1][0]
        assert lin1.source_table == "table_b"
        assert lin1.target_table == "table_a"
        assert lin1.operation_type == OperationType.INSERT

        lin2 = [l for l in lineages if l.statement_seq == 2][0]
        assert lin2.source_table == "table_d"
        assert lin2.target_table == "table_c"
        assert lin2.operation_type == OperationType.UPDATE

    def test_table_type_classification(self):
        """表类型分类测试"""
        stmts = [
            _make_stmt(1, StatementType.CREATE, "CREATE TEMP TABLE tmp AS SELECT * FROM src;"),
            _make_stmt(2, StatementType.INSERT, "INSERT INTO tgt SELECT * FROM tmp;"),
        ]
        _, type_map = extract_lineages(stmts)

        assert type_map["src"] == TableType.SOURCE
        assert type_map["tmp"] == TableType.INTERMEDIATE
        assert type_map["tgt"] == TableType.TARGET

    def test_statement_tables_populated(self):
        """验证语句的表引用信息被正确填充"""
        stmts = [_make_stmt(1, StatementType.INSERT, "INSERT INTO target SELECT * FROM source;")]
        extract_lineages(stmts)

        assert "source" in stmts[0].tables_referenced
        assert "target" in stmts[0].tables_modified


class TestExtractLineagesWithPlan:
    """使用执行计划的血缘提取测试"""

    def test_execution_plan_takes_priority(self):
        """执行计划优先级高于静态解析"""
        stmts = [_make_stmt(1, StatementType.INSERT, "INSERT INTO target SELECT * FROM source;")]
        # 提供一个空的执行计划（模拟 EXPLAIN 返回）
        plans = {1: {"Plan": {"Node Type": "ModifyTable"}}}
        lineages, _ = extract_lineages(stmts, execution_plans=plans)

        # 有执行计划时使用 execution_plan 方法
        assert len(lineages) == 1
        assert lineages[0].extraction_method == ExtractionMethod.EXECUTION_PLAN

    def test_fallback_to_static_when_no_plan(self):
        """无执行计划时回退到静态解析"""
        stmts = [_make_stmt(1, StatementType.INSERT, "INSERT INTO target SELECT * FROM source;")]
        lineages, _ = extract_lineages(stmts)

        assert len(lineages) == 1
        assert lineages[0].extraction_method == ExtractionMethod.STATIC_ANALYSIS

    def test_mixed_plan_and_static(self):
        """部分语句有执行计划，部分没有"""
        stmts = [
            _make_stmt(1, StatementType.CREATE, "CREATE TEMP TABLE tmp AS SELECT * FROM src;"),
            _make_stmt(2, StatementType.INSERT, "INSERT INTO tgt SELECT * FROM tmp;"),
        ]
        # 只给第二条语句提供执行计划
        plans = {2: {"Plan": {"Node Type": "ModifyTable"}}}
        lineages, _ = extract_lineages(stmts, execution_plans=plans)

        seq1_lin = [l for l in lineages if l.statement_seq == 1]
        seq2_lin = [l for l in lineages if l.statement_seq == 2]
        assert all(l.extraction_method == ExtractionMethod.STATIC_ANALYSIS for l in seq1_lin)
        assert all(l.extraction_method == ExtractionMethod.EXECUTION_PLAN for l in seq2_lin)


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
        assert lineages[0].target_table == "target"
        assert lineages[0].source_table == ""
