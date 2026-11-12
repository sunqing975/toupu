# 投谱后端配置。所有配置来自环境变量，禁止提交真实 .env。
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "toupu"
    environment: str = "dev"
    debug: bool = True
    database_url: str = "postgresql+psycopg://toupu:toupu@localhost:5432/toupu"


@lru_cache
def get_settings() -> Settings:
    return Settings()
