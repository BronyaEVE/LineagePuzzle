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


class TestTransactionControl:
    """事务控制关键字（BEGIN/COMMIT/ROLLBACK）补分号测试

    设计：preprocess 不剥离事务关键字，只给行首事务关键字补分号（若缺）。
    splitter 用 str.split(";") 切分后，BEGIN/COMMIT 等会被 _should_keep 过滤掉。
    完全不碰 END（CASE WHEN...END 中 END 合法，剥离会切断 CASE 表达式）。
    """

    def test_begin_with_semicolon(self):
        sql = "BEGIN;\nINSERT INTO t SELECT * FROM src;\nCOMMIT;"
        result = preprocess(sql)
        # BEGIN/COMMIT 被补分号后，INSERT 不受影响
        assert "INSERT INTO t" in result
        assert "SELECT * FROM src" in result

    def test_bare_begin_without_semicolon(self):
        """裸 BEGIN 无分号：补分号后 INSERT 必须独立，不能被 BEGIN 吞掉"""
        sql = "BEGIN\nINSERT INTO t SELECT * FROM src;\nCOMMIT;"
        result = preprocess(sql)
        # 关键：INSERT 必须保留，不能被 BEGIN 吞掉
        assert "INSERT INTO t" in result
        assert "SELECT * FROM src" in result

    def test_bare_begin_multiline_block(self):
        """裸 BEGIN + 缩进多语句块：每条 DML 都要保留"""
        sql = (
            "BEGIN\n"
            "  INSERT INTO t (a) SELECT id FROM src;\n"
            "  UPDATE t SET a = 1;\n"
            "COMMIT;"
        )
        result = preprocess(sql)
        assert "INSERT INTO t" in result
        assert "UPDATE t SET a = 1" in result

    def test_begin_transaction_keyword(self):
        sql = "BEGIN TRANSACTION;\nINSERT INTO t SELECT * FROM src;\nCOMMIT;"
        result = preprocess(sql)
        assert "INSERT INTO t" in result

    def test_start_transaction(self):
        sql = "START TRANSACTION;\nINSERT INTO t SELECT * FROM src;\nCOMMIT;"
        result = preprocess(sql)
        assert "INSERT INTO t" in result

    def test_rollback_block(self):
        sql = "BEGIN\nINSERT INTO t SELECT * FROM src;\nROLLBACK;"
        result = preprocess(sql)
        assert "INSERT INTO t" in result

    def test_control_keywords_isolated(self):
        """事务关键字补分号后单独成段（便于 splitter 用 _should_keep 过滤）"""
        sql = "BEGIN\nINSERT INTO t SELECT * FROM src;\nCOMMIT"
        result = preprocess(sql)
        lines = result.splitlines()
        # BEGIN 和 COMMIT 不应和 DML 出现在同一行
        for line in lines:
            if "INSERT INTO" in line:
                assert not line.upper().startswith("BEGIN")
                assert not line.upper().startswith("COMMIT")

    def test_bare_begin_keyword_gets_semicolon(self):
        """裸 BEGIN（无分号）必须被补上分号，否则 splitter 按分号切分会
        把 BEGIN 和后续 DML 粘在一起，导致 _should_keep 整段丢弃。"""
        sql = "BEGIN\nINSERT INTO t SELECT * FROM src;"
        result = preprocess(sql)
        # BEGIN 行必须有分号
        begin_line = next(l for l in result.splitlines() if l.upper().startswith("BEGIN"))
        assert begin_line.rstrip().endswith(";"), f"BEGIN 行未补分号: {begin_line!r}"


