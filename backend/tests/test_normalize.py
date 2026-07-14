"""表名归一化工具测试

新语义：normalize_table_name 将表名规范化为 `schema.table` 全限定名，
裸表名（不带 schema 前缀）补默认 schema `public`。这样区分 public.orders
与 reporting.orders 等跨 schema 同名表。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.normalize import normalize_table_name


class TestNormalizeTableName:

    def test_plain_name(self):
        """裸表名补 public"""
        assert normalize_table_name("orders") == "public.orders"

    def test_schema_prefix(self):
        """带 schema 前缀保留"""
        assert normalize_table_name("public.orders") == "public.orders"

    def test_catalog_schema_prefix(self):
        """catalog.database 前缀去掉，保留 schema.table"""
        assert normalize_table_name("mydb.public.orders") == "public.orders"

    def test_empty_string(self):
        assert normalize_table_name("") == ""

    def test_quoted_identifier(self):
        """带引号标识符保留大小写，补 public"""
        assert normalize_table_name('"Orders"') == "public.Orders"

    def test_quoted_schema_quoted_table(self):
        assert normalize_table_name('"public"."Orders"') == "public.Orders"

    def test_triple_quoted(self):
        """catalog.schema.table（带引号）→ schema.table"""
        assert normalize_table_name('"mydb"."public"."Orders"') == "public.Orders"

    def test_whitespace(self):
        assert normalize_table_name("  public.orders  ") == "public.orders"

    def test_custom_schema(self):
        """非 public schema 保留"""
        assert normalize_table_name("analytics.fact_sales") == "analytics.fact_sales"

    def test_quoted_identifier_with_dot(self):
        """引号内的点号不应被拆分；整体作为表名，补 public"""
        assert normalize_table_name('"my.schema".orders') == "my.schema.orders"

    def test_mixed_quoted_unquoted(self):
        """public."Orders" → public.Orders"""
        assert normalize_table_name('public."Orders"') == "public.Orders"

    def test_long_chain(self):
        """长链取最后两段作 schema.table"""
        assert normalize_table_name("a.b.c.d.target") == "d.target"

    def test_unquoted_folded_to_lowercase(self):
        """不带引号的标识符折叠成小写（PostgreSQL 语义）

        PG 里 ORDERS == orders == Orders（不带引号都折叠小写）。
        这样避免同一张表因大小写不同被算成多张表。
        """
        assert normalize_table_name("public.MyTable") == "public.mytable"
        assert normalize_table_name("ORDERS") == "public.orders"
        assert normalize_table_name("Orders") == "public.orders"
        assert normalize_table_name("orders") == "public.orders"
        # ORDERS 和 orders 归一化后应相等
        assert normalize_table_name("public.ORDERS") == normalize_table_name("public.orders")

    def test_quoted_case_preserved(self):
        """带引号的标识符保留原大小写（PostgreSQL 语义）"""
        assert normalize_table_name('"Orders"') == "public.Orders"
        assert normalize_table_name('"public"."MyTable"') == "public.MyTable"
        # 带引号和不带引号的是不同的表（PG 语义）
        assert normalize_table_name('"Orders"') != normalize_table_name("Orders")

    def test_cross_schema_distinct(self):
        """跨 schema 同名表必须区分（这是新设计的核心价值）"""
        assert normalize_table_name("public.orders") == "public.orders"
        assert normalize_table_name("reporting.orders") == "reporting.orders"
        assert normalize_table_name("public.orders") != normalize_table_name("reporting.orders")
