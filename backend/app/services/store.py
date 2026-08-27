"""JSON 文件持久化存储层（带文件锁）。

三层存储结构：
  - 全局表注册表 (tables.json)：每个表带 `script_ids` 反向索引
  - 全局血缘边 (edges.jsonl)：JSON Lines 格式，支持追加写
  - 单个脚本 (scripts/{id}.json)

所有写操作在 `store.lock` 文件锁保护下进行，避免并发写丢失数据。
edges 采用 JSONL 追加写，save_script 时不再全量重写；删除脚本时才重写。
孤立表清理基于 `script_ids` 反向索引，O(受影响表数) 而非 O(边数)。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import networkx as nx
from filelock import FileLock

from ..models.analysis import AnalysisResult, GlobalEdge, GlobalGraph, ScriptSummary, VisNode
from .normalize import normalize_table_name

DATA_DIR = Path(
    os.environ.get("LINEAGE_DATA_DIR")
    or (Path(__file__).resolve().parent.parent.parent / "data")
)
TABLES_FILE = DATA_DIR / "tables.json"
EDGES_FILE = DATA_DIR / "edges.jsonl"  # JSON Lines 格式
SCRIPTS_DIR = DATA_DIR / "scripts"
LOCK_FILE = DATA_DIR / "store.lock"
# 预处理规则：把「参数映射」和「自定义清洗」统一为正则替换规则。
# 旧 param_mapping.json 在首次启动时迁移到这里。
PARAM_MAPPING_FILE = DATA_DIR / "param_mapping.json"  # 保留用于迁移检测，迁移后可删
PREPROCESS_RULES_FILE = DATA_DIR / "preprocess_rules.json"
# 标签维度定义表：管理员维护，定义有哪些维度 + 每个维度下的可选标签值。
# 脚本本身只存扁平 tags 数组（如 ["C层","个人借据"]），维度归属由此表查得。
# 部署后默认空（dimensions: []），由管理员通过设置面板填充实际维度名和标签值。
TAG_SCHEMA_FILE = DATA_DIR / "tag_schema.json"

# script_id 合法字符集：字母数字、下划线、连字符（analysis_id 是 uuid4，必然匹配）。
# 用严格正则防止路径遍历（../、绝对路径、盘符等都会被拒绝）。
_SCRIPT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_script_id(script_id: str) -> None:
    """校验 script_id，防止路径遍历攻击。

    script_id 直接拼进文件路径（SCRIPTS_DIR / f'{script_id}.json'），
    若含 ../ 或路径分隔符会逃逸 SCRIPTS_DIR，导致读/删任意文件。
    合法 script_id 是 uuid4（仅含十六进制和连字符），此处用白名单正则严格限制。
    """
    if not script_id or not _SCRIPT_ID_RE.fullmatch(script_id):
        raise ValueError(f"非法 script_id: {script_id!r}")


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def _store_lock():
    """获取 store.lock 文件锁，保护写操作的原子性。

    所有对 tables.json / edges.jsonl / scripts/ 的写操作必须在此锁内。
    读操作不加锁——读时可能看到中间态，但单次 IO 是原子的，对本项目规模可接受。
    """
    _ensure_dirs()
    lock = FileLock(str(LOCK_FILE), timeout=30)
    with lock:
        yield


# ============================================================
# 基础 IO 工具
# ============================================================

def _read_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data):
    _ensure_dirs()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    # 图数据被直接改写 → 内存缓存失效（下次读懒重建）。
    # 生产写路径随后都会 _refresh_cache，这里只是兜底（含测试直接写文件）。
    global _CACHE
    if path == TABLES_FILE:
        _CACHE = None


def _read_edges() -> list[dict]:
    """读取 edges.jsonl（JSON Lines 格式），每行一个 JSON 对象。

    文件不存在或空文件返回空列表。
    """
    if not EDGES_FILE.exists():
        return []
    edges: list[dict] = []
    with open(EDGES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                edges.append(json.loads(line))
            except json.JSONDecodeError:
                # 跳过损坏行（追加写中断的半行）
                continue
    return edges


def _write_edges(edges: list[dict]):
    """全量重写 edges.jsonl（仅删除脚本时用）。"""
    global _CACHE
    _ensure_dirs()
    with open(EDGES_FILE, "w", encoding="utf-8") as f:
        for edge in edges:
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")
    # 边数据被直接改写 → 内存缓存失效（下次读懒重建）
    _CACHE = None


def _append_edge(edge: dict):
    """单条边追加到 edges.jsonl 尾部（O(1)，save_script 路径用）。"""
    _ensure_dirs()
    with open(EDGES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(edge, ensure_ascii=False) + "\n")


# ============================================================
# 全局图谱内存缓存（实体为中心：表节点 + 有向血缘边，双向邻接）
# ------------------------------------------------------------
# 设计：tables.json（表实体）+ edges.jsonl（有向血缘边，携带 script 溯源
# 与 column_mappings）是血缘的唯一真相源；启动/变更时构建内存缓存，
# 上游/下游邻接成为 O(1) 查询（下游追溯不再每次重建图）。脚本降级为
# 边的溯源来源 + 管理单元。
# 一致性：所有写操作在 _store_lock 内持久化后调用 _refresh_cache 重建；
# 读操作无锁读取缓存指针（Python 模块级赋值原子，看到的是完整的新或旧缓存）。
# ============================================================


@dataclass
class _GraphCache:
    """实体图内存缓存：边列表 + 表元数据 + networkx 有向图 + 角色集合。"""
    edges: list[dict]
    tables: dict
    graph: nx.DiGraph
    sources: set[str]
    targets: set[str]


# 模块级缓存；None 表示尚未构建（首次读懒构建 / 启动预热）。
_CACHE: _GraphCache | None = None


def _build_cache() -> _GraphCache:
    """从 tables.json + edges.jsonl 构建内存缓存。

    不加锁：调用方已持锁（写路径），或允许并发幂等构建（读懒触发）。
    """
    tables = _read_json(TABLES_FILE, {})
    edges = _read_edges()
    G = nx.DiGraph()
    sources: set[str] = set()
    targets: set[str] = set()
    for e in edges:
        src = e.get("source", "")
        tgt = e.get("target", "")
        if src and tgt:
            G.add_edge(
                src, tgt,
                operation=e.get("operation", ""),
                script_id=e.get("script_id", ""),
                statement_seq=e.get("statement_seq", 0),
            )
            sources.add(src)
            targets.add(tgt)
    return _GraphCache(edges=edges, tables=tables, graph=G, sources=sources, targets=targets)


def _get_cache() -> _GraphCache:
    """返回图缓存；未构建则在锁内懒构建（首次读触发）。"""
    global _CACHE
    if _CACHE is None:
        with _store_lock():
            if _CACHE is None:
                _CACHE = _build_cache()
    return _CACHE


def _refresh_cache() -> None:
    """写操作后重建缓存并原子替换指针。调用方必须已持有 _store_lock。"""
    global _CACHE
    _CACHE = _build_cache()


def warm_cache() -> None:
    """启动时预热图缓存（可选；首次读也会懒构建）。"""
    _get_cache()


def reset_caches() -> None:
    """清空内存缓存（图缓存 + 脚本摘要缓存）。

    供测试使用：测试把 DATA_DIR 重定向到临时目录/直接清空文件后，
    必须同时清内存缓存，否则读到旧数据。（生产代码无需调用——
    所有写路径都会 _refresh_cache。）
    """
    global _CACHE, _SCRIPT_SUMMARY_CACHE
    _CACHE = None
    _SCRIPT_SUMMARY_CACHE = {}


# ============================================================
# 脚本管理（所有写操作均在 _store_lock 保护下）
# ============================================================

def save_script(result: AnalysisResult) -> AnalysisResult:
    """保存脚本分析结果，同时更新全局表注册表和边。

    整个操作在文件锁内完成，保证 tables.json / edges.jsonl / scripts/*.json
    三处的更新是原子的（不会被其他并发写穿插）。
    """
    with _store_lock():
        # 自动命名
        if not result.name:
            result.name = f"脚本_{result.created_at.strftime('%m%d_%H%M')}"

        script_path = SCRIPTS_DIR / f"{result.analysis_id}.json"
        # 幂等保护：同 analysis_id 已存在时先清旧边/旧表引用（正常流程每次新 uuid，
        # 不会命中；防御重复保存导致 edges.jsonl 出现重复边）
        if script_path.exists():
            _remove_edges_for_script(result.analysis_id)
            _remove_script_from_tables(result.analysis_id)

        # 保存单个脚本文件
        _write_json(script_path, result.model_dump())

        # 更新全局表（带 script_ids 反向索引）
        _merge_tables(result)

        # 追加边到 edges.jsonl（O(1) 追加，不读不重写）
        _append_edges_for_script(result)

        # 实体图已变，重建内存缓存
        _refresh_cache()

    return result


# 摘要缓存：{(path, mtime): ScriptSummary}。list_scripts 每次刷新页都会被调，
# 全量解析每个脚本 JSON（含完整 SQL 文本）代价大；mtime 未变的脚本直接复用摘要。
_SCRIPT_SUMMARY_CACHE: dict[tuple[str, float], ScriptSummary] = {}


def list_scripts() -> list[ScriptSummary]:
    """返回所有脚本的摘要列表，按创建时间倒序（mtime 缓存，未变的脚本不重新解析）。"""
    global _SCRIPT_SUMMARY_CACHE
    _ensure_dirs()
    summaries = []
    valid_keys: set[tuple[str, float]] = set()
    for f in sorted(SCRIPTS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            mtime = f.stat().st_mtime
            cache_key = (str(f), mtime)
            valid_keys.add(cache_key)
            cached = _SCRIPT_SUMMARY_CACHE.get(cache_key)
            if cached is not None:
                summaries.append(cached)
                continue
            data = _read_json(f)
            sg = data.get("statement_group") or {}
            stmts = sg.get("statements") or []
            tables_in_script = set()
            for s in stmts:
                tables_in_script.update(normalize_table_name(t) for t in s.get("tables_referenced", []))
                tables_in_script.update(normalize_table_name(t) for t in s.get("tables_created", []))
                tables_in_script.update(normalize_table_name(t) for t in s.get("tables_modified", []))
            summary = ScriptSummary(
                analysis_id=data["analysis_id"],
                name=data.get("name", ""),
                created_at=data.get("created_at", ""),
                statement_count=len(stmts),
                table_count=len(tables_in_script),
                tags=data.get("tags", []),
            )
            _SCRIPT_SUMMARY_CACHE[cache_key] = summary
            summaries.append(summary)
        except Exception:
            continue
    # 清掉已删除/已变更脚本的过期缓存项（键含 mtime，旧 mtime 键不会再命中）
    if len(_SCRIPT_SUMMARY_CACHE) > len(valid_keys):
        _SCRIPT_SUMMARY_CACHE = {
            k: v for k, v in _SCRIPT_SUMMARY_CACHE.items() if k in valid_keys
        }
    return summaries


def get_script(script_id: str) -> AnalysisResult | None:
    """读取单个脚本的完整分析结果。"""
    _validate_script_id(script_id)
    path = SCRIPTS_DIR / f"{script_id}.json"
    if not path.exists():
        return None
    data = _read_json(path)
    return AnalysisResult(**data)


def delete_script(script_id: str) -> bool:
    """删除脚本及其关联的全局边，清理孤立表。

    流程（全程持锁）:
      1. 删除脚本文件
      2. 重写 edges.jsonl，移除该脚本的边
      3. 全表扫：从每个表的 script_ids 移除 script_id，script_ids 变空的表删除

    注意：步骤 3 必须全表扫（不能只看 edges 涉及的表），因为表可能从
    database_info 或无源表 lineage 登记进 tables.json 但不在 edges 里。
    """
    _validate_script_id(script_id)
    with _store_lock():
        path = SCRIPTS_DIR / f"{script_id}.json"
        if not path.exists():
            return False

        # 删除脚本文件
        path.unlink()

        # 删除关联边（重写 edges.jsonl）
        _remove_edges_for_script(script_id)

        # 全表扫清理：移除 script_id 引用，孤立表删除
        _remove_script_from_tables(script_id)

        # 实体图已变，重建内存缓存
        _refresh_cache()

    return True


def update_script_name(script_id: str, name: str) -> AnalysisResult | None:
    """重命名脚本（只改 scripts/{id}.json，不影响全局表/边）。"""
    _validate_script_id(script_id)
    with _store_lock():
        result = get_script(script_id)
        if not result:
            return None
        result.name = name
        result.updated_at = datetime.now()
        script_path = SCRIPTS_DIR / f"{script_id}.json"
        _write_json(script_path, result.model_dump())
    return result


# ============================================================
# 全局图谱（读操作，不加锁）
# ============================================================

def get_global_graph() -> GlobalGraph:
    """返回累积的全局血缘图谱（从内存缓存组装，不再每次读文件）。"""
    c = _get_cache()
    nodes = []
    for name, info in c.tables.items():
        is_src = name in c.sources
        is_tgt = name in c.targets
        if is_src and is_tgt:
            ntype = "intermediate"
        elif is_src:
            ntype = "source"
        elif is_tgt:
            ntype = "target"
        else:
            ntype = info.get("type", "source")
        nodes.append(VisNode(id=name, label=name, type=ntype))
    ge = [GlobalEdge(**e) for e in c.edges]
    return GlobalGraph(nodes=nodes, edges=ge)


def get_column_mappings() -> list[dict]:
    """聚合列级血缘映射，供「列级追溯」视图使用。

    真相源是 edges.jsonl：每条边携带 column_mappings（见 _append_edges_for_script）。
    一条语句的 column_mappings 会被挂到该语句的全部交叉积边上，因此这里按
    (script_id, statement_seq, 列映射内容) 去重，还原「每条语句一组列映射」。

    每条：{target_table, target_column, source_table, source_columns, transformation, script_id, statement_seq}
    """
    c = _get_cache()
    seen: set = set()
    mappings: list[dict] = []
    for e in c.edges:
        script_id = e.get("script_id", "")
        seq = e.get("statement_seq")
        for m in e.get("column_mappings") or []:
            if not isinstance(m, dict):
                continue
            src_cols = m.get("source_columns", [])
            key = (
                script_id, seq,
                m.get("target_table"), m.get("target_column"),
                m.get("source_table", ""),
                tuple(src_cols) if isinstance(src_cols, list) else tuple(),
                m.get("transformation"),
            )
            if key in seen:
                continue
            seen.add(key)
            mappings.append(
                {
                    "target_table": m.get("target_table"),
                    "target_column": m.get("target_column"),
                    "source_table": m.get("source_table", ""),
                    "source_columns": src_cols if isinstance(src_cols, list) else [],
                    "transformation": m.get("transformation"),
                    "script_id": script_id,
                    "statement_seq": seq,
                }
            )
    return mappings


# ============================================================
# 预处理规则（参数映射 + 自定义清洗，统一为正则替换规则）
# ============================================================

# 内置锁定规则（核心清洗，可见可开关但不可删除，防止误操作导致解析崩溃）
# 这些规则从原 preprocess 固定核心阶段提取，现在暴露给用户但锁定删除。
_DEFAULT_LOCKED_RULES = [
    {
        "id": "builtin-block-comment",
        "name": "去块注释 /* */",
        # [\s\S] 匹配任意字符（含换行），处理多行 /* ... */ 块注释；
        # 旧的 .*? 不跨行，多行注释会漏掉。
        "pattern": r"/\*[\s\S]*?\*/",
        "replacement": "",
        "enabled": True,
        "builtin": True,
        "locked": True,
    },
    {
        "id": "builtin-line-comment",
        "name": "去行注释 --",
        "pattern": r"--[^\n]*",
        "replacement": "",
        "enabled": True,
        "builtin": True,
        "locked": True,
    },
]