class TestCaseWhenEndNotStripped:
    """CASE WHEN...END 的 END 不能被当作事务块 END 处理

    回归测试：早期事务控制正则匹配了裸 END 并补分号/剥离，导致所有换行
    写在行首的 CASE...END 被插入分号切断（END;\\n AS alias），整条 INSERT
    被 splitter 拆碎、FROM 子句丢失，最终只显示目标表无源表。

    现行方案：preprocess 完全不碰 END（CASE 的 END 和事务块的 END 纯正则
    无法区分），事务块靠 BEGIN...COMMIT 即可闭合。
    """

    def test_case_when_end_preserved_inline(self):
        """单行 CASE WHEN...END 不被切断"""
        sql = "INSERT INTO t (a) SELECT CASE WHEN x THEN 1 ELSE 2 END AS a FROM src;"
        result = preprocess(sql)
        assert "END AS a" in result
        # 不应在 CASE 表达式中间出现孤立分号
        assert "END;" not in result

    def test_case_when_end_on_own_line(self):
        """CASE 的 END 换行写在行首（真实 ETL 脚本常见写法）不被切断

        这是实际触发 bug 的写法：每个 CASE 的 END 都顶格换行，
        旧正则 ^\\s*END 把它误判成事务块结束符。
        """
        sql = (
            "INSERT INTO t (a)\n"
            "SELECT\n"
            "CASE WHEN P1.x = 1 THEN P1.a\n"
            "ELSE P1.b\n"
            "END AS a\n"
            "FROM src P1;"
        )
        result = preprocess(sql)
        # END AS a 必须保持完整，不能变成 END;\n AS a
        assert "END AS a" in result
        assert "END;\n" not in result
        assert "END;" not in result

    def test_multiple_case_when_in_select(self):
        """多个 CASE WHEN...END 都不能被切断（来自真实 bug 报告的复现场景）"""
        sql = (
            "INSERT INTO ${icl_schema}.t (a, b)\n"
            "SELECT\n"
            "CASE WHEN P1.x = 'Y' THEN P1.a\n"
            "ELSE P1.b\n"
            "END AS a\n"
            ",CASE WHEN P1.y = '0' THEN P1.c\n"
            "ELSE P1.d\n"
            "END AS b\n"
            "FROM ${iol_schema}.src P1;"
        )
        result = preprocess(sql)
        assert "END AS a" in result
        assert "END AS b" in result
        # 整段只有一个分号（结尾），CASE 中间不应有分号
        assert result.count(";") == 1

    def test_case_when_source_table_preserved(self):
        """CASE WHEN 语句经 preprocess + split 后 FROM 子句不丢失

        端到端验证：bug 的现象是只显示目标表、无源表无边。
        根因是 END 被切断后 FROM 子句被 splitter 切到下一段丢弃。
        """
        from app.services.splitter import split_statements

        sql = (
            "INSERT INTO target_t (label)\n"
            "SELECT\n"
            "CASE WHEN s.status = 1 THEN 'paid'\n"
            "ELSE 'unpaid'\n"
            "END AS label\n"
            "FROM source_t s;"
        )
        cleaned = preprocess(sql)
        group = split_statements(cleaned, original_script=sql)
        assert len(group.statements) == 1, f"应只切出1条语句,实际{len(group.statements)}"
        stmt_text = group.statements[0].text
        # FROM 子句必须保留在这条语句里
        assert "FROM source_t" in stmt_text


