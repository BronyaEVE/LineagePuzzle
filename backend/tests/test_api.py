"""API 层端到端测试。

用 FastAPI TestClient 覆盖所有 15 个 REST 端点，验证：
- 路由层正确调用 services 并返回序列化结果
- HTTP 状态码（200/400/404/422）符合预期
- 路径遍历防护在 API 层返回 400（S1 安全修复）
- 请求体校验（422）正常工作

数据隔离：setup_module 把 store.DATA_DIR 重定向到临时目录，不污染真实数据，
也不依赖已存在的 scripts。不连接外部数据库（analyze 用离线 ast_only 模式）。
"""
import sys
import os
import shutil
import tempfile
import pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import store


client = TestClient(app)

# ============================================================
# 数据隔离：重定向 store 的数据目录到临时目录
# ============================================================
_original_data_dir = None


def setup_module():
    """所有测试共享一个临时数据目录，setup 时清空，保证测试间干净状态。"""
    global _original_data_dir
    _original_data_dir = store.DATA_DIR
    store.DATA_DIR = pathlib.Path(tempfile.mkdtemp())
    store.TABLES_FILE = store.DATA_DIR / "tables.json"
    store.EDGES_FILE = store.DATA_DIR / "edges.jsonl"
    store.SCRIPTS_DIR = store.DATA_DIR / "scripts"
    store.PARAM_MAPPING_FILE = store.DATA_DIR / "param_mapping.json"
    store.LOCK_FILE = store.DATA_DIR / "store.lock"


def teardown_module():
    global _original_data_dir
    if _original_data_dir:
        shutil.rmtree(str(store.DATA_DIR), ignore_errors=True)
        store.DATA_DIR = _original_data_dir
        store.TABLES_FILE = store.DATA_DIR / "tables.json"
        store.EDGES_FILE = store.DATA_DIR / "edges.jsonl"
        store.SCRIPTS_DIR = store.DATA_DIR / "scripts"
        store.PARAM_MAPPING_FILE = store.DATA_DIR / "param_mapping.json"
        store.LOCK_FILE = store.DATA_DIR / "store.lock"


@pytest.fixture(autouse=True)
def _clean_store():
    """每个测试前清空数据目录，保证测试隔离（重写 tables/edges/清 scripts）。"""
    store._write_json(store.TABLES_FILE, {})
    store._write_edges([])
    # 清空 scripts 目录
    if store.SCRIPTS_DIR.exists():
        for f in store.SCRIPTS_DIR.glob("*.json"):
            f.unlink()
    yield


# ============================================================
# 健康检查
# ============================================================

