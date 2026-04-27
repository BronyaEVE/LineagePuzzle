from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.analysis import AnalysisResult
from ..schemas.requests import AnalyzeRequest, CorrectStatementRequest
from ..services.analyzer import analyze
from ..services.splitter import split_statements
from ..services.preprocessor import preprocess
from ..services.lineage_extractor import extract_lineages

router = APIRouter()

# 内存存储（MVP 阶段）
_analyses: dict[str, AnalysisResult] = {}


@router.post("/analyze", response_model=AnalysisResult)
async def analyze_script(request: AnalyzeRequest):
    """提交 DML 脚本进行血缘分析。"""
    try:
        result = analyze(request.script, request.database_config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

    _analyses[result.analysis_id] = result
    return result


@router.get("/analyses")
async def list_analyses(page: int = 1, page_size: int = 20):
    """获取历史分析记录。"""
    items = list(_analyses.values())
    items.sort(key=lambda x: x.created_at, reverse=True)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": len(items),
    }


@router.get("/analyses/{analysis_id}", response_model=AnalysisResult)
async def get_analysis(analysis_id: str):
    """获取单次分析详情。"""
    result = _analyses.get(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    return result


@router.get("/analyses/{analysis_id}/statements")
async def get_statements(analysis_id: str):
    """获取预处理和分段后的语句。"""
    result = _analyses.get(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    if not result.statement_group:
        raise HTTPException(status_code=404, detail="语句分段不存在")
    return result.statement_group


@router.put("/analyses/{analysis_id}/statements/{seq}", response_model=AnalysisResult)
async def correct_statement(analysis_id: str, seq: int, request: CorrectStatementRequest):
    """修正语句解析结果并重新生成血缘。"""
    result = _analyses.get(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析记录不存在")
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

    _analyses[analysis_id] = result
    return result
