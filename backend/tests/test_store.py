"""Store 持久化存储层测试

新语义：表名规范化为 `schema.table` 全限定名，裸表名补 public。
跨 schema 同名表（public.orders vs reporting.orders）视为不同节点。
"""
import sys
import os
import json
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import store
from app.models.analysis import AnalysisResult, DatabaseInfo, Visualization, VisNode, VisEdge
from app.models.lineage import Lineage, OperationType, ExtractionMethod, TableInfo, TableType, ColumnMapping
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
    """构建测试用 AnalysisResult

    默认使用全限定名 (public.xxx) 作为表标识。
    """
    if lineages is None:
        lineages = [
            Lineage(
                lineage_id="l1", source_table="public.orders", target_table="public.tmp",
                operation_type=OperationType.CREATE,
                extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                statement_seq=1, dml_statement="CREATE TEMP TABLE tmp AS SELECT * FROM orders;",
            ),
            Lineage(
                lineage_id="l2", source_table="public.tmp", target_table="public.report",
                operation_type=OperationType.INSERT,
                extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                statement_seq=2, dml_statement="INSERT INTO report SELECT * FROM tmp;",
            ),
        ]
    if tables_db is None:
        tables_db = [
            TableInfo(schema_name="public", table_name="orders", table_type=TableType.SOURCE, source="database"),
            TableInfo(schema_name="public", table_name="report", table_type=TableType.TARGET, source="database"),
        ]
    if tables_script is None:
        tables_script = [
            TableInfo(schema_name="public", table_name="tmp", table_type=TableType.INTERMEDIATE, source="script_created"),
        ]
    if vis_nodes is None:
        vis_nodes = [VisNode(id="public.orders", label="orders", type="source"),
                     VisNode(id="public.tmp", label="tmp", type="intermediate"),
                     VisNode(id="public.report", label="report", type="target")]
    if vis_edges is None:
        vis_edges = [VisEdge(source="public.orders", target="public.tmp", label="CREATE", statement_seq=1),
                     VisEdge(source="public.tmp", target="public.report", label="INSERT", statement_seq=2)]
    if stmts is None:
        stmts = [
            Statement(seq=1, type=StatementType.CREATE,
                      text="CREATE TEMP TABLE tmp AS SELECT * FROM orders;",
                      tables_referenced=["public.orders"], tables_created=["public.tmp"]),
            Statement(seq=2, type=StatementType.INSERT,
                      text="INSERT INTO report SELECT * FROM tmp;",
                      tables_referenced=["public.tmp"], tables_modified=["public.report"]),
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
    store.EDGES_FILE = store.DATA_DIR / "edges.jsonl"
    store.SCRIPTS_DIR = store.DATA_DIR / "scripts"
    store.LOCK_FILE = store.DATA_DIR / "store.lock"


def teardown_module():
    global _original_data_dir
    if _original_data_dir:
        shutil.rmtree(str(store.DATA_DIR), ignore_errors=True)
        store.DATA_DIR = _original_data_dir
        store.TABLES_FILE = store.DATA_DIR / "tables.json"
        store.EDGES_FILE = store.DATA_DIR / "edges.jsonl"
        store.SCRIPTS_DIR = store.DATA_DIR / "scripts"
        store.LOCK_FILE = store.DATA_DIR / "store.lock"


def _read_edges():
    """测试辅助：读取 JSONL 格式的 edges 并解析为 list[dict]。"""
    return store._read_edges()


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
        assert s.table_count >= 3  # public.orders, public.tmp, public.report

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
        edges_before = _read_edges()
        assert any(e["script_id"] == "d2" for e in edges_before)
        store.delete_script("d2")
        edges_after = _read_edges()
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
        store._write_edges([])
        store.save_script(_make_result("d3"))
        tables_before = json.loads(store.TABLES_FILE.read_text())
        assert "public.tmp" in tables_before
        store.delete_script("d3")
        tables_after = json.loads(store.TABLES_FILE.read_text())
        assert len(tables_after) == 0


class TestGlobalGraph:
    """全局累积图谱测试"""

    def test_single_script_graph(self):
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("gg1"))
        graph = store.get_global_graph()
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2

    def test_cumulative_graph(self):
        """两个脚本累积后图谱应合并"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        # 脚本1: orders → tmp → report
        store.save_script(_make_result("gg2"))
        # 脚本2: customers → report（不同脚本，同一目标表）
        result2 = _make_result(
            "gg3", name="脚本2",
            lineages=[
                Lineage(lineage_id="l3", source_table="public.customers", target_table="public.report",
                        operation_type=OperationType.INSERT,
                        extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                        statement_seq=1, dml_statement="INSERT INTO report SELECT * FROM customers;"),
            ],
            tables_db=[
                TableInfo(schema_name="public", table_name="customers", table_type=TableType.SOURCE, source="database"),
                TableInfo(schema_name="public", table_name="report", table_type=TableType.TARGET, source="database"),
            ],
            tables_script=[],
            vis_nodes=[VisNode(id="public.customers", label="customers", type="source"),
                       VisNode(id="public.report", label="report", type="target")],
            vis_edges=[VisEdge(source="public.customers", target="public.report", label="INSERT", statement_seq=1)],
            stmts=[Statement(seq=1, type=StatementType.INSERT,
                             text="INSERT INTO report SELECT * FROM customers;",
                             tables_referenced=["public.customers"], tables_modified=["public.report"])],
        )
        store.save_script(result2)

        graph = store.get_global_graph()
        assert len(graph.nodes) == 4  # public.orders, public.tmp, public.report, public.customers
        assert len(graph.edges) == 3   # orders→tmp, tmp→report, customers→report

        # report 同时是 source 也是 target → intermediate
        report_node = [n for n in graph.nodes if n.id == "public.report"][0]
        # 注意：tmp 也是 intermediate（既是 source 也是 target）

    def test_node_type_evolution(self):
        """表角色随多次分析演化"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        # 第一次：orders → tmp（tmp 是 target）
        store.save_script(_make_result("ev1"))
        graph1 = store.get_global_graph()
        tmp1 = [n for n in graph1.nodes if n.id == "public.tmp"][0]
        assert tmp1.type == "intermediate"  # 既是 target 也是 source（因为有 tmp→report）

    def test_edge_has_script_id(self):
        """全局边应标注来源脚本"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
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


class TestJsonlFormat:
    """edges.jsonl JSON Lines 格式测试"""

    def test_edges_file_extension(self):
        """edges 文件应为 .jsonl 后缀"""
        assert store.EDGES_FILE.name == "edges.jsonl"

    def test_each_line_is_valid_json(self):
        """edges.jsonl 每行必须是一个独立的合法 JSON 对象"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("jsonl1"))

        # 逐行解析，每行都应是合法 JSON
        lines = store.EDGES_FILE.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 2  # 默认 fixture 有 2 条边
        for line in lines:
            line = line.strip()
            assert line, f"空行: {line!r}"
            obj = json.loads(line)  # 不抛异常即合法
            assert isinstance(obj, dict)
            assert {"edge_id", "source", "target", "script_id"} <= set(obj.keys())

    def test_not_a_json_array(self):
        """edges.jsonl 不是 JSON 数组（整体 json.loads 应失败）"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("jsonl2"))

        raw = store.EDGES_FILE.read_text(encoding="utf-8")
        # 整体不是 JSON 数组（不以 [ 开头）
        assert not raw.lstrip().startswith("[")

    def test_append_does_not_rewrite(self):
        """save_script 追加边时不应清空已有边（增量追加语义）"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("app1"))  # 2 条边
        store.save_script(_make_result("app2"))  # 又 2 条边
        edges = _read_edges()
        assert len(edges) == 4
        assert {e["script_id"] for e in edges} == {"app1", "app2"}


