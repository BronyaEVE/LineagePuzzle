"""列级血缘提取测试（v2.1）。

覆盖 DESIGN.v2 §6.4 的 8 个场景，验证显式列级血缘解析 + 降级行为。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.column_lineage import extract_column_mappings
from app.services.lineage_extractor import extract_lineages
from app.models.statement import Statement, StatementType


def _stmt(seq, stype, text):
    return Statement(seq=seq, type=stype, text=text)


# ============ 直接测 extract_column_mappings ============

class TestExplicitColumnMapping:
    """显式列级血缘（最理想场景）"""

    def test_simple_insert_select(self):
        """INSERT INTO t(a,b,c) SELECT x,y,z → a←x, b←y, c←z"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO report (a, b, c) SELECT x, y, z FROM src")
        mappings = extract_column_mappings(stmt)

        assert len(mappings) == 3
        # 按目标列名建索引
        by_tgt = {m.target_column: m for m in mappings}
        assert set(by_tgt.keys()) == {"a", "b", "c"}
        assert by_tgt["a"].source_columns == ["x"]
        assert by_tgt["a"].source_table == "public.src"
        assert by_tgt["a"].transformation is None  # 纯列引用
        assert by_tgt["b"].source_columns == ["y"]
        assert by_tgt["c"].source_columns == ["z"]
        assert all(m.target_table == "public.report" for m in mappings)

    def test_join_with_aliases(self):
        """JOIN 多源表带别名 → 正确解析 o.id, c.name 到各自表"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO summary (order_id, total, cust_name) "
                     "SELECT o.id, o.amount, c.name "
                     "FROM orders o JOIN customers c ON o.cid = c.id")
        mappings = extract_column_mappings(stmt)

        assert len(mappings) == 3
        by_tgt = {m.target_column: m for m in mappings}
        assert by_tgt["order_id"].source_table == "public.orders"
        assert by_tgt["order_id"].source_columns == ["id"]
        assert by_tgt["total"].source_table == "public.orders"
        assert by_tgt["total"].source_columns == ["amount"]
        assert by_tgt["cust_name"].source_table == "public.customers"
        assert by_tgt["cust_name"].source_columns == ["name"]

    def test_aggregation_transform(self):
        """聚合 SUM(amount) → 记录 transformation"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO agg (cust_id, total) "
                     "SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id")
        mappings = extract_column_mappings(stmt)

        by_tgt = {m.target_column: m for m in mappings}
        # SUM(amount) 有 transform
        assert by_tgt["total"].transformation is not None
        assert "SUM" in by_tgt["total"].transformation
        assert by_tgt["total"].source_columns == ["amount"]
        # customer_id 纯列，无 transform
        assert by_tgt["cust_id"].transformation is None

    def test_expression_multiple_sources(self):
        """表达式 price*qty → 多源列"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO calc (gross) SELECT price * qty FROM sales")
        mappings = extract_column_mappings(stmt)

        assert len(mappings) == 1
        m = mappings[0]
        assert m.target_column == "gross"
        assert set(m.source_columns) == {"price", "qty"}
        assert m.source_table == "public.sales"
        assert m.transformation is not None  # price * qty


class TestCtasAndSubquery:
    """CTAS 和子查询"""

    def test_ctas(self):
        """CREATE TABLE tmp AS SELECT a, b FROM src → 目标列=projection 列名"""
        stmt = _stmt(1, StatementType.CREATE,
                     "CREATE TABLE tmp AS SELECT a, b FROM src WHERE x > 0")
        mappings = extract_column_mappings(stmt)

        assert len(mappings) == 2
        by_tgt = {m.target_column: m for m in mappings}
        assert set(by_tgt.keys()) == {"a", "b"}
        assert by_tgt["a"].source_columns == ["a"]
        assert by_tgt["a"].source_table == "public.src"
        assert by_tgt["b"].source_table == "public.src"

    def test_subquery(self):
        """子查询 → 列穿透到物理表 [v2.2 穿透]"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO dest (cust_id, cnt) "
                     "SELECT customer_id, cnt FROM ("
                     "  SELECT customer_id, COUNT(*) as cnt FROM orders GROUP BY customer_id"
                     ") sub")
        mappings = extract_column_mappings(stmt)

        by_tgt = {m.target_column: m for m in mappings}
        # customer_id 穿透派生表到物理表 orders
        assert by_tgt["cust_id"].source_table == "public.orders"
        assert by_tgt["cust_id"].source_columns == ["customer_id"]
        # cnt 来自 COUNT(*)，派生表内无物理源列 → 不产生带源的映射
        # （有意识的设计：聚合产生的列不杜撰源列）
        assert "cnt" not in by_tgt or by_tgt["cnt"].source_columns == []

    def test_nested_subquery_passthrough(self):
        """嵌套两层子查询 → 穿透到最底层物理表 [v2.2]"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO t (a) SELECT x FROM ("
                     "  SELECT x FROM (SELECT x FROM orders) d2"
                     ") d1")
        mappings = extract_column_mappings(stmt)

        assert len(mappings) == 1
        m = mappings[0]
        assert m.target_column == "a"
        assert m.source_table == "public.orders"
        assert m.source_columns == ["x"]

    def test_join_with_subquery(self):
        """JOIN + 子查询混合 → 各列穿透到正确物理表 [v2.2]"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO rep (oid, cname) "
                     "SELECT s.oid, c.name FROM ("
                     "  SELECT oid, cust_id FROM orders"
                     ") s JOIN customers c ON s.cust_id = c.id")
        mappings = extract_column_mappings(stmt)

        by_tgt = {m.target_column: m for m in mappings}
        # s.oid 穿透派生表 s → orders.oid
        assert by_tgt["oid"].source_table == "public.orders"
        assert by_tgt["oid"].source_columns == ["oid"]
        # c.name 直接来自物理表 customers
        assert by_tgt["cname"].source_table == "public.customers"
        assert by_tgt["cname"].source_columns == ["name"]

    def test_subquery_expression_passthrough(self):
        """派生表内表达式 → 穿透表达式提取源列 [v2.2]"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO calc (gross) SELECT gross FROM ("
                     "  SELECT price * qty AS gross FROM sales"
                     ") sub")
        mappings = extract_column_mappings(stmt)

        assert len(mappings) == 1
        m = mappings[0]
        assert m.target_column == "gross"
        assert m.source_table == "public.sales"
        assert set(m.source_columns) == {"price", "qty"}


class TestDegradation:
    """降级场景：无法解析时不应崩溃，返回空或部分结果"""

    def test_select_star_degrades(self):
        """SELECT * → 无表结构，跳过列级，返回空（降级为表级）"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO report SELECT * FROM src")
        mappings = extract_column_mappings(stmt)
        # SELECT * 跳过，无显式目标列也无 projection 列名可用 → 空
        assert mappings == []

    def test_no_explicit_target_cols(self):
        """INSERT INTO t SELECT a, b（无显式目标列）→ 用 projection 列名对齐"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO report SELECT x, y FROM src")
        mappings = extract_column_mappings(stmt)

        # 无显式目标列，target 退化用 projection 列名 x, y
        by_tgt = {m.target_column: m for m in mappings}
        assert "x" in by_tgt
        assert "y" in by_tgt

    def test_constant_projection(self):
        """常量 SELECT 1, 'x' → 源列为空，记录 transformation"""
        stmt = _stmt(1, StatementType.INSERT,
                     "INSERT INTO config (id, label) SELECT 1, 'active'")
        mappings = extract_column_mappings(stmt)

        by_tgt = {m.target_column: m for m in mappings}
        assert by_tgt["id"].source_columns == []
        assert by_tgt["id"].source_table == ""
        assert by_tgt["id"].transformation is not None

    def test_invalid_sql_graceful(self):
        """无效 SQL 不应抛异常"""
        stmt = _stmt(1, StatementType.INSERT, "THIS IS NOT SQL")
        mappings = extract_column_mappings(stmt)
        assert mappings == []


class TestUpdateColumnLineage:
    """UPDATE SET 子句的列级血缘"""

    def test_update_set_expression(self):
        """UPDATE SET total = total * 1.1 → total←total，transform=total * 1.1"""
        stmt = _stmt(1, StatementType.UPDATE,
                     "UPDATE orders SET total = total * 1.1 WHERE id = 1")
        mappings = extract_column_mappings(stmt)

        by_tgt = {m.target_column: m for m in mappings}
        assert "total" in by_tgt
        assert by_tgt["total"].source_columns == ["total"]
        assert by_tgt["total"].transformation is not None

    def test_update_set_constant(self):
        """UPDATE SET status = 'paid' → 源列为空（常量）"""
        stmt = _stmt(1, StatementType.UPDATE,
                     "UPDATE orders SET status = 'paid' WHERE id = 1")
        mappings = extract_column_mappings(stmt)

        by_tgt = {m.target_column: m for m in mappings}
        assert by_tgt["status"].source_columns == []
        assert by_tgt["status"].transformation is not None


class TestIntegrationWithLineages:
    """验证列级映射挂到 Lineage 上（集成层）"""

    def test_lineages_carry_column_mappings(self):
        """extract_lineages 产出的 Lineage 应携带 column_mappings"""
        stmts = [_stmt(1, StatementType.INSERT,
                       "INSERT INTO report (a, b) SELECT x, y FROM src")]
        lineages, _ = extract_lineages(stmts)

        assert len(lineages) >= 1
        lin = lineages[0]
        assert len(lin.column_mappings) == 2
        by_tgt = {m.target_column: m for m in lin.column_mappings}
        assert by_tgt["a"].source_columns == ["x"]
        assert by_tgt["b"].source_columns == ["y"]

    def test_table_level_still_works_with_column(self):
        """列级是附加层，不影响表级血缘"""
        stmts = [_stmt(1, StatementType.INSERT,
                       "INSERT INTO report (a) SELECT x FROM src")]
        lineages, _ = extract_lineages(stmts)

        # 表级边仍在
        assert len(lineages) == 1
        assert lineages[0].source_table == "public.src"
        assert lineages[0].target_table == "public.report"

    def test_select_star_table_level_preserved(self):
        """SELECT * 列级降级，但表级边仍正常生成"""
        stmts = [_stmt(1, StatementType.INSERT,
                       "INSERT INTO report SELECT * FROM src")]
        lineages, _ = extract_lineages(stmts)

        # 表级边在
        assert len(lineages) == 1
        assert lineages[0].source_table == "public.src"
        # 列级降级为空
        assert lineages[0].column_mappings == []
