from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    database: str
    username: str
    password: str


class AnalyzeRequest(BaseModel):
    script: str = Field(..., min_length=1, description="DML 脚本文本")
    database_config: DatabaseConfig


class CorrectStatementRequest(BaseModel):
    corrected_text: str = Field(..., min_length=1)
    tables_referenced: list[str] = Field(default_factory=list)
    tables_modified: list[str] = Field(default_factory=list)