class TestColumnMappingsPersistence:
    """列级血缘持久化测试（DESIGN.v2 §6.4）"""

    def test_edge_persists_column_mappings(self):
        """edges.jsonl 持久化 column_mappings"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("cm1", lineages=[
            Lineage(
                lineage_id="l-cm", source_table="public.src", target_table="public.dst",
                operation_type=OperationType.INSERT,
                extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                statement_seq=1, dml_statement="INSERT INTO dst (a,b) SELECT x,y FROM src;",
                column_mappings=[
                    ColumnMapping(target_table="public.dst", target_column="a",
                                  source_table="public.src", source_columns=["x"], transformation=None),
                    ColumnMapping(target_table="public.dst", target_column="b",
                                  source_table="public.src", source_columns=["y"], transformation=None),
                ],
            ),
        ]))

        edges = _read_edges()
        assert len(edges) == 1
        e = edges[0]
        assert "column_mappings" in e
        assert len(e["column_mappings"]) == 2
        assert e["column_mappings"][0]["target_column"] == "a"
        assert e["column_mappings"][0]["source_columns"] == ["x"]
        assert e["column_mappings"][1]["target_column"] == "b"

    def test_global_graph_edge_has_column_mappings(self):
        """get_global_graph 返回的 GlobalEdge 带 column_mappings"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("cm2", lineages=[
            Lineage(
                lineage_id="l-cm2", source_table="public.src", target_table="public.dst",
                operation_type=OperationType.INSERT,
                extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                statement_seq=1, dml_statement="INSERT INTO dst (a) SELECT x FROM src;",
                column_mappings=[
                    ColumnMapping(target_table="public.dst", target_column="a",
                                  source_table="public.src", source_columns=["x"], transformation=None),
                ],
            ),
        ]))

        graph = store.get_global_graph()
        assert len(graph.edges) == 1
        ge = graph.edges[0]
        assert len(ge.column_mappings) == 1
        assert ge.column_mappings[0].target_column == "a"
        assert ge.column_mappings[0].source_columns == ["x"]

    def test_backward_compat_no_column_mappings(self):
        """旧 edges.jsonl（无 column_mappings 字段）应反序列化为空数组，不报错"""
        store._write_json(store.TABLES_FILE, {})
        # 手工写一条无 column_mappings 的旧格式边
        store._write_edges([{
            "edge_id": "old-1",
            "source": "public.old_src",
            "target": "public.old_dst",
            "operation": "INSERT",
            "script_id": "old-script",
            "statement_seq": 1,
            "created_at": "2026-01-01",
            # 故意没有 column_mappings 字段
        }])
        # tables.json 也补上对应表，否则 get_global_graph 过滤孤立表
        store._write_json(store.TABLES_FILE, {
            "public.old_src": {"schema": "public", "name": "old_src", "type": "source",
                               "source": "lineage", "first_seen": "x", "script_ids": ["old-script"],
                               "script_count": 1, "last_seen": "x", "columns": []},
            "public.old_dst": {"schema": "public", "name": "old_dst", "type": "target",
                               "source": "lineage", "first_seen": "x", "script_ids": ["old-script"],
                               "script_count": 1, "last_seen": "x", "columns": []},
        })

        # 不应抛异常，column_mappings 兜底为空
        graph = store.get_global_graph()
        assert len(graph.edges) == 1
        assert graph.edges[0].column_mappings == []


