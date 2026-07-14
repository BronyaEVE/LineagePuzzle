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


class PreprocessRule(BaseModel):
    """单条预处理规则。

    预处理模块把「参数映射」和「自定义清洗」统一为「正则替换规则」。
    每条规则在 SQL 解析前对脚本文本执行一次 re.sub(pattern, replacement)。

    - id: 规则唯一标识（前端用 uuid 生成），用于开关/删除定位
    - name: 用户可读名称（如 "去单行注释"、"参数映射: icl_schema"）
    - pattern: Python 正则表达式（re.sub 第一个参数）
    - replacement: 替换文本，支持 $1 $2 反向引用（re.sub 第二个参数）
    - enabled: 是否启用（关闭的规则在 preprocess 时跳过）
    - builtin: 是否内置规则（用于前端区分样式 + "恢复默认"）
    """
    id: str = Field(..., min_length=1)
    name: str = Field("", max_length=100)
    pattern: str = Field(..., min_length=1)
    replacement: str = Field("")
    enabled: bool = True
    builtin: bool = False