def _init_default_rules() -> None:
    """首次启动初始化：预置内置 locked 规则 + 迁移旧 param_mapping。

    - 若 preprocess_rules.json 不存在：写入默认 locked 规则 + 旧 param_mapping 迁移
    - 若已存在：检查是否缺少默认 locked 规则（版本升级时补齐），不覆盖用户改动
    """
    existing = _read_json(PREPROCESS_RULES_FILE, [])
    existing_ids = {r.get("id") for r in existing}

    if not existing:
        # 全新安装：预置默认 locked 规则 + 迁移旧 param_mapping
        rules = [dict(r) for r in _DEFAULT_LOCKED_RULES]
        old = _read_json(PARAM_MAPPING_FILE, {})
        for param, value in old.items():
            if param and re.fullmatch(r"\w+", param) and str(value).strip():
                rules.append({
                    "id": f"param-{param}",
                    "name": f"参数映射: {param}",
                    "pattern": r"\$\{" + param + r"\}",
                    "replacement": str(value),
                    "enabled": True,
                    "builtin": True,
                    "locked": False,
                })
        _write_json(PREPROCESS_RULES_FILE, rules)
    else:
        # 已有规则：补齐缺失的默认 locked 规则（版本升级场景）
        missing = [r for r in _DEFAULT_LOCKED_RULES if r["id"] not in existing_ids]
        if missing:
            # locked 规则插在最前面（核心清洗先执行）
            _write_json(PREPROCESS_RULES_FILE, missing + existing)