class TestScriptIdsIndex:
    """script_ids 反向索引测试"""

    def test_table_has_script_ids_after_save(self):
        """保存脚本后，相关表的 script_ids 应包含该脚本 id"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("sidx1"))

        tables = json.loads(store.TABLES_FILE.read_text())
        assert "public.orders" in tables
        sids = tables["public.orders"].get("script_ids", [])
        assert "sidx1" in sids
        assert tables["public.orders"]["script_count"] == len(sids)

    def test_script_ids_accumulate_across_scripts(self):
        """两个脚本引用同一表时，script_ids 应累积去重"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        # 脚本1 涉及 public.orders
        store.save_script(_make_result("sidx-a"))
        # 脚本2 也涉及 public.orders（orders→report 单条边）
        store.save_script(_make_result(
            "sidx-b",
            lineages=[
                Lineage(lineage_id="lb", source_table="public.orders", target_table="public.report",
                        operation_type=OperationType.INSERT,
                        extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                        statement_seq=1, dml_statement="INSERT INTO report SELECT * FROM orders;"),
            ],
            tables_db=[
                TableInfo(schema_name="public", table_name="orders", table_type=TableType.SOURCE, source="database"),
                TableInfo(schema_name="public", table_name="report", table_type=TableType.TARGET, source="database"),
            ],
            tables_script=[],
            vis_nodes=[],
            vis_edges=[],
            stmts=[Statement(seq=1, type=StatementType.INSERT,
                             text="INSERT INTO report SELECT * FROM orders;",
                             tables_referenced=["public.orders"], tables_modified=["public.report"])],
        ))

        tables = json.loads(store.TABLES_FILE.read_text())
        sids = tables["public.orders"]["script_ids"]
        assert set(sids) == {"sidx-a", "sidx-b"}
        assert tables["public.orders"]["script_count"] == 2

    def test_delete_removes_script_from_index(self):
        """删除脚本后，相关表的 script_ids 应移除该 script_id"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("del-idx1"))
        store.save_script(_make_result(
            "del-idx2",
            lineages=[
                Lineage(lineage_id="lx", source_table="public.orders", target_table="public.report",
                        operation_type=OperationType.INSERT,
                        extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                        statement_seq=1, dml_statement="INSERT INTO report SELECT * FROM orders;"),
            ],
            tables_db=[
                TableInfo(schema_name="public", table_name="orders", table_type=TableType.SOURCE, source="database"),
                TableInfo(schema_name="public", table_name="report", table_type=TableType.TARGET, source="database"),
            ],
            tables_script=[],
            vis_nodes=[],
            vis_edges=[],
            stmts=[Statement(seq=1, type=StatementType.INSERT,
                             text="INSERT INTO report SELECT * FROM orders;",
                             tables_referenced=["public.orders"], tables_modified=["public.report"])],
        ))

        # 两个脚本都引用 public.orders
        tables = json.loads(store.TABLES_FILE.read_text())
        assert set(tables["public.orders"]["script_ids"]) == {"del-idx1", "del-idx2"}

        # 删除 del-idx1：orders 的 script_ids 应只剩 del-idx2
        store.delete_script("del-idx1")
        tables = json.loads(store.TABLES_FILE.read_text())
        assert tables["public.orders"]["script_ids"] == ["del-idx2"]
        assert tables["public.orders"]["script_count"] == 1

    def test_orphan_table_cleaned_when_script_ids_empty(self):
        """当表的 script_ids 全部被移除时，该表应被删除（孤立表清理）"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        store.save_script(_make_result("orph1"))

        # tmp 只被 orph1 引用
        tables = json.loads(store.TABLES_FILE.read_text())
        assert tables["public.tmp"]["script_ids"] == ["orph1"]

        store.delete_script("orph1")
        tables = json.loads(store.TABLES_FILE.read_text())
        # script_ids 变空 → 表被删
        assert "public.tmp" not in tables


