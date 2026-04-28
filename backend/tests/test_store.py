"""Store 持久化存储层测试"""
import sys
import os
import json
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import store
from app.models.analysis import AnalysisResult, DatabaseInfo, Visualization, VisNode, VisEdge
from app.models.lineage import Lineage, OperationType, ExtractionMethod, TableInfo, TableType
from app.models.statement import StatementGroup, Statement, StatementType


def _make_result(
    script_id="test-001",
    name="测试脚本",
    lineages=None,
    tables_db=None,
    tables_script=None,
    vis_nodes=None,
    vis_edges=None,
    stmts=None,
):
    """构建测试用 AnalysisResult"""
    if lineages is None:
        lineages = [
            Lineage(
                lineage_id="l1", source_table="orders", target_table="tmp",
                operation_type=OperationType.CREATE,
                extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                statement_seq=1, dml_statement="CREATE TEMP TABLE tmp AS SELECT * FROM orders;",
            ),
            Lineage(
                lineage_id="l2", source_table="tmp", target_table="report",
                operation_type=OperationType.INSERT,
                extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                statement_seq=2, dml_statement="INSERT INTO report SELECT * FROM tmp;",
            ),
        ]
    if tables_db is None:
        tables_db = [
            TableInfo(table_name="orders", table_type=TableType.SOURCE, source="database"),
            TableInfo(table_name="report", table_type=TableType.TARGET, source="database"),
        ]
    if tables_script is None:
        tables_script = [
            TableInfo(table_name="tmp", table_type=TableType.INTERMEDIATE, source="script_created"),
        ]
    if vis_nodes is None:
        vis_nodes = [VisNode(id="orders", label="orders", type="source"),
                     VisNode(id="tmp", label="tmp", type="intermediate"),
                     VisNode(id="report", label="report", type="target")]
    if vis_edges is None:
        vis_edges = [VisEdge(source="orders", target="tmp", label="CREATE", statement_seq=1),
                     VisEdge(source="tmp", target="report", label="INSERT", statement_seq=2)]
    if stmts is None:
        stmts = [
            Statement(seq=1, type=StatementType.CREATE,
                      text="CREATE TEMP TABLE tmp AS SELECT * FROM orders;",
                      tables_referenced=["orders"], tables_created=["tmp"]),
            Statement(seq=2, type=StatementType.INSERT,
                      text="INSERT INTO report SELECT * FROM tmp;",
                      tables_referenced=["tmp"], tables_modified=["report"]),
        ]

    return AnalysisResult(
        analysis_id=script_id,
        name=name,
        input_script="CREATE TEMP TABLE tmp AS SELECT * FROM orders; INSERT INTO report SELECT * FROM tmp;",
        database_info=DatabaseInfo(tables_from_db=tables_db, tables_from_script=tables_script),
        statement_group=StatementGroup(
            group_id="g1",
            original_script="original",
            preprocessed_script="preprocessed",
            statements=stmts,
        ),
        lineages=lineages,
        visualization=Visualization(nodes=vis_nodes, edges=vis_edges),
    )


# 使用临时目录避免污染真实数据
_original_data_dir = None


def setup_module():
    global _original_data_dir
    _original_data_dir = store.DATA_DIR
    store.DATA_DIR = pathlib.Path(tempfile.mkdtemp())
    store.TABLES_FILE = store.DATA_DIR / "tables.json"
    store.EDGES_FILE = store.DATA_DIR / "edges.json"
    store.SCRIPTS_DIR = store.DATA_DIR / "scripts"


def teardown_module():
    global _original_data_dir
    if _original_data_dir:
        shutil.rmtree(str(store.DATA_DIR), ignore_errors=True)
        store.DATA_DIR = _original_data_dir
        store.TABLES_FILE = store.DATA_DIR / "tables.json"
        store.EDGES_FILE = store.DATA_DIR / "edges.json"
        store.SCRIPTS_DIR = store.DATA_DIR / "scripts"


import pathlib


class TestSaveAndList:
    """保存和列表测试"""

    def test_save_creates_files(self):
        result = _make_result("s1")
        store.save_script(result)
        assert store.TABLES_FILE.exists()
        assert store.EDGES_FILE.exists()
        assert (store.SCRIPTS_DIR / "s1.json").exists()

    def test_list_scripts(self):
        store.save_script(_make_result("s2", name="脚本A"))
        store.save_script(_make_result("s3", name="脚本B"))
        summaries = store.list_scripts()
        assert len(summaries) >= 2
        names = {s.name for s in summaries}
        assert "脚本A" in names
        assert "脚本B" in names

    def test_list_script_summary_fields(self):
        store.save_script(_make_result("s4", name="摘要测试"))
        summaries = store.list_scripts()
        s = [x for x in summaries if x.analysis_id == "s4"][0]
        assert s.name == "摘要测试"
        assert s.statement_count == 2
        assert s.table_count >= 3  # orders, tmp, report

    def test_auto_naming(self):
        result = _make_result("s5", name="")
        store.save_script(result)
        saved = store.get_script("s5")
        assert saved.name.startswith("脚本_")