def get_preprocess_rules() -> list[dict]:
    """返回预处理规则列表（按数组顺序执行）。

    首次调用触发默认规则初始化 + 旧 param_mapping 迁移。
    每条规则: {id, name, pattern, replacement, enabled, builtin, locked}
    """
    _init_default_rules()
    return _read_json(PREPROCESS_RULES_FILE, [])


def set_preprocess_rules(rules: list[dict]) -> list[dict]:
    """更新预处理规则（全量替换），在文件锁保护下写入。

    校验：每条规则 pattern 必须 re.compile 通过（非法正则拒绝）。
    locked 规则不可删除：若用户提交的列表缺少 locked 规则，自动从
    _DEFAULT_LOCKED_RULES 补回（防止前端误删导致解析崩溃）。
    返回写入后的规则列表。
    """
    cleaned: list[dict] = []
    seen_ids: set[str] = set()
    for r in rules:
        rid = str(r.get("id", "")).strip()
        pattern = str(r.get("pattern", ""))
        if not rid or rid in seen_ids:
            continue  # id 必填且唯一
        if not pattern:
            continue  # pattern 必填
        if len(pattern) > 200:
            continue  # 超长 pattern 拒绝（ReDoS 缓解：灾难性回溯模式通常需要长嵌套）
        try:
            re.compile(pattern)
        except re.error:
            continue  # 非法正则拒绝
        seen_ids.add(rid)
        cleaned.append({
            "id": rid,
            "name": str(r.get("name", "")).strip()[:100],
            "pattern": pattern,
            "replacement": str(r.get("replacement", "")),
            "enabled": bool(r.get("enabled", True)),
            "builtin": bool(r.get("builtin", False)),
            "locked": bool(r.get("locked", False)),
        })
    # locked 规则保护：用户提交的列表里若缺少某个 locked 规则，补回它
    # （locked 规则的 enabled 状态尊重用户设置，但不可删除）
    for default_r in _DEFAULT_LOCKED_RULES:
        if default_r["id"] not in seen_ids:
            # 用户删了 locked 规则 → 补回（保持文件里已有的 enabled 状态）
            existing = _read_json(PREPROCESS_RULES_FILE, [])
            existing_rule = next((r for r in existing if r.get("id") == default_r["id"]), None)
            restored = dict(default_r)
            if existing_rule:
                restored["enabled"] = existing_rule.get("enabled", True)
            cleaned.insert(0, restored)  # locked 规则插最前面
    with _store_lock():
        _write_json(PREPROCESS_RULES_FILE, cleaned)
    return cleaned