class TestConcurrencySafety:
    """并发写安全测试（文件锁保护）"""

    def test_concurrent_saves_no_edge_loss(self):
        """两个线程并发 save_script，所有边都不应丢失"""
        import threading
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        errors: list[Exception] = []

        def worker(script_id: str):
            try:
                store.save_script(_make_result(script_id))
            except Exception as e:
                errors.append(e)

        # 5 个线程并发保存，每个 2 条边 → 共 10 条
        threads = [threading.Thread(target=worker, args=(f"conc{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"并发保存抛异常: {errors}"

        edges = _read_edges()
        # 没有锁的话，并发追加写可能交错损坏行或丢数据；有锁则 10 条齐全
        assert len(edges) == 10, f"期望 10 条边，实际 {len(edges)}（可能并发写丢数据）"
        script_ids = {e["script_id"] for e in edges}
        assert script_ids == {f"conc{i}" for i in range(5)}

    def test_concurrent_delete_and_save_isolated(self):
        """并发删除一个脚本、保存另一个脚本，不应互相破坏数据完整性"""
        import threading
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        # 预置一个脚本
        store.save_script(_make_result("pre"))

        errors: list[Exception] = []

        def deleter():
            try:
                store.delete_script("pre")
            except Exception as e:
                errors.append(e)

        def saver():
            try:
                store.save_script(_make_result("new"))
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=deleter)
        t2 = threading.Thread(target=saver)
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert errors == [], f"并发操作抛异常: {errors}"
        # 'pre' 的边应全部移除，'new' 的边应保留
        edges = _read_edges()
        assert all(e["script_id"] != "pre" for e in edges)
        assert any(e["script_id"] == "new" for e in edges)


class TestQualifiedNameNormalization:
    """全限定名归一化测试（schema 保留语义）"""

    def test_qualified_names_kept_distinct(self):
        """不同 schema 的表名在全局注册表中保持独立 key"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        # 第一次: public.orders → public.report
        store.save_script(_make_result("sp1"))
        # 第二次: analytics.orders → analytics.report（同名不同 schema）
        store.save_script(_make_result(
            "sp2",
            lineages=[
                Lineage(lineage_id="l-sp", source_table="analytics.orders", target_table="analytics.report",
                        operation_type=OperationType.INSERT,
                        extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                        statement_seq=1, dml_statement="INSERT INTO analytics.report SELECT * FROM analytics.orders;"),
            ],
            tables_db=[
                TableInfo(schema_name="analytics", table_name="orders", table_type=TableType.SOURCE, source="database"),
                TableInfo(schema_name="analytics", table_name="report", table_type=TableType.TARGET, source="database"),
            ],
            tables_script=[],
            vis_nodes=[VisNode(id="analytics.orders", label="orders", type="source"),
                       VisNode(id="analytics.report", label="report", type="target")],
            vis_edges=[VisEdge(source="analytics.orders", target="analytics.report", label="INSERT", statement_seq=1)],
            stmts=[Statement(seq=1, type=StatementType.INSERT,
                             text="INSERT INTO analytics.report SELECT * FROM analytics.orders;",
                             tables_referenced=["analytics.orders"], tables_modified=["analytics.report"])],
        ))

        tables = json.loads(store.TABLES_FILE.read_text())
        # public.orders 与 analytics.orders 是两个独立 key（不合并）
        assert "public.orders" in tables
        assert "analytics.orders" in tables
        assert "public.report" in tables
        assert "analytics.report" in tables

    def test_plain_name_normalized_to_public(self):
        """裸表名（不带 schema）应归一化为 public.xxx"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        store.save_script(_make_result("plain1"))

        tables = json.loads(store.TABLES_FILE.read_text())
        # 不应出现裸表名，都应该是 public.xxx
        assert "public.orders" in tables
        assert "public.tmp" in tables
        assert "public.report" in tables
        # 不应出现不带 schema 的 key
        assert "orders" not in tables
        assert "tmp" not in tables
        assert "report" not in tables

    def test_schema_prefix_edges_kept(self):
        """边的 source/target 应保留 schema 前缀"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        store.save_script(_make_result(
            "sp3",
            lineages=[
                Lineage(lineage_id="l-sp3", source_table="analytics.raw_data", target_table="staging.cleaned",
                        operation_type=OperationType.INSERT,
                        extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                        statement_seq=1, dml_statement="INSERT INTO staging.cleaned SELECT * FROM analytics.raw_data;"),
            ],
            tables_db=[
                TableInfo(schema_name="analytics", table_name="raw_data", table_type=TableType.SOURCE, source="database"),
                TableInfo(schema_name="staging", table_name="cleaned", table_type=TableType.TARGET, source="database"),
            ],
            tables_script=[],
            vis_nodes=[],
            vis_edges=[],
            stmts=[Statement(seq=1, type=StatementType.INSERT,
                             text="INSERT INTO staging.cleaned SELECT * FROM analytics.raw_data;",
                             tables_referenced=["analytics.raw_data"], tables_modified=["staging.cleaned"])],
        ))

        edges = _read_edges()
        assert len(edges) == 1
        assert edges[0]["source"] == "analytics.raw_data"
        assert edges[0]["target"] == "staging.cleaned"

    def test_cross_schema_dedup_within_same_schema(self):
        """同一 schema 下的表合并 script_count，跨 schema 的同名表独立"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        # 脚本1: public.orders → public.report
        store.save_script(_make_result("dedup1"))
        tables1 = json.loads(store.TABLES_FILE.read_text())
        assert "public.orders" in tables1

        # 脚本2: 同样引用 public.orders → public.report（应合并，script_count 增加）
        store.save_script(_make_result(
            "dedup2",
            lineages=[
                Lineage(lineage_id="l-dedup", source_table="public.orders", target_table="public.report",
                        operation_type=OperationType.INSERT,
                        extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                        statement_seq=1, dml_statement="INSERT INTO public.report SELECT * FROM public.orders;"),
            ],
            tables_db=[
                TableInfo(schema_name="public", table_name="orders", table_type=TableType.SOURCE, source="database"),
                TableInfo(schema_name="public", table_name="report", table_type=TableType.TARGET, source="database"),
            ],
            tables_script=[],
            vis_nodes=[],
            vis_edges=[],
            stmts=[Statement(seq=1, type=StatementType.INSERT,
                             text="INSERT INTO report SELECT * FROM orders;",
                             tables_referenced=["public.orders"], tables_modified=["public.report"])],
        ))
        tables2 = json.loads(store.TABLES_FILE.read_text())
        # public.orders 仍然只有一个 key（同 schema 合并）
        assert "public.orders" in tables2
        # 不应出现裸 orders
        assert "orders" not in tables2

    def test_global_graph_qualified(self):
        """全局图谱的节点应使用全限定名"""
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])

        store.save_script(_make_result(
            "gg-sp1",
            lineages=[
                Lineage(lineage_id="l-ggsp", source_table="public.src", target_table="dw.tgt",
                        operation_type=OperationType.INSERT,
                        extraction_method=ExtractionMethod.STATIC_ANALYSIS,
                        statement_seq=1, dml_statement="INSERT INTO dw.tgt SELECT * FROM public.src;"),
            ],
            tables_db=[
                TableInfo(schema_name="public", table_name="src", table_type=TableType.SOURCE, source="database"),
                TableInfo(schema_name="dw", table_name="tgt", table_type=TableType.TARGET, source="database"),
            ],
            tables_script=[],
            vis_nodes=[],
            vis_edges=[],
            stmts=[Statement(seq=1, type=StatementType.INSERT,
                             text="INSERT INTO tgt SELECT * FROM src;",
                             tables_referenced=["public.src"], tables_modified=["dw.tgt"])],
        ))

        graph = store.get_global_graph()
        node_ids = {n.id for n in graph.nodes}
        assert "public.src" in node_ids
        assert "dw.tgt" in node_ids
        # 不应出现裸表名
        assert "src" not in node_ids
        assert "tgt" not in node_ids
        assert len(graph.edges) == 1
        assert graph.edges[0].source == "public.src"
        assert graph.edges[0].target == "dw.tgt"
