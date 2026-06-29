"""影响分析测试：networkx 内存图的下游/上游/路径/环检测。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import store
from app.models.analysis import AnalysisResult, DatabaseInfo, Visualization, VisNode, VisEdge
from app.models.lineage import Lineage, OperationType, ExtractionMethod, TableInfo, TableType
from app.models.statement import StatementGroup, Statement, StatementType


def _make_lineage_result(script_id, edges):
    """构建测试用 AnalysisResult（只关心 edges）。"""
    lineages = []
    vis_edges = []
    for i, (src, tgt, op) in enumerate(edges):
        op_enum = OperationType[op]
        lineages.append(Lineage(
            lineage_id=f"l-{script_id}-{i}", source_table=src, target_table=tgt,
            operation_type=op_enum, extraction_method=ExtractionMethod.STATIC_ANALYSIS,
            statement_seq=1, dml_statement="test",
        ))
        vis_edges.append(VisEdge(source=src, target=tgt, label=op, statement_seq=1))
    nodes = set()
    for src, tgt, _ in edges:
        nodes.add(src)
        nodes.add(tgt)
    return AnalysisResult(
        analysis_id=script_id, name=script_id,
        created_at="2026-01-01", input_script="test",
        database_info=DatabaseInfo(),
        statement_group=None,
        lineages=lineages,
        visualization=Visualization(
            nodes=[VisNode(id=n, label=n, type="source") for n in sorted(nodes)],
            edges=vis_edges,
        ),
    )


class TestBuildGraph:
    """内存图构建测试"""

    def test_build_graph_from_edges(self):
        """edges.jsonl 能正确构建有向图"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_lineage_result("g1", [
            ("public.orders", "public.tmp", "CREATE"),
            ("public.tmp", "public.report", "INSERT"),
        ]))

        G = store.build_graph()
        assert G.number_of_nodes() == 3
        assert G.number_of_edges() == 2
        assert G.has_edge("public.orders", "public.tmp")
        assert G.has_edge("public.tmp", "public.report")

    def test_empty_graph(self):
        """空 edges 构建空图"""
        store._write_edges([])
        G = store.build_graph()
        assert G.number_of_nodes() == 0
        assert G.number_of_edges() == 0


class TestImpactAnalysis:
    """影响分析测试"""

    def setup_chain(self):
        """构建测试链路：orders → tmp → report → summary"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_lineage_result("chain1", [
            ("public.orders", "public.tmp_detail", "CREATE"),
            ("public.customers", "public.tmp_detail", "CREATE"),
            ("public.tmp_detail", "public.order_report", "INSERT"),
            ("public.order_report", "public.daily_summary", "INSERT"),
        ]))

    def test_downstream(self):
        """改 orders 会影响哪些下游表"""
        self.setup_chain()
        result = store.impact_analysis("public.orders")
        assert "public.tmp_detail" in result["downstream"]
        assert "public.order_report" in result["downstream"]
        assert "public.daily_summary" in result["downstream"]
        assert result["downstream_count"] == 3

    def test_upstream(self):
        """daily_summary 的数据来自哪些上游"""
        self.setup_chain()
        result = store.impact_analysis("public.daily_summary")
        assert "public.order_report" in result["upstream"]
        assert "public.tmp_detail" in result["upstream"]
        assert "public.orders" in result["upstream"]
        assert "public.customers" in result["upstream"]
        assert result["upstream_count"] == 4

    def test_paths(self):
        """orders → daily_summary 的最短路径"""
        self.setup_chain()
        result = store.impact_analysis("public.orders")
        path = result["paths"]["public.daily_summary"]
        assert path == ["public.orders", "public.tmp_detail", "public.order_report", "public.daily_summary"]

    def test_no_cycle(self):
        """正常血缘图没有环"""
        self.setup_chain()
        result = store.impact_analysis("public.orders")
        assert result["has_cycle"] is False

    def test_cycle_detection(self):
        """环检测：A→B→A 应被检测到"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_lineage_result("cyc1", [
            ("public.a", "public.b", "INSERT"),
            ("public.b", "public.a", "INSERT"),
        ]))
        result = store.impact_analysis("public.a")
        assert result["has_cycle"] is True

    def test_leaf_node(self):
        """叶子节点（最下游）没有下游"""
        self.setup_chain()
        result = store.impact_analysis("public.daily_summary")
        assert result["downstream"] == []
        assert result["downstream_count"] == 0

    def test_root_node(self):
        """根节点（最上游）没有上游"""
        self.setup_chain()
        result = store.impact_analysis("public.orders")
        assert result["upstream"] == []

    def test_nonexistent_table(self):
        """查不存在的表返回 error"""
        self.setup_chain()
        result = store.impact_analysis("public.not_exist")
        assert "error" in result

    def test_multi_source_convergence(self):
        """多源汇聚：orders 和 customers 都流向 tmp_detail"""
        self.setup_chain()
        result = store.impact_analysis("public.tmp_detail")
        # tmp_detail 的上游是 orders 和 customers
        assert "public.orders" in result["upstream"]
        assert "public.customers" in result["upstream"]