# 旧接口保留向后兼容：export_all 用它生成向后兼容的 param_mapping 字段
def get_param_mapping() -> dict[str, str]:
    """[已废弃] 返回参数映射。从 preprocess_rules 里筛 id 以 'param-' 开头的规则反解。

    仅供 export_all 向后兼容导出字段使用；对应的 HTTP 路由已删除。
    """
    rules = get_preprocess_rules()
    mapping: dict[str, str] = {}
    for r in rules:
        rid = r.get("id", "")
        if rid.startswith("param-") and r.get("builtin"):
            # id 格式 param-{name}，name 即参数名
            param_name = rid[len("param-"):]
            if re.fullmatch(r"\w+", param_name):
                mapping[param_name] = r.get("replacement", "")
    return mapping


# ============================================================
# 标签维度 + 脚本打标
# ============================================================

def get_tag_schema() -> dict:
    """返回标签维度定义表。

    结构: {"dimensions": [{"name": "数仓层", "values": ["O层","C层",...]}]}

    部署后默认空（dimensions: []），由管理员通过设置面板填充。
    维度名和标签值完全由用户定义，代码层不预设任何维度。
    """
    return _read_json(TAG_SCHEMA_FILE, {"dimensions": []})


def set_tag_schema(schema: dict) -> dict:
    """更新标签维度定义表（全量替换），在文件锁保护下写入。

    清洗规则：
      - dimensions 必须是 list，每项 {name, values}
      - name 非空字符串，去首尾空白，长度 ≤ 50
      - values 是非空字符串列表，去重（保持顺序）
      - 同一 schema 内 dimension name 去重（重名后者覆盖前者）
    """
    raw_dims = schema.get("dimensions") if isinstance(schema, dict) else None
    cleaned_dims: list[dict] = []
    seen_dim_names: set[str] = set()
    if isinstance(raw_dims, list):
        for d in raw_dims if isinstance(raw_dims, list) else []:
            if not isinstance(d, dict):
                continue
            name = str(d.get("name", "")).strip()
            if not name or len(name) > 50 or name in seen_dim_names:
                continue
            raw_values = d.get("values") if isinstance(d.get("values"), list) else []
            values: list[str] = []
            seen_values: set[str] = set()
            for v in raw_values:
                sv = str(v).strip()
                if sv and sv not in seen_values:
                    values.append(sv)
                    seen_values.add(sv)
            cleaned_dims.append({"name": name, "values": values})
            seen_dim_names.add(name)
    with _store_lock():
        _write_json(TAG_SCHEMA_FILE, {"dimensions": cleaned_dims})
    return {"dimensions": cleaned_dims}


