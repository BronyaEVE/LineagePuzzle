from datetime import datetime

from pydantic import BaseModel, Field

from .lineage import Lineage, TableInfo
from .statement import StatementGroup


class DatabaseInfo(BaseModel):
    tables_from_db: list[TableInfo] = Field(default_factory=list)
    tables_from_script: list[TableInfo] = Field(default_factory=list)


class VisNode(BaseModel):
    id: str
    label: str
    type: str  # source / intermediate / target


class VisEdge(BaseModel):
    source: str
    target: str
    label: str
    statement_seq: int


class Visualization(BaseModel):
    nodes: list[VisNode] = Field(default_factory=list)
    edges: list[VisEdge] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    analysis_id: str
    name: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = None
    input_script: str = ""
    database_info: DatabaseInfo = Field(default_factory=DatabaseInfo)
    statement_group: StatementGroup | None = None
    lineages: list[Lineage] = Field(default_factory=list)
    visualization: Visualization = Field(default_factory=Visualization)


class ScriptSummary(BaseModel):
    analysis_id: str
    name: str
    created_at: datetime
    statement_count: int = 0
    table_count: int = 0


class GlobalEdge(BaseModel):
    edge_id: str
    source: str
    target: str
    operation: str
    script_id: str
    statement_seq: int
    created_at: str = ""


class GlobalGraph(BaseModel):
    nodes: list[VisNode] = Field(default_factory=list)
    edges: list[GlobalEdge] = Field(default_factory=list)
