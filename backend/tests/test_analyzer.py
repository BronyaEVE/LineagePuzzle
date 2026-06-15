"""analyzer 编排测试：离线模式 + extraction_mode 标记"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analyzer import analyze


class TestOfflineMode:
    """DESIGN.v2 §7.1：无 DB 连接的离线模式（database_config=None）"""

    def test_offline_produces_lineages(self):
        """db_config=None 时不连 DB，纯 AST 也能产出血缘"""
        script = "INSERT INTO target SELECT * FROM source;"
        result = analyze(script, None)

        assert result.extraction_mode == "ast_only"
        assert len(result.lineages) == 1
        assert result.lineages[0].source_table == "public.source"
        assert result.lineages[0].target_table == "public.target"
        # 离线模式不连 DB，tables_from_db 应为空
        assert result.database_info.tables_from_db == []

    def test_offline_multi_statement(self):
        """离线模式多语句脚本（含临时表）血缘链路完整"""
        script = (
            "CREATE TEMP TABLE tmp AS SELECT * FROM orders;"
            "INSERT INTO report SELECT * FROM tmp;"
        )
        result = analyze(script, None)

        assert result.extraction_mode == "ast_only"
        # 两条血缘：orders→tmp, tmp→report
        assert len(result.lineages) == 2
        src_targets = {(l.source_table, l.target_table) for l in result.lineages}
        assert ("public.orders", "public.tmp") in src_targets
        assert ("public.tmp", "public.report") in src_targets

    def test_offline_extraction_method_static(self):
        """离线模式所有血缘的 extraction_method 都是 static_analysis"""
        script = "INSERT INTO t SELECT * FROM a JOIN b ON a.id = b.id;"
        result = analyze(script, None)
        for lin in result.lineages:
            assert lin.extraction_method.value == "static_analysis"


class TestBadDbConfigDegradesGracefully:
    """DB 连接失败时应降级为 ast_only，不抛异常"""

    def test_bad_db_config_falls_back_to_ast(self):
        """连接不存在的 DB，降级为 ast_only 仍返回血缘"""
        from app.schemas.requests import DatabaseConfig
        bad_config = DatabaseConfig(
            host="localhost", port=1, database="nonexistent",
            username="x", password="x",
        )
        script = "INSERT INTO target SELECT * FROM source;"
        # 不应抛异常
        result = analyze(script, bad_config)
        # 降级为 ast_only
        assert result.extraction_mode == "ast_only"
        assert len(result.lineages) == 1