def set_script_tags(script_id: str, tags: list[str]) -> AnalysisResult | None:
    """给脚本打标签（全量替换脚本的 tags 数组）。

    只改 scripts/{id}.json，不影响全局表/边。
    清洗：去空白、去重、长度 ≤ 50（标签值通常是短词）。
    返回更新后的脚本，脚本不存在返回 None。
    """
    _validate_script_id(script_id)
    # 清洗标签：去首尾空白、去空、去重（保持顺序）
    cleaned: list[str] = []
    seen: set[str] = set()
    for t in tags:
        st = str(t).strip()
        if st and st not in seen and len(st) <= 50:
            cleaned.append(st)
            seen.add(st)
    with _store_lock():
        result = get_script(script_id)
        if not result:
            return None
        result.tags = cleaned
        result.updated_at = datetime.now()
        script_path = SCRIPTS_DIR / f"{script_id}.json"
        _write_json(script_path, result.model_dump())
    return result


def batch_set_script_tags(script_ids: list[str], tags: list[str]) -> dict:
    """批量给多个脚本打同一组标签（全量替换每个脚本的 tags）。

    用于批量上传/批量整理时给一批脚本统一打标。
    返回 {updated: [成功 id], failed: [{id, reason}]}。
    单个脚本失败不阻塞其他脚本（如脚本已被删除）。

    性能：整批一把锁 + 直接在原始 dict 上改 tags/updated_at 两个键后回写，
    不做 pydantic 全量反序列化/再序列化（旧实现逐脚本走 set_script_tags，
    N 个脚本 = N 次锁 + N 次完整 AnalysisResult 往返）。
    """
    # 清洗标签一次（避免每个脚本重复清洗）
    cleaned: list[str] = []
    seen: set[str] = set()
    for t in tags:
        st = str(t).strip()
        if st and st not in seen and len(st) <= 50:
            cleaned.append(st)
            seen.add(st)
    updated: list[str] = []
    failed: list[dict] = []
    now = datetime.now().isoformat()

    with _store_lock():
        for sid in script_ids:
            try:
                _validate_script_id(sid)
            except ValueError as e:
                failed.append({"id": sid, "reason": str(e)})
                continue
            path = SCRIPTS_DIR / f"{sid}.json"
            if not path.exists():
                failed.append({"id": sid, "reason": "脚本不存在"})
                continue
            try:
                data = _read_json(path)
                data["tags"] = list(cleaned)
                data["updated_at"] = now
                _write_json(path, data)
                updated.append(sid)
            except Exception:
                failed.append({"id": sid, "reason": "写入失败"})
    return {"updated": updated, "failed": failed}


