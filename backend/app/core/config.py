# 投谱后端配置。所有配置来自环境变量，禁止提交真实 .env。
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.0.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "toupu"
    app_version: str = APP_VERSION
    environment: str = "dev"
    debug: bool = True
    database_url: str = "postgresql+psycopg://toupu:toupu@localhost:5432/toupu"
    run_migrations_on_startup: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
