"""语句拆分器测试"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.splitter import split_statements, _detect_type, _should_keep
from app.models.statement import StatementType


class TestDetectType:
    """语句类型检测测试"""

    def test_insert(self):
        assert _detect_type("INSERT INTO t VALUES (1)") == StatementType.INSERT

    def test_insert_select(self):
        assert _detect_type("INSERT INTO t SELECT * FROM s") == StatementType.INSERT

    def test_update(self):
        assert _detect_type("UPDATE t SET col = 1") == StatementType.UPDATE

    def test_delete(self):
        assert _detect_type("DELETE FROM t WHERE id = 1") == StatementType.DELETE

    def test_merge(self):
        assert _detect_type("MERGE INTO t USING s ON t.id = s.id") == StatementType.MERGE

    def test_create_table(self):
        assert _detect_type("CREATE TABLE t AS SELECT * FROM s") == StatementType.CREATE

    def test_create_temp_table(self):
        assert _detect_type("CREATE TEMP TABLE t AS SELECT * FROM s") == StatementType.CREATE

    def test_create_temporary_table(self):
        assert _detect_type("CREATE TEMPORARY TABLE t AS SELECT * FROM s") == StatementType.CREATE

    def test_unknown(self):
        assert _detect_type("ALTER TABLE t ADD COLUMN c INT") == StatementType.UNKNOWN

    def test_cte_insert(self):
        """WITH ... AS ... INSERT 应识别为 INSERT"""
        sql = "WITH cte AS (SELECT * FROM s) INSERT INTO t SELECT * FROM cte"
        assert _detect_type(sql) == StatementType.INSERT


class TestShouldKeep:
    """语句过滤测试"""

    def test_keep_insert(self):
        assert _should_keep("INSERT INTO t VALUES (1)") is True

    def test_keep_update(self):
        assert _should_keep("UPDATE t SET col = 1") is True

    def test_keep_delete(self):
        assert _should_keep("DELETE FROM t") is True

    def test_keep_create_table(self):
        assert _should_keep("CREATE TABLE t AS SELECT * FROM s") is True

    def test_keep_create_temp(self):
        assert _should_keep("CREATE TEMP TABLE t (id INT)") is True

    def test_drop_alter(self):
        assert _should_keep("DROP TABLE t") is False

    def test_alter(self):
        assert _should_keep("ALTER TABLE t ADD COLUMN c INT") is False

    def test_empty(self):
        assert _should_keep("") is False

    def test_grant(self):
        assert _should_keep("GRANT SELECT ON t TO user") is False


class TestSplitStatements:
    """完整拆分测试"""

    def test_single_statement(self):
        script = "INSERT INTO t VALUES (1);"
        group = split_statements(script)
        assert len(group.statements) == 1
        assert group.statements[0].seq == 1
        assert group.statements[0].type == StatementType.INSERT

    def test_multiple_statements(self):
        script = "INSERT INTO t VALUES (1); UPDATE t SET col = 2; DELETE FROM t WHERE id = 3;"
        group = split_statements(script)
        assert len(group.statements) == 3
        assert group.statements[0].type == StatementType.INSERT
        assert group.statements[1].type == StatementType.UPDATE
        assert group.statements[2].type == StatementType.DELETE

    def test_sequential_numbering(self):
        script = "INSERT INTO a VALUES (1); INSERT INTO b VALUES (2); INSERT INTO c VALUES (3);"
        group = split_statements(script)
        seqs = [s.seq for s in group.statements]
        assert seqs == [1, 2, 3]

    def test_filter_ddl(self):
        """DDL 语句（ALTER、DROP）应被过滤"""
        script = "ALTER TABLE t ADD COLUMN c INT; INSERT INTO t VALUES (1); DROP TABLE t;"
        group = split_statements(script)
        assert len(group.statements) == 1
        assert group.statements[0].type == StatementType.INSERT

    def test_preserve_create_table(self):
        """CREATE TABLE 应被保留"""
        script = "CREATE TEMP TABLE tmp AS SELECT * FROM src; INSERT INTO tgt SELECT * FROM tmp;"
        group = split_statements(script)
        assert len(group.statements) == 2
        assert group.statements[0].type == StatementType.CREATE
        assert group.statements[1].type == StatementType.INSERT

    def test_empty_script(self):
        group = split_statements("")
        assert len(group.statements) == 0

    def test_original_script_preserved(self):
        original = "CREATE TABLE tmp AS SELECT 1;"
        group = split_statements("CREATE TABLE tmp AS SELECT 1;", original_script=original)
        assert group.original_script == original
        assert group.preprocessed_script == "CREATE TABLE tmp AS SELECT 1;"

    def test_statement_text_ends_with_semicolon(self):
        script = "INSERT INTO t VALUES (1)"
        group = split_statements(script)
        assert group.statements[0].text.endswith(";")

    def test_complex_temp_table_flow(self):
        """设计文档测试用例4: 包含临时表的完整流程"""
        script = """
        CREATE TEMP TABLE tmp_order_detail AS
        SELECT o.order_id, o.amount, c.name
        FROM orders o JOIN customers c ON o.customer_id = c.id;

        INSERT INTO order_report (order_id, amount, customer_name)
        SELECT order_id, amount, name FROM tmp_order_detail;
        """
        group = split_statements(script)
        assert len(group.statements) == 2
        assert group.statements[0].type == StatementType.CREATE
        assert group.statements[1].type == StatementType.INSERT
        assert "tmp_order_detail" in group.statements[0].text