# ============================================================
# 导入导出（全量数据）
# ============================================================

def export_all() -> dict:
    """聚合导出全部数据为单个 dict。

    包含 tables / edges / scripts / param_mapping 四部分，
    附加 version 和 exported_at 时间戳，用于迁移、备份、分享。
    """
    _ensure_dirs()
    scripts: dict[str, dict] = {}
    for f in SCRIPTS_DIR.glob("*.json"):
        try:
            scripts[f.stem] = _read_json(f)
        except Exception:
            continue
    return {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "tables": _read_json(TABLES_FILE, {}),
        "edges": _read_edges(),
        "scripts": scripts,
        "preprocess_rules": get_preprocess_rules(),
        # 向后兼容：旧版导入文件里有 param_mapping 字段，迁移逻辑会处理
        "param_mapping": get_param_mapping(),
        # 标签维度定义表（脚本的 tags 已包含在 scripts 里，无需单独导出）
        "tag_schema": get_tag_schema(),
    }


def import_all(payload: dict) -> None:
    """全量导入（在 _store_lock 内整体替换 4 处文件）。

    payload 结构同 export_all 的输出。导入前会清空现有 scripts 目录，
    然后逐个写入。tables/edges/param_mapping 直接覆盖。
    """
    with _store_lock():
        # tables
        _write_json(TABLES_FILE, payload.get("tables", {}))
        # edges
        _write_edges(payload.get("edges", []))
        # scripts：先清空目录，再逐个写入
        for f in SCRIPTS_DIR.glob("*.json"):
            f.unlink()
        for sid, data in payload.get("scripts", {}).items():
            # 安全：sid 直接拼进文件路径，必须走白名单校验，
            # 否则恶意 key（../ 或绝对路径）可写出数据目录之外（路径穿越）
            try:
                _validate_script_id(sid)
            except ValueError:
                continue
            _write_json(SCRIPTS_DIR / f"{sid}.json", data)
        # preprocess_rules（绕过 set_preprocess_rules 的锁，因为已在锁内）
        # 兼容旧版导入：若无 preprocess_rules 字段但有 param_mapping，走迁移
        if "preprocess_rules" in payload:
            _write_json(PREPROCESS_RULES_FILE, payload.get("preprocess_rules", []))
        elif "param_mapping" in payload:
            # 旧版导入文件：把 param_mapping 转为 builtin 规则
            _write_json(PREPROCESS_RULES_FILE, [
                {
                    "id": f"param-{k}",
                    "name": f"参数映射: {k}",
                    "pattern": r"\$\{" + k + r"\}",
                    "replacement": str(v),
                    "enabled": True,
                    "builtin": True,
                }
                for k, v in payload.get("param_mapping", {}).items()
                if k and re.fullmatch(r"\w+", k) and str(v).strip()
            ])
        # tag_schema（兼容旧版：无此字段时写空 schema）
        _write_json(TAG_SCHEMA_FILE, payload.get("tag_schema", {"dimensions": []}))

        # tables/edges 已被整体替换，重建内存缓存
        _refresh_cache()


