from enum import Enum

from pydantic import BaseModel, Field


class TableType(str, Enum):
    SOURCE = "source"
    INTERMEDIATE = "intermediate"
    TARGET = "target"


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


class ExtractionMethod(str, Enum):
    EXECUTION_PLAN = "execution_plan"
    STATIC_ANALYSIS = "static_analysis"


class OperationType(str, Enum):
    CREATE = "CREATE"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    MERGE = "MERGE"


class ColumnMapping(BaseModel):
    source_column: str
    target_column: str
    transformation: str | None = None


class Lineage(BaseModel):
    lineage_id: str
    source_table: str
    target_table: str
    operation_type: OperationType
    extraction_method: ExtractionMethod = ExtractionMethod.EXECUTION_PLAN
    statement_seq: int
    column_mappings: list[ColumnMapping] = Field(default_factory=list)
    dml_statement: str = ""
