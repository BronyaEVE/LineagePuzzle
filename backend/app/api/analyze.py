from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.analysis import AnalysisResult, ScriptSummary, GlobalGraph
from ..schemas.requests import AnalyzeRequest, CorrectStatementRequest, BatchAnalyzeRequest
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


@router.post("/analyze-batch", response_model=list[AnalysisResult])
async def analyze_batch(request: BatchAnalyzeRequest):
    """批量分析多个 SQL 文件，每个文件产出独立脚本。

    前端解压 zip + 读取所有 .sql 文件内容后，以 {files: [{name, content}]}
    JSON 形式提交。后端逐个 analyze + save_script，每个文件成为一个独立脚本
    （各自 analysis_id，可单独删除/重命名）。

    部分失败容错：单个文件分析失败不阻塞其他文件。全部失败才返回 500，
    部分成功则返回成功的列表（失败信息通过 X-Batch-Errors 响应头透出）。
    """
    results: list[AnalysisResult] = []
    errors: list[str] = []
    for item in request.files:
        try:
            result = analyze(item.content, request.database_config)
            # 用文件名作为脚本显示名（去掉 .sql 后缀更清爽）
            result.name = item.name.removesuffix(".sql").removesuffix(".SQL")
            result = store.save_script(result)
            results.append(result)
        except Exception as e:
            errors.append(f"{item.name}: {str(e)}")

    # 全部失败才报错；部分成功则正常返回成功的列表
    if errors and not results:
        raise HTTPException(
            status_code=500,
            detail="全部文件分析失败: " + "; ".join(errors),
        )
    return results


# === 脚本管理 ===

@router.get("/scripts", response_model=list[ScriptSummary])
async def list_scripts():
    """获取所有脚本摘要列表。"""
    return store.list_scripts()


@router.get("/scripts/{script_id}", response_model=AnalysisResult)
async def get_script(script_id: str):
    """获取单个脚本的完整分析结果。"""
    try:
        result = store.get_script(script_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return result


@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str):
    """删除脚本及其关联的全局边。"""
    try:
        deleted = store.delete_script(script_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return {"status": "deleted"}


@router.put("/scripts/{script_id}/name")
async def rename_script(script_id: str, name: str = ""):
    """重命名脚本。"""
    try:
        result = store.update_script_name(script_id, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    try:
        result = store.get_script(script_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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


# === 导入导出 ===

@router.get("/export")
async def export_data():
    """导出全部分析数据（tables + edges + scripts + param_mapping）。

    返回单个 JSON，可保存为文件用于备份/迁移。
    """
    return store.export_all()


@router.post("/import")
async def import_data(payload: dict):
    """导入全部分析数据（全量覆盖现有数据）。

    请求体：export_all 的输出格式。会覆盖现有 tables/edges/scripts/param_mapping。
    """
    store.import_all(payload)
    return {"status": "ok", "message": "导入完成"}


# === 影响分析 ===

@router.get("/impact-analysis/{table}")
async def impact_analysis(table: str):
    """影响分析：给定一个表，返回其上游/下游/路径/环信息。

    用于回答：
    - "改了 orders 表，哪些下游表受影响？"（downstream）
    - "order_report 的数据来自哪些上游表？"（upstream）
    - "从 orders 到 daily_summary 的最短路径是什么？"（paths）
    - "全局血缘是否有环？"（has_cycle，有环说明数据流有误）
    """
    return store.impact_analysis(table)