# ============================================================
# 影响分析（基于 networkx 内存图，存储仍是 JSON）
# ============================================================

def build_graph() -> nx.DiGraph:
    """返回缓存的 networkx 有向图（实体图缓存的一部分）。

    旧版每次调用从 edges.jsonl 重建；现在复用内存缓存，下游/上游邻接为 O(1)。
    """
    return _get_cache().graph


def impact_analysis(table: str) -> dict:
    """影响分析：给定一个表，返回其上游/下游/路径/环信息。

    - downstream: 改这个表会影响哪些下游表（递归遍历所有后代）
    - upstream: 这个表的数据来自哪些上游表（递归遍历所有祖先）
    - paths: 下游全部路径（table → 各下游表的所有链路，含中间环节）
    - upstream_paths: 上游全部路径（各上游表 → table 的所有链路）
    - paths_truncated: 是否因路径过多触发上限裁剪（True 表示只返回了部分路径）
    - has_cycle: 全局图谱是否有环（数据流不应有环，有环说明分析有误）

    路径算法选择 [v2.3]：
      原 shortest_path 只返回最短链路，菱形依赖（A→B→C 且 A→C）下会漏掉
      A→B 这条实际发生影响的中间环节，造成"A→B 明明有血缘却不高亮"的误导。
      改用 all_simple_paths 返回全部路径，让前端把所有真实存在的链路边都高亮。

    路径爆炸防护（all_simple_paths 在病态菱形网格上指数级增长）：
      1. cutoff=MAX_PATH_DEPTH 限深（血缘链路极少超过 6-8 层）
      2. 单源路径数上限 MAX_PATHS_PER_PAIR，超过提前终止 + 标记 truncated
      3. has_cycle 时降级 shortest_path（环上 all_simple_paths 会无限循环）
    实测：真实 4 层数仓单源最大 5 条路径；病态宽5深5网格 125 条仍 <2ms。
    """
    # 路径爆炸防护参数
    MAX_PATH_DEPTH = 8       # 单条路径最大深度（边数），覆盖 ODS→DWD→DWS→ADS 等真实场景
    MAX_PATHS_PER_PAIR = 200  # 单个 (src,tgt) 对的最大路径数，超过则截断并标记

    G = _get_cache().graph
    # 对输入表名做归一化（图里的节点是 normalize 后的全限定名，含大小写折叠）
    table = normalize_table_name(table)
    if table not in G:
        return {"table": table, "error": "表不存在于血缘图中", "downstream": [], "upstream": []}

    downstream = sorted(nx.descendants(G, table))
    upstream = sorted(nx.ancestors(G, table))

    # 环检测：有环时 all_simple_paths 不安全（可能无限循环），降级用最短路径
    has_cycle = not nx.is_directed_acyclic_graph(G)
    use_full_paths = not has_cycle

    def _collect_paths(src: str, tgt: str) -> tuple[list[list[str]], bool]:
        """收集 src→tgt 的全部路径，返回 (路径列表, 是否被截断)。

        DAG 时用 all_simple_paths + cutoff + 数量上限；有环时降级最短路径。
        """
        if use_full_paths:
            paths: list[list[str]] = []
            truncated = False
            try:
                for p in nx.all_simple_paths(G, src, tgt, cutoff=MAX_PATH_DEPTH):
                    paths.append(p)
                    if len(paths) >= MAX_PATHS_PER_PAIR:
                        truncated = True
                        break
            except nx.NetworkXNoPath:
                pass
            return paths, truncated
        else:
            # 有环兜底：只给最短路径（保证有返回，避免无限循环）
            try:
                return [nx.shortest_path(G, src, tgt)], True
            except nx.NetworkXNoPath:
                return [], False

    # 下游全部路径
    paths: dict[str, list[list[str]]] = {}
    any_truncated = False
    for d in downstream:
        ps, trunc = _collect_paths(table, d)
        paths[d] = ps
        if trunc:
            any_truncated = True

    # 上游全部路径
    upstream_paths: dict[str, list[list[str]]] = {}
    for u in upstream:
        ps, trunc = _collect_paths(u, table)
        upstream_paths[u] = ps
        if trunc:
            any_truncated = True

    return {
        "table": table,
        "downstream": downstream,
        "upstream": upstream,
        "downstream_count": len(downstream),
        "upstream_count": len(upstream),
        "paths": paths,
        "upstream_paths": upstream_paths,
        "paths_truncated": any_truncated,
        "has_cycle": has_cycle,
    }


