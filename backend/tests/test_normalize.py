"""表名归一化工具测试"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.normalize import normalize_table_name


class TestNormalizeTableName:

    def test_plain_name(self):
        assert normalize_table_name("orders") == "orders"

    def test_schema_prefix(self):
        assert normalize_table_name("public.orders") == "orders"

    def test_catalog_schema_prefix(self):
        assert normalize_table_name("mydb.public.orders") == "orders"

    def test_empty_string(self):
        assert normalize_table_name("") == ""

    def test_quoted_identifier(self):
        assert normalize_table_name('"Orders"') == "Orders"

    def test_quoted_schema_quoted_table(self):
        assert normalize_table_name('"public"."Orders"') == "Orders"

    def test_triple_quoted(self):
        assert normalize_table_name('"mydb"."public"."Orders"') == "Orders"

    def test_whitespace(self):
        assert normalize_table_name("  public.orders  ") == "orders"

    def test_custom_schema(self):
        assert normalize_table_name("analytics.fact_sales") == "fact_sales"

    def test_quoted_identifier_with_dot(self):
        """引号内的点号不应被拆分"""
        assert normalize_table_name('"my.schema".orders') == "orders"

    def test_mixed_quoted_unquoted(self):
        assert normalize_table_name('public."Orders"') == "Orders"

    def test_long_chain(self):
        assert normalize_table_name("a.b.c.d.target") == "target"

    def test_lowercase_preserved(self):
        assert normalize_table_name("public.MyTable") == "MyTable"