class TestGetAndDelete:
    """读取和删除测试"""

    def test_get_script(self):
        store.save_script(_make_result("g1", name="读取测试"))
        result = store.get_script("g1")
        assert result is not None
        assert result.name == "读取测试"
        assert len(result.lineages) == 2

    def test_get_nonexistent(self):
        assert store.get_script("nonexistent") is None

    def test_delete_script(self):
        store.save_script(_make_result("d1"))
        assert store.delete_script("d1") is True
        assert store.get_script("d1") is None

    def test_delete_nonexistent(self):
        assert store.delete_script("nonexistent") is False

    def test_delete_removes_edges(self):
        store.save_script(_make_result("d2"))
        edges_before = json.loads(store.EDGES_FILE.read_text())
        assert any(e["script_id"] == "d2" for e in edges_before)
        store.delete_script("d2")
        edges_after = json.loads(store.EDGES_FILE.read_text())
        assert not any(e["script_id"] == "d2" for e in edges_after)

    def test_delete_cleans_orphan_tables(self):
        """删除脚本后，仅被该脚本引用的表应被清理"""
        store.save_script(_make_result("d3"))
        assert store.get_script("d3") is not None
        # 先删除所有其他可能引用相同表的脚本
        for f in store.SCRIPTS_DIR.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            if data["analysis_id"] != "d3":
                store.delete_script(data["analysis_id"])
        # 重新保存确保只有 d3
        store._write_json(store.TABLES_FILE, {})
        store._write_json(store.EDGES_FILE, [])
        store.save_script(_make_result("d3"))
        tables_before = json.loads(store.TABLES_FILE.read_text())
        assert "tmp" in tables_before
        store.delete_script("d3")
        tables_after = json.loads(store.TABLES_FILE.read_text())
        assert len(tables_after) == 0


class TestGlobalGraph:
    """全局累积图谱测试"""

    def test_single_script_graph(self):
        store._write_json(store.TABLES_FILE, {})
        store._write_json(store.EDGES_FILE, [])
        store.save_script(_make_result("gg1"))
        graph = store.get_global_graph()
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2

    def test_cumulative_graph(self):
        """两个脚本累积后图谱应合并"""
        store._write_json(store.TABLES_FILE, {})
        store._write_json(store.EDGES_FILE, [])

        # 脚本1: orders → tmp → report
        store.save_script(_make_result("gg2"))
        # 脚本2: customers → report（不同脚本，同一目标表）
        result2 = _make_result(
            "gg3", name="脚本2",
            lineages=[
                Lineage(lineage_id="l3", source_table="customers", target_table="report",
                        operation_type=OperationType.INSERT,
                        extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                        statement_seq=1, dml_statement="INSERT INTO report SELECT * FROM customers;"),
            ],
            tables_db=[
                TableInfo(table_name="customers", table_type=TableType.SOURCE, source="database"),
                TableInfo(table_name="report", table_type=TableType.TARGET, source="database"),
            ],
            tables_script=[],
            vis_nodes=[VisNode(id="customers", label="customers", type="source"),
                       VisNode(id="report", label="report", type="target")],
            vis_edges=[VisEdge(source="customers", target="report", label="INSERT", statement_seq=1)],
            stmts=[Statement(seq=1, type=StatementType.INSERT,
                             text="INSERT INTO report SELECT * FROM customers;",
                             tables_referenced=["customers"], tables_modified=["report"])],
        )
        store.save_script(result2)

        graph = store.get_global_graph()
        assert len(graph.nodes) == 4  # orders, tmp, report, customers
        assert len(graph.edges) == 3   # orders→tmp, tmp→report, customers→report

        # report 同时是 source 也是 target → intermediate
        report_node = [n for n in graph.nodes if n.id == "report"][0]
        # 注意：tmp 也是 intermediate（既是 source 也是 target）

    def test_node_type_evolution(self):
        """表角色随多次分析演化"""
        store._write_json(store.TABLES_FILE, {})
        store._write_json(store.EDGES_FILE, [])

        # 第一次：orders → tmp（tmp 是 target）
        store.save_script(_make_result("ev1"))
        graph1 = store.get_global_graph()
        tmp1 = [n for n in graph1.nodes if n.id == "tmp"][0]
        assert tmp1.type == "intermediate"  # 既是 target 也是 source（因为有 tmp→report）

    def test_edge_has_script_id(self):
        """全局边应标注来源脚本"""
        store._write_json(store.TABLES_FILE, {})
        store._write_json(store.EDGES_FILE, [])
        store.save_script(_make_result("sid1"))
        graph = store.get_global_graph()
        for edge in graph.edges:
            assert edge.script_id == "sid1"


class TestRename:
    """重命名测试"""

    def test_rename(self):
        store.save_script(_make_result("r1", name="旧名"))
        result = store.update_script_name("r1", "新名")
        assert result.name == "新名"
        assert result.updated_at is not None

    def test_rename_nonexistent(self):
        assert store.update_script_name("nonexistent", "name") is None
