"""JSON 文件持久化存储层。

三层存储结构：
  - 全局表注册表 (tables.json)
  - 全局血缘边 (edges.json)
  - 单个脚本 (scripts/{id}.json)
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from ..models.analysis import AnalysisResult, GlobalEdge, GlobalGraph, ScriptSummary, VisNode
from .normalize import normalize_table_name

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
TABLES_FILE = DATA_DIR / "tables.json"
EDGES_FILE = DATA_DIR / "edges.json"
SCRIPTS_DIR = DATA_DIR / "scripts"


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data):
    _ensure_dirs()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# ============================================================
# 脚本管理
# ============================================================

def save_script(result: AnalysisResult) -> AnalysisResult:
    """保存脚本分析结果，同时更新全局表注册表和边。"""
    _ensure_dirs()

    # 自动命名
    if not result.name:
        result.name = f"脚本_{result.created_at.strftime('%m%d_%H%M')}"

    # 保存单个脚本文件
    script_path = SCRIPTS_DIR / f"{result.analysis_id}.json"
    _write_json(script_path, result.model_dump())

    # 更新全局表
    _merge_tables(result)

    # 更新全局边
    _merge_edges(result)

    return result


def list_scripts() -> list[ScriptSummary]:
    """返回所有脚本的摘要列表，按创建时间倒序。"""
    _ensure_dirs()
    summaries = []
    for f in sorted(SCRIPTS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = _read_json(f)
            sg = data.get("statement_group") or {}
            stmts = sg.get("statements") or []
            vis = data.get("visualization") or {}
            tables_in_script = set()
            for s in stmts:
                tables_in_script.update(normalize_table_name(t) for t in s.get("tables_referenced", []))
                tables_in_script.update(normalize_table_name(t) for t in s.get("tables_created", []))
                tables_in_script.update(normalize_table_name(t) for t in s.get("tables_modified", []))
            summaries.append(ScriptSummary(
                analysis_id=data["analysis_id"],
                name=data.get("name", ""),
                created_at=data.get("created_at", ""),
                statement_count=len(stmts),
                table_count=len(tables_in_script),
            ))
        except Exception:
            continue
    return summaries


def get_script(script_id: str) -> AnalysisResult | None:
    """读取单个脚本的完整分析结果。"""
    path = SCRIPTS_DIR / f"{script_id}.json"
    if not path.exists():
        return None
    data = _read_json(path)
    return AnalysisResult(**data)


def delete_script(script_id: str) -> bool:
    """删除脚本及其关联的全局边，清理孤立表。"""
    path = SCRIPTS_DIR / f"{script_id}.json"
    if not path.exists():
        return False

    # 删除脚本文件
    path.unlink()

    # 删除关联的全局边
    _remove_edges_for_script(script_id)

    # 清理孤立表
    _cleanup_orphan_tables()

    return True


def update_script_name(script_id: str, name: str) -> AnalysisResult | None:
    """重命名脚本。"""
    result = get_script(script_id)
    if not result:
        return None
    result.name = name
    result.updated_at = datetime.now()
    script_path = SCRIPTS_DIR / f"{script_id}.json"
    _write_json(script_path, result.model_dump())
    return result


# ============================================================
# 全局图谱
# ============================================================

def get_global_graph() -> GlobalGraph:
    """返回累积的全局血缘图谱。"""
    tables = _read_json(TABLES_FILE, {})
    edges = _read_json(EDGES_FILE, [])

    # 根据边判断节点角色
    sources = {e["source"] for e in edges}
    targets = {e["target"] for e in edges}

    nodes = []
    for name, info in tables.items():
        is_src = name in sources
        is_tgt = name in targets
        if is_src and is_tgt:
            ntype = "intermediate"
        elif is_src:
            ntype = "source"
        elif is_tgt:
            ntype = "target"
        else:
            ntype = info.get("type", "source")
        nodes.append(VisNode(id=name, label=name, type=ntype))

    ge = [GlobalEdge(**e) for e in edges]
    return GlobalGraph(nodes=nodes, edges=ge)


def get_tables() -> dict:
    """返回全局表注册表。"""
    return _read_json(TABLES_FILE, {})


# ============================================================
# 内部方法
# ============================================================

def _merge_tables(result: AnalysisResult):
    """合并脚本的表信息到全局注册表。"""
    tables = _read_json(TABLES_FILE, {})
    now = datetime.now().isoformat()

    all_table_infos = list(result.database_info.tables_from_db) + list(result.database_info.tables_from_script)
    for ti in all_table_infos:
        name = normalize_table_name(ti.table_name)
        if name in tables:
            tables[name]["script_count"] = tables[name].get("script_count", 0) + 1
            tables[name]["last_seen"] = now
            # 合并列信息（如果之前为空）
            if not tables[name].get("columns") and ti.columns:
                tables[name]["columns"] = [{"name": c.name, "type": c.type} for c in ti.columns]
        else:
            tables[name] = {
                "schema": ti.schema_name,
                "name": name,
                "type": ti.table_type.value if hasattr(ti.table_type, "value") else str(ti.table_type),
                "columns": [{"name": c.name, "type": c.type} for c in ti.columns],
                "source": ti.source,
                "first_seen": now,
                "script_count": 1,
                "last_seen": now,
            }

    # 也从 lineages 中收集表（确保不遗漏）
    for lin in result.lineages:
        for tname in [lin.source_table, lin.target_table]:
            tname = normalize_table_name(tname)
            if tname and tname not in tables:
                tables[tname] = {
                    "schema": "public",
                    "name": tname,
                    "type": "source",  # 会被全局图逻辑重新判定
                    "columns": [],
                    "source": "lineage",
                    "first_seen": now,
                    "script_count": 1,
                    "last_seen": now,
                }

    _write_json(TABLES_FILE, tables)


def _merge_edges(result: AnalysisResult):
    """添加脚本的血缘边到全局边列表。"""
    edges = _read_json(EDGES_FILE, [])
    now = datetime.now().isoformat()

    for lin in result.lineages:
        if not lin.source_table:
            continue
        edges.append({
            "edge_id": str(uuid.uuid4()),
            "source": normalize_table_name(lin.source_table),
            "target": normalize_table_name(lin.target_table),
            "operation": lin.operation_type.value if hasattr(lin.operation_type, "value") else str(lin.operation_type),
            "script_id": result.analysis_id,
            "statement_seq": lin.statement_seq,
            "created_at": now,
        })

    _write_json(EDGES_FILE, edges)


def _remove_edges_for_script(script_id: str):
    """删除指定脚本关联的所有全局边。"""
    edges = _read_json(EDGES_FILE, [])
    edges = [e for e in edges if e.get("script_id") != script_id]
    _write_json(EDGES_FILE, edges)


def _cleanup_orphan_tables():
    """清理不再被任何边引用的孤立表。"""
    tables = _read_json(TABLES_FILE, {})
    edges = _read_json(EDGES_FILE, [])

    referenced = set()
    for e in edges:
        referenced.add(e.get("source"))
        referenced.add(e.get("target"))

    orphans = [name for name in tables if name not in referenced]
    for name in orphans:
        del tables[name]

    if orphans:
        _write_json(TABLES_FILE, tables)