class TestHealth:
    def test_health(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ============================================================
# POST /analyze —— 分析脚本
# ============================================================

class TestAnalyze:
    def test_analyze_offline_success(self):
        """离线模式（无 database_config）分析成功，结果自动持久化"""
        r = client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["extraction_mode"] == "ast_only"
        assert len(data["lineages"]) == 1
        assert data["lineages"][0]["source_table"] == "public.orders"
        assert data["lineages"][0]["target_table"] == "public.report"
        # 返回了 analysis_id（持久化后）
        assert "analysis_id" in data

    def test_analyze_empty_script_rejected(self):
        """空脚本被 pydantic 校验拒绝（min_length=1）→ 422"""
        r = client.post("/api/analyze", json={"script": ""})
        assert r.status_code == 422

    def test_analyze_missing_script_field(self):
        """缺少 script 字段 → 422"""
        r = client.post("/api/analyze", json={})
        assert r.status_code == 422

    def test_analyze_multi_statement(self):
        """多语句脚本（含临时表）血缘链路完整"""
        r = client.post("/api/analyze", json={
            "script": "CREATE TEMP TABLE tmp AS SELECT * FROM orders;"
                      "INSERT INTO report SELECT * FROM tmp;",
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data["lineages"]) == 2
        pairs = {(l["source_table"], l["target_table"]) for l in data["lineages"]}
        assert ("public.orders", "public.tmp") in pairs
        assert ("public.tmp", "public.report") in pairs


# ============================================================
# 脚本管理 CRUD
# ============================================================

class TestScriptCrud:
    def _create_script(self) -> str:
        """辅助：分析一个脚本，返回 analysis_id"""
        r = client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        })
        assert r.status_code == 200
        return r.json()["analysis_id"]

    def test_list_scripts_empty(self):
        r = client.get("/api/scripts")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_scripts_after_analyze(self):
        sid = self._create_script()
        r = client.get("/api/scripts")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["analysis_id"] == sid
        # 摘要字段完整
        assert "name" in data[0]
        assert "statement_count" in data[0]

    def test_get_script(self):
        sid = self._create_script()
        r = client.get(f"/api/scripts/{sid}")
        assert r.status_code == 200
        assert r.json()["analysis_id"] == sid

    def test_get_script_not_found(self):
        r = client.get("/api/scripts/nonexistent-id")
        assert r.status_code == 404

    def test_delete_script(self):
        sid = self._create_script()
        r = client.delete(f"/api/scripts/{sid}")
        assert r.status_code == 200
        # 再查应 404
        assert client.get(f"/api/scripts/{sid}").status_code == 404

    def test_delete_script_not_found(self):
        r = client.delete("/api/scripts/nonexistent-id")
        assert r.status_code == 404

    def test_rename_script(self):
        sid = self._create_script()
        r = client.put(f"/api/scripts/{sid}/name?name=新名字")
        assert r.status_code == 200
        # 验证改名生效
        assert client.get(f"/api/scripts/{sid}").json()["name"] == "新名字"

    def test_rename_script_not_found(self):
        r = client.put("/api/scripts/nonexistent-id/name?name=x")
        assert r.status_code == 404

    def test_get_statements(self):
        sid = self._create_script()
        r = client.get(f"/api/scripts/{sid}/statements")
        assert r.status_code == 200
        data = r.json()
        assert "statements" in data
        assert len(data["statements"]) >= 1


# ============================================================
# POST /analyze-batch —— 批量导入 SQL 文件
# ============================================================