class TestDoBlockExtraction:
    """DO $$ ... $$ 匿名块内的 DML 提取测试

    生产脚本常把 DML 包在 DO $$ BEGIN ... EXCEPTION WHEN OTHERS THEN
    RAISE ... END $$; 里做异常处理。sqlglot 无法解析 PL/pgSQL（降级为
    Command，表血缘丢失）。preprocess 用正则把 DML 从 block 内抠出来，
    去掉 PL/pgSQL 控制关键字（BEGIN/END/EXCEPTION/RAISE 等）。
    """

    def test_simple_do_block_extracted(self):
        """简单 DO block 内的单条 INSERT 应被提取出来"""
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO t (a) SELECT id FROM src;\n"
            "END\n"
            "$$;"
        )
        result = preprocess(sql)
        assert "INSERT INTO t" in result
        assert "SELECT id FROM src" in result
        # PL/pgSQL 外壳应被去掉
        assert "DO" not in result
        assert "BEGIN" not in result

    def test_do_block_with_exception(self):
        """DO block 带 EXCEPTION 异常处理 —— 用户真实场景"""
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO t (a) SELECT id FROM src;\n"
            "EXCEPTION WHEN OTHERS THEN\n"
            "  RAISE NOTICE 'sqlstate:%', sqlstate;\n"
            "END\n"
            "$$;"
        )
        result = preprocess(sql)
        # DML 必须保留
        assert "INSERT INTO t" in result
        assert "SELECT id FROM src" in result
        # 异常处理代码应被去掉
        assert "EXCEPTION" not in result
        assert "RAISE" not in result
        assert "sqlstate" not in result

    def test_do_block_multiple_dml(self):
        """DO block 内多条 DML 都应被提取"""
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO t1 (a) SELECT id FROM src1;\n"
            "  UPDATE t2 SET a = 1 WHERE x = 2;\n"
            "  DELETE FROM t3 WHERE used = false;\n"
            "EXCEPTION WHEN OTHERS THEN\n"
            "  RAISE NOTICE 'err';\n"
            "END\n"
            "$$;"
        )
        result = preprocess(sql)
        assert "INSERT INTO t1" in result
        assert "UPDATE t2 SET a = 1" in result
        assert "DELETE FROM t3" in result

    def test_do_block_with_case_when_preserved(self):
        """DO block 内的 CASE WHEN...END 必须完整保留

        端到端：DO block 提取不能破坏 CASE 表达式（END 不能被当作块结束）。
        """
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO r (lbl)\n"
            "  SELECT CASE WHEN s.x = 1 THEN 'a' ELSE 'b' END AS lbl\n"
            "  FROM src s;\n"
            "EXCEPTION WHEN OTHERS THEN\n"
            "  RAISE NOTICE 'err';\n"
            "END\n"
            "$$;"
        )
        result = preprocess(sql)
        # CASE 的 END AS 必须完整
        assert "END AS lbl" in result

    def test_custom_dollar_quote_tag(self):
        """自定义 dollar-quote tag（$body$、$func$ 等）"""
        sql = (
            "DO $body$\n"
            "BEGIN\n"
            "  INSERT INTO t (a) SELECT id FROM src;\n"
            "END\n"
            "$body$;"
        )
        result = preprocess(sql)
        assert "INSERT INTO t" in result
        assert "SELECT id FROM src" in result

    def test_mixed_bare_sql_and_do_block(self):
        """生产真实场景：裸 SQL + DO block 混合"""
        sql = (
            "INSERT INTO a (x) SELECT y FROM s1;\n"
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO b (x) SELECT y FROM s2;\n"
            "EXCEPTION WHEN OTHERS THEN\n"
            "  RAISE NOTICE 'err';\n"
            "END\n"
            "$$;\n"
            "INSERT INTO c (x) SELECT y FROM s3;"
        )
        result = preprocess(sql)
        # 三条 DML 都要在
        assert "INSERT INTO a" in result
        assert "INSERT INTO b" in result
        assert "INSERT INTO c" in result
        # DO block 外壳要去掉
        assert "DO $$" not in result
        assert "EXCEPTION" not in result

    def test_do_block_empty(self):
        """空 DO block（只有异常处理，无 DML）不报错"""
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  RAISE NOTICE 'no dml here';\n"
            "EXCEPTION WHEN OTHERS THEN\n"
            "  NULL;\n"
            "END\n"
            "$$;"
        )
        result = preprocess(sql)
        # 不应崩溃，也不应残留 PL/pgSQL 关键字
        assert "RAISE" not in result
        assert "EXCEPTION" not in result

    def test_do_block_dml_source_table_extracted(self):
        """端到端：DO block 内 DML 的源表必须被识别（不只是文本保留）"""
        from app.services.splitter import split_statements
        from app.services.lineage_extractor import extract_lineages

        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  INSERT INTO target_t (a) SELECT id FROM source_t;\n"
            "EXCEPTION WHEN OTHERS THEN\n"
            "  RAISE NOTICE 'err';\n"
            "END\n"
            "$$;"
        )
        cleaned = preprocess(sql)
        group = split_statements(cleaned, original_script=sql)
        assert len(group.statements) == 1
        lineages, _ = extract_lineages(group.statements)
        # 必须生成 source -> target 的边，而不是只剩 target
        assert len(lineages) == 1
        assert lineages[0].source_table == "public.source_t"
        assert lineages[0].target_table == "public.target_t"
