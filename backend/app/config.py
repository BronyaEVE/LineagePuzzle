from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LineagePuzzle"
    debug: bool = True
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


settings = Settings()
