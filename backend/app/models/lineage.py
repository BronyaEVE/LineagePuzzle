"""血缘数据模型（引擎包再导出）+ Web/DB 层特有的表信息模型。

Lineage/ColumnMapping/TableType 等引擎模型已迁至 lineage_puzzle 包
（git 依赖 v0.1.0，单一真相源）；此处再导出以保持 `from ..models.lineage
import ...` 的既有引用不变。ColumnInfo/TableInfo 是 DB 校验层特有模型，
仅 Web 仓需要，留在此处。
"""
from pydantic import BaseModel, Field

from lineage_puzzle.schemas import (  # noqa: F401  再导出
    ColumnMapping,
    ExtractionMethod,
    Lineage,
    OperationType,
    TableType,
)


class ColumnInfo(BaseModel):
    name: str
    type: str = "UNKNOWN"


class TableInfo(BaseModel):
    schema_name: str = "public"
    table_name: str
    table_type: TableType = TableType.SOURCE
    source: str = Field(
        "database",
        description="database: 从 INFORMATION_SCHEMA 读取; script_created: 从脚本 CREATE 语句解析",
    )
    columns: list[ColumnInfo] = Field(default_factory=list)
