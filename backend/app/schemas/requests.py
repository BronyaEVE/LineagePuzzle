from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    database: str
    username: str
    password: str


class AnalyzeRequest(BaseModel):
    script: str = Field(..., min_length=1, description="DML 脚本文本")
    # DESIGN.v2 §7.1：database_config 可选。不提供时以纯 AST 模式（ast_only）分析，不连接数据库。
    database_config: DatabaseConfig | None = None


class CorrectStatementRequest(BaseModel):
    corrected_text: str = Field(..., min_length=1)
    tables_referenced: list[str] = Field(default_factory=list)
    tables_modified: list[str] = Field(default_factory=list)


class BatchFileItem(BaseModel):
    """批量导入的单个文件项。

    name: 文件名（如 "create_tables.sql"），作为脚本的显示名。
    content: 文件内容（SQL 文本），前端已读取并（zip 已解压）。
    """
    name: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


class BatchAnalyzeRequest(BaseModel):
    """批量分析请求：一次提交多个 SQL 文件，每个产出独立脚本。

    前端解压 zip + 读取所有 .sql 文件内容后，以 JSON 数组形式提交，
    后端逐个 analyze + save_script。无需 python-multipart（避免新依赖）。
    """
    files: list[BatchFileItem] = Field(..., min_length=1)
    database_config: DatabaseConfig | None = None
