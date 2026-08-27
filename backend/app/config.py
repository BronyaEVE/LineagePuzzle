from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 环境变量前缀 LINEAGE_：如 LINEAGE_DEBUG=1（api_token 用显式别名 LINEAGE_TOKEN）
    model_config = SettingsConfigDict(env_prefix="LINEAGE_")

    app_name: str = "LineagePuzzle"
    # 生产默认关 debug（debug=True 会在错误响应里带完整 traceback；
    # 便携版绑 0.0.0.0 时对 LAN 暴露）。开发时用环境变量 LINEAGE_DEBUG=1 开启。
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    # 可选 API 令牌：设置后所有 /api/* 请求须携带（?token= 查询参数或
    # Authorization: Bearer 头）。用于 0.0.0.0 LAN 共享模式下的最小鉴权。
    # 未设置时保持无鉴权（本地/桌面模式）。
    # 注意：显式别名 LINEAGE_TOKEN（prefix 只会拼出 LINEAGE_API_TOKEN）。
    api_token: str = Field(default="", validation_alias="LINEAGE_TOKEN")


settings = Settings()
