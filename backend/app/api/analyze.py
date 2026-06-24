from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.analysis import AnalysisResult, ScriptSummary, GlobalGraph
from ..schemas.requests import AnalyzeRequest, CorrectStatementRequest
from ..services.analyzer import analyze
from ..services.lineage_extractor import extract_lineages
from ..services import store

router = APIRouter()


@router.post("/analyze", response_model=AnalysisResult)
async def analyze_script(request: AnalyzeRequest):
    """提交 DML 脚本进行血缘分析，结果自动存入持久化存储。"""
    try:
        result = analyze(request.script, request.database_config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

    result = store.save_script(result)
    return result


# === 脚本管理 ===

@router.get("/scripts", response_model=list[ScriptSummary])
async def list_scripts():
    """获取所有脚本摘要列表。"""
    return store.list_scripts()


@router.get("/scripts/{script_id}", response_model=AnalysisResult)
async def get_script(script_id: str):
    """获取单个脚本的完整分析结果。"""
    result = store.get_script(script_id)
    if not result:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return result


@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str):
    """删除脚本及其关联的全局边。"""
    if not store.delete_script(script_id):
        raise HTTPException(status_code=404, detail="脚本不存在")
    return {"status": "deleted"}


@router.put("/scripts/{script_id}/name")
async def rename_script(script_id: str, name: str = ""):
    """重命名脚本。"""
    result = store.update_script_name(script_id, name)
    if not result:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return {"status": "renamed", "name": name}


@router.get("/scripts/{script_id}/statements")
async def get_statements(script_id: str):
    """获取脚本的语句分段。"""
    result = store.get_script(script_id)
    if not result:
        raise HTTPException(status_code=404, detail="脚本不存在")
    if not result.statement_group:
        raise HTTPException(status_code=404, detail="语句分段不存在")
    return result.statement_group


@router.put("/scripts/{script_id}/statements/{seq}", response_model=AnalysisResult)
async def correct_statement(script_id: str, seq: int, request: CorrectStatementRequest):
    """修正语句解析结果并重新生成血缘。"""
    result = store.get_script(script_id)
    if not result:
        raise HTTPException(status_code=404, detail="脚本不存在")
    if not result.statement_group:
        raise HTTPException(status_code=404, detail="语句分段不存在")

    # 找到并更新语句
    stmt = None
    for s in result.statement_group.statements:
        if s.seq == seq:
            stmt = s
            break
    if not stmt:
        raise HTTPException(status_code=404, detail=f"语句 #{seq} 不存在")

    stmt.text = request.corrected_text
    stmt.tables_referenced = request.tables_referenced
    stmt.tables_modified = request.tables_modified

    # 重新提取血缘
    lineages, table_type_map = extract_lineages(result.statement_group.statements)
    result.lineages = lineages

    # 重新构建可视化
    from ..services.analyzer import _build_visualization
    result.visualization = _build_visualization(lineages, table_type_map)

    # 原子地替换该脚本的边（删旧边 + 保存新结果 + 加新边，全程持锁）
    # 注意：不能分开调 _remove_edges_for_script + save_script，中间无锁会丢数据
    store.replace_script_edges(result)

    return result


# === 全局图谱 ===

@router.get("/global-graph", response_model=GlobalGraph)
async def get_global_graph():
    """获取全局累积血缘图谱。"""
    return store.get_global_graph()


@router.get("/tables")
async def get_tables():
    """获取全局表注册表。"""
    return store.get_tables()


# === 全局参数映射 ===

@router.get("/param-mapping")
async def get_param_mapping():
    """获取全局参数映射表 {param_name: actual_value}。

    用于分析时把 SQL 里的 ${param} 占位符替换成实际值。
    """
    return store.get_param_mapping()


@router.put("/param-mapping")
async def set_param_mapping(mapping: dict):
    """更新全局参数映射表（全量替换）。

    请求体：{"icl_schema": "ods", "env": "prod"}
    分析时 ${icl_schema}.orders → ods.orders，${env} → prod。
    key 必须是合法标识符（字母数字下划线），否则被过滤。
    """
    return store.set_param_mapping(mapping)
