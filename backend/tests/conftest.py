# 测试启动前确保迁移已应用（模块级 TestClient 不触发 lifespan）。
import pytest

from app.main import run_migrations


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> None:
    run_migrations()