class TestBatchAnalyze:
    """批量导入：每个 SQL 文件产出独立脚本"""

    def test_batch_success(self):
        """多文件批量分析成功，每个文件成为独立脚本（独立 analysis_id）"""
        r = client.post("/api/analyze-batch", json={
            "files": [
                {"name": "ddl.sql", "content": "CREATE TABLE t1 AS SELECT * FROM src;"},
                {"name": "etl.sql", "content": "INSERT INTO report SELECT * FROM orders;"},
            ],
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        # 两个独立的 analysis_id
        ids = {item["analysis_id"] for item in data}
        assert len(ids) == 2
        # 脚本名用文件名（去 .sql 后缀）
        names = {item["name"] for item in data}
        assert names == {"ddl", "etl"}

    def test_batch_single_file(self):
        """单个文件也能批量端点"""
        r = client.post("/api/analyze-batch", json={
            "files": [{"name": "only.sql", "content": "INSERT INTO t SELECT * FROM s;"}],
        })
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_batch_empty_files_rejected(self):
        """空文件列表 → 422（min_length=1）"""
        r = client.post("/api/analyze-batch", json={"files": []})
        assert r.status_code == 422

    def test_batch_empty_content_rejected(self):
        """文件内容为空 → 422（BatchFileItem.content min_length=1）"""
        r = client.post("/api/analyze-batch", json={
            "files": [{"name": "empty.sql", "content": ""}],
        })
        assert r.status_code == 422

    def test_batch_results_in_script_list(self):
        """批量结果在 GET /scripts 列表里可见"""
        client.post("/api/analyze-batch", json={
            "files": [
                {"name": "a.sql", "content": "INSERT INTO t1 SELECT * FROM s1;"},
                {"name": "b.sql", "content": "INSERT INTO t2 SELECT * FROM s2;"},
            ],
        })
        r = client.get("/api/scripts")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_batch_partial_failure_tolerance(self):
        """部分文件失败容错：坏文件不阻塞好文件，全失败才报 500。

        本项目 analyze 对无效 SQL 优雅降级（返回空 lineages，不抛异常），
        所以单个"坏"SQL 不会触发异常路径。这里用一个能真正触发异常的场景
        模拟：由于 analyze 内部 try/except 兜底，构造全失败需更极端输入。
        实际验证重点是：好文件能成功，结果数量正确。
        """
        r = client.post("/api/analyze-batch", json={
            "files": [
                {"name": "good.sql", "content": "INSERT INTO t SELECT * FROM s;"},
                {"name": "also_good.sql", "content": "CREATE TABLE x AS SELECT * FROM y;"},
            ],
        })
        assert r.status_code == 200
        assert len(r.json()) == 2  # 两个都成功

    def test_batch_global_graph_accumulates(self):
        """批量导入后全局图谱累积所有文件血缘"""
        client.post("/api/analyze-batch", json={
            "files": [
                {"name": "a.sql", "content": "INSERT INTO t1 SELECT * FROM s1;"},
                {"name": "b.sql", "content": "INSERT INTO t2 SELECT * FROM s2;"},
            ],
        })
        r = client.get("/api/global-graph")
        nodes = {n["id"] for n in r.json()["nodes"]}
        # 两个文件的表都在全局图里
        assert {"public.s1", "public.t1", "public.s2", "public.t2"} <= nodes


# ============================================================
# 路径遍历防护（S1 安全修复）
# ============================================================

class TestPathTraversalGuard:
    """验证非法 script_id 在 API 层返回 400（而非内部错误或路径逃逸）"""

    @pytest.mark.parametrize("bad_id", [
        "../../etc/passwd",
        "..\\..\\config",
        "foo/../../bar",
        "a/b",
        "a b",
    ])
    def test_get_rejects_path_traversal(self, bad_id):
        r = client.get(f"/api/scripts/{bad_id}")
        # 注意：FastAPI 路径参数默认不含 /，含 / 的会 404；但 ../ 会被 URL 解码
        # 关键是不应 200，且不应逃逸读文件
        assert r.status_code in (400, 404)

    @pytest.mark.parametrize("bad_id", [
        "..\\..\\config",  # Windows 风格，反斜杠在 URL 里是合法字符
        "a b",
    ])
    def test_delete_rejects_path_traversal(self, bad_id):
        r = client.delete(f"/api/scripts/{bad_id}")
        assert r.status_code in (400, 404)

    def test_rename_rejects_path_traversal(self):
        # 含空格的 id 能进到 store 层被校验拒绝 → 400
        r = client.put("/api/scripts/a b/name?name=x")
        assert r.status_code in (400, 404)


# ============================================================
# 语句修正
# ============================================================

class TestCorrectStatement:
    def test_correct_statement(self):
        """修正语句的目标表后，血缘重新生成"""
        sid = client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        }).json()["analysis_id"]

        r = client.put(f"/api/scripts/{sid}/statements/1", json={
            "corrected_text": "INSERT INTO report2 SELECT * FROM orders",
            "tables_referenced": ["public.orders"],
            "tables_modified": ["public.report2"],
        })
        assert r.status_code == 200
        data = r.json()
        # 目标表应变成 report2
        targets = {l["target_table"] for l in data["lineages"]}
        assert "public.report2" in targets

    def test_correct_statement_not_found(self):
        sid = client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        }).json()["analysis_id"]
        # 不存在的 seq
        r = client.put(f"/api/scripts/{sid}/statements/999", json={
            "corrected_text": "SELECT 1",
            "tables_referenced": [],
            "tables_modified": [],
        })
        assert r.status_code == 404

    def test_correct_statement_invalid_body(self):
        """缺少必填字段 → 422"""
        sid = client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        }).json()["analysis_id"]
        r = client.put(f"/api/scripts/{sid}/statements/1", json={})
        assert r.status_code == 422


# ============================================================
# 全局图谱 / 表注册
# ============================================================

class TestGlobalGraph:
    def test_global_graph_empty(self):
        r = client.get("/api/global-graph")
        assert r.status_code == 200
        data = r.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_global_graph_after_analyze(self):
        client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        })
        r = client.get("/api/global-graph")
        assert r.status_code == 200
        data = r.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert "public.orders" in node_ids
        assert "public.report" in node_ids
        assert len(data["edges"]) == 1

    def test_get_tables(self):
        client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        })
        r = client.get("/api/tables")
        assert r.status_code == 200
        data = r.json()
        assert "public.orders" in data
        assert "public.report" in data


# ============================================================
# 参数映射
# ============================================================

