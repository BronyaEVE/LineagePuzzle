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
        """orders → daily_summary 的全部路径（线性链只有一条）"""
        self.setup_chain()
        result = store.impact_analysis("public.orders")
        # paths[d] 现在是 list[list[str]]（全部路径），线性链只有一条
        paths = result["paths"]["public.daily_summary"]
        assert paths == [["public.orders", "public.tmp_detail", "public.order_report", "public.daily_summary"]]

    def test_upstream_paths(self):
        """daily_summary 的上游链路：每个上游表 → daily_summary 的全部路径。

        后端返回 upstream_paths（list[list[str]]），前端据此把所有真实链路边高亮。
        """
        self.setup_chain()
        result = store.impact_analysis("public.daily_summary")
        up_paths = result["upstream_paths"]
        # 直接上游 order_report 到 daily_summary 的路径（只有一条）
        assert up_paths["public.order_report"] == [["public.order_report", "public.daily_summary"]]
        # 最远上游 orders 的路径应贯穿整条链（只有一条，因为 setup_chain 是线性链）
        assert up_paths["public.orders"] == [
            ["public.orders", "public.tmp_detail", "public.order_report", "public.daily_summary"],
        ]
        # 所有上游表都在 upstream_paths 里有对应路径
        assert set(up_paths.keys()) == set(result["upstream"])

    def test_diamond_graph_all_paths(self):
        """菱形依赖：A→B→C 且 A→C 时，点击 C 应返回两条上游路径 [v2.3 核心修复]

        旧 shortest_path 实现只返回 [A,C] 最短路径，漏掉 A→B 这条实际发生的
        中间环节边，导致前端 A→B 不高亮（误导用户以为 A→B 与 C 无关）。
        改用 all_simple_paths 后，A→C 的两条路径 [A,C] 和 [A,B,C] 都返回，
        前端据此把 A→C、B→C、A→B 三条边都高亮。
        """
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_lineage_result("diamond1", [
            ("public.A", "public.B", "INSERT"),
            ("public.B", "public.C", "INSERT"),
            ("public.A", "public.C", "INSERT"),  # 菱形的直连边
        ]))

        result = store.impact_analysis("public.C")
        up_paths = result["upstream_paths"]

        # A→C 有两条路径（不再只有最短的那条）
        paths_from_A = up_paths["public.A"]
        paths_sorted = sorted(paths_from_A)  # 排序便于断言
        assert paths_sorted == [
            ["public.A", "public.B", "public.C"],  # 经 B 的链路
            ["public.A", "public.C"],              # 直连
        ]
        # B→C 只有一条
        assert up_paths["public.B"] == [["public.B", "public.C"]]

        # 前端展开这些路径得到的高亮边集合（模拟前端 buildEdgeSet 逻辑）
        highlighted_edges = set()
        for paths in up_paths.values():
            for path in paths:
                for i in range(len(path) - 1):
                    highlighted_edges.add(f"{path[i]}->{path[i+1]}")
        # 三条边都应被高亮（旧实现会漏 A->B）
        assert highlighted_edges == {"public.A->public.B", "public.B->public.C", "public.A->public.C"}

    def test_paths_truncated_flag(self):
        """路径未超过上限时 paths_truncated 为 False"""
        self.setup_chain()
        result = store.impact_analysis("public.orders")
        assert result["paths_truncated"] is False

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