# ============================================================
# 内部方法
# ============================================================

def _merge_tables(result: AnalysisResult):
    """合并脚本的表信息到全局注册表（带 script_ids 反向索引）。

    必须在 _store_lock 内调用。
    """
    tables = _read_json(TABLES_FILE, {})
    now = datetime.now().isoformat()
    script_id = result.analysis_id

    def _touch(name: str, schema: str, *, columns: list | None = None,
               source: str = "database", table_type: str | None = None):
        """登记或更新一个表，把 script_id 追加到 script_ids（去重）。"""
        if not name:
            return
        if name in tables:
            rec = tables[name]
            rec["last_seen"] = now
            # 合并 script_ids（去重）
            sids = rec.setdefault("script_ids", [])
            if script_id not in sids:
                sids.append(script_id)
            rec["script_count"] = len(sids)
            # 合并列信息（如果之前为空）
            if not rec.get("columns") and columns:
                rec["columns"] = [{"name": c.name, "type": c.type} for c in columns]
        else:
            tables[name] = {
                "schema": schema,
                "name": name,
                "type": table_type or "source",  # 会被全局图逻辑重新判定
                "columns": [{"name": c.name, "type": c.type} for c in (columns or [])],
                "source": source,
                "first_seen": now,
                "script_ids": [script_id],
                "script_count": 1,
                "last_seen": now,
            }

    # 从 database_info 合并
    all_table_infos = list(result.database_info.tables_from_db) + list(result.database_info.tables_from_script)
    for ti in all_table_infos:
        name = normalize_table_name(ti.table_name)
        _touch(
            name,
            ti.schema_name,
            columns=ti.columns,
            source=ti.source,
            table_type=ti.table_type.value if hasattr(ti.table_type, "value") else str(ti.table_type),
        )

    # 也从 lineages 中收集表（确保不遗漏）
    for lin in result.lineages:
        for tname in [lin.source_table, lin.target_table]:
            normalized = normalize_table_name(tname)
            if normalized:
                _touch(normalized, "public", source="lineage")

    _write_json(TABLES_FILE, tables)


def _append_edges_for_script(result: AnalysisResult):
    """把脚本产生的血缘边逐条追加到 edges.jsonl（O(1) 追加，不重写）。

    必须在 _store_lock 内调用。
    """
    now = datetime.now().isoformat()
    for lin in result.lineages:
        if not lin.source_table:
            continue
        _append_edge({
            "edge_id": str(uuid.uuid4()),
            "source": normalize_table_name(lin.source_table),
            "target": normalize_table_name(lin.target_table),
            "operation": lin.operation_type.value if hasattr(lin.operation_type, "value") else str(lin.operation_type),
            "script_id": result.analysis_id,
            "statement_seq": lin.statement_seq,
            "created_at": now,
            # 列级血缘映射（DESIGN.v2 §6.4）：持久化到 edges.jsonl，
            # get_global_graph 反序列化为 GlobalEdge.column_mappings
            "column_mappings": [cm.model_dump() for cm in lin.column_mappings],
        })


def _remove_edges_for_script(script_id: str):
    """删除指定脚本关联的所有全局边（全量重写 edges.jsonl）。

    必须在 _store_lock 内调用。删除是低频操作，重写可接受。
    """
    edges = _read_edges()
    edges = [e for e in edges if e.get("script_id") != script_id]
    _write_edges(edges)


def _remove_script_from_tables(script_id: str):
    """全表扫：从每个表的 script_ids 移除 script_id，script_ids 变空的表删除。

    必须全表扫而非只看 edges 涉及的表，因为表可能从 database_info 或
    无源表 lineage（UPDATE 无源场景，边不写 edges.jsonl）登记进 tables.json，
    但这些表不一定出现在 edges 里。只看 edges 会漏（孤立表残留 bug）。
    tables.json 每个表带 script_ids 反向索引，全表扫 O(表数) 可接受。
    必须在 _store_lock 内调用。
    """
    tables = _read_json(TABLES_FILE, {})
    changed = False
    for name in list(tables.keys()):
        rec = tables[name]
        sids = rec.get("script_ids", [])
        if script_id in sids:
            sids = [s for s in sids if s != script_id]
            rec["script_ids"] = sids
            rec["script_count"] = len(sids)
            changed = True
            # script_ids 为空 → 该表不再被任何脚本引用 → 删除（孤立表清理）
            if not sids:
                del tables[name]
    if changed:
        _write_json(TABLES_FILE, tables)