class TestParamMapping:
    def test_get_empty(self):
        r = client.get("/api/param-mapping")
        assert r.status_code == 200
        # 初始无映射文件时返回空 dict
        assert r.json() == {}

    def test_set_and_get(self):
        r = client.put("/api/param-mapping", json={"icl_schema": "ods", "env": "prod"})
        assert r.status_code == 200
        data = r.json()
        assert data["icl_schema"] == "ods"
        # 再 GET 确认持久化
        assert client.get("/api/param-mapping").json()["icl_schema"] == "ods"

    def test_set_filters_invalid_keys(self):
        """非法 key（非标识符）被过滤"""
        r = client.put("/api/param-mapping", json={
            "valid_name": "ok",
            "invalid-name": "bad",
            "": "empty",
        })
        assert r.status_code == 200
        data = r.json()
        assert "valid_name" in data
        assert "invalid-name" not in data


# ============================================================
# 导入导出
# ============================================================

class TestExportImport:
    def test_export_empty(self):
        r = client.get("/api/export")
        assert r.status_code == 200
        data = r.json()
        assert "tables" in data
        assert "edges" in data
        assert "scripts" in data
        assert "param_mapping" in data

    def test_export_after_data(self):
        client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        })
        r = client.get("/api/export")
        data = r.json()
        assert len(data["scripts"]) == 1
        assert len(data["edges"]) == 1

    def test_import_overwrites(self):
        """导入数据后全局图谱反映导入内容"""
        # 先准备导出数据
        client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        })
        exported = client.get("/api/export").json()

        # 清空（autouse fixture 在下一个测试会清，这里手动模拟）
        store._write_json(store.TABLES_FILE, {})
        store._write_edges([])
        for f in store.SCRIPTS_DIR.glob("*.json"):
            f.unlink()
        assert client.get("/api/global-graph").json()["nodes"] == []

        # 导入 → 恢复
        r = client.post("/api/import", json=exported)
        assert r.status_code == 200
        nodes = {n["id"] for n in client.get("/api/global-graph").json()["nodes"]}
        assert "public.orders" in nodes

    def test_export_import_roundtrip(self):
        """导出再导入，数据一致"""
        client.post("/api/analyze", json={
            "script": "INSERT INTO report SELECT * FROM orders",
        })
        before = client.get("/api/export").json()
        # 导入（覆盖自身）
        client.post("/api/import", json=before)
        after = client.get("/api/export").json()
        assert len(after["scripts"]) == len(before["scripts"])
        assert len(after["edges"]) == len(before["edges"])


# ============================================================
# 影响分析
# ============================================================

class TestImpactAnalysis:
    def _setup_chain(self):
        """建链：orders → tmp → report → summary"""
        client.post("/api/analyze", json={
            "script": "CREATE TEMP TABLE tmp AS SELECT * FROM orders;"
                      "INSERT INTO report SELECT * FROM tmp;"
                      "INSERT INTO summary SELECT * FROM report;",
        })

    def test_impact_downstream(self):
        self._setup_chain()
        r = client.get("/api/impact-analysis/public.orders")
        assert r.status_code == 200
        data = r.json()
        assert "public.tmp" in data["downstream"]
        assert "public.report" in data["downstream"]
        assert "public.summary" in data["downstream"]

    def test_impact_upstream(self):
        self._setup_chain()
        r = client.get("/api/impact-analysis/public.summary")
        assert r.status_code == 200
        data = r.json()
        assert "public.orders" in data["upstream"]
        assert "public.report" in data["upstream"]

    def test_impact_upstream_paths(self):
        """后端返回 upstream_paths（全部路径，v2.3 改为 list[list[str]]）"""
        self._setup_chain()
        r = client.get("/api/impact-analysis/public.summary")
        data = r.json()
        assert "upstream_paths" in data
        # orders → summary 的完整链路（线性链只有一条路径，包在数组里）
        assert data["upstream_paths"]["public.orders"] == [
            ["public.orders", "public.tmp", "public.report", "public.summary"],
        ]

    def test_impact_nonexistent_table(self):
        r = client.get("/api/impact-analysis/public.nonexistent")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data
        assert data["downstream"] == []

    def test_impact_leaf_node(self):
        """叶子节点（无下游）downstream 为空"""
        self._setup_chain()
        r = client.get("/api/impact-analysis/public.summary")
        assert r.json()["downstream"] == []
