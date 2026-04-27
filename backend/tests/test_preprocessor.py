"""预处理模块测试"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.preprocessor import preprocess


class TestRemoveComments:
    """注释移除测试"""

    def test_single_line_comment(self):
        sql = "SELECT * FROM t -- 这是注释\nWHERE id = 1"
        result = preprocess(sql)
        assert "--" not in result
        assert "SELECT * FROM t" in result
        assert "WHERE id = 1" in result

    def test_multi_line_comment(self):
        sql = "SELECT /* 内联注释 */ * FROM t"
        result = preprocess(sql)
        assert "/*" not in result
        assert "*/" not in result
        assert "SELECT" in result
        assert "FROM t" in result

    def test_comment_only_line(self):
        sql = "-- 整行注释\nINSERT INTO t VALUES (1);"
        result = preprocess(sql)
        assert result == "INSERT INTO t VALUES (1);"

    def test_block_comment_multiline(self):
        sql = "/* 第一行\n第二行\n第三行 */ INSERT INTO t VALUES (1);"
        result = preprocess(sql)
        assert "INSERT INTO t VALUES (1);" in result
        assert "第一行" not in result

    def test_mixed_comments(self):
        sql = """
        -- 头部注释
        INSERT /* 内联 */ INTO t
        -- 中间注释
        VALUES (1);
        """
        result = preprocess(sql)
        assert "--" not in result
        assert "/*" not in result
        assert "INSERT" in result
        assert "INTO t" in result
        assert "VALUES (1);" in result


class TestWhitespace:
    """空格压缩测试"""

    def test_compress_spaces(self):
        sql = "SELECT   *    FROM     t"
        result = preprocess(sql)
        assert "   " not in result
        assert "SELECT * FROM t" in result

    def test_remove_blank_lines(self):
        sql = "INSERT INTO t VALUES (1);\n\n\n\nINSERT INTO t VALUES (2);"
        result = preprocess(sql)
        assert "\n\n" not in result

    def test_trim_lines(self):
        sql = "  SELECT * FROM t  \n  WHERE id = 1  "
        result = preprocess(sql)
        for line in result.splitlines():
            assert line == line.strip()

    def test_empty_script(self):
        assert preprocess("") == ""

    def test_whitespace_only(self):
        assert preprocess("   \n   \n   ") == ""


class TestPreserveCreate:
    """验证 CREATE TABLE 语句被保留"""

    def test_create_table_preserved(self):
        sql = "CREATE TABLE tmp AS SELECT * FROM src;"
        result = preprocess(sql)
        assert "CREATE TABLE tmp" in result

    def test_create_temp_table_preserved(self):
        sql = "CREATE TEMP TABLE tmp AS SELECT * FROM src;"
        result = preprocess(sql)
        assert "CREATE TEMP TABLE tmp" in result

    def test_create_temporary_table_preserved(self):
        sql = "CREATE TEMPORARY TABLE tmp AS SELECT * FROM src;"
        result = preprocess(sql)
        assert "CREATE TEMPORARY TABLE tmp" in result
