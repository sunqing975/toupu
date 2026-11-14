"""Run tests against a dedicated database, never the configured development database."""

import os

import psycopg
import pytest
from sqlalchemy.engine import make_url

from app.core.config import get_settings

# This must run before app.main / app.db.session are imported by test modules.
settings = get_settings()
source = make_url(settings.database_url)
target = make_url(
    os.environ.get(
        "TEST_DATABASE_URL", source.set(database="toupu_test").render_as_string(hide_password=False)
    )
)
if target.database == source.database or not (target.database or "").endswith("_test"):
    raise RuntimeError("测试数据库必须与开发库不同且名称以 _test 结尾")
admin = source.set(drivername="postgresql", database="postgres")
with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
    if not conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (target.database,)
    ).fetchone():
        conn.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(target.database))
        )
os.environ["DATABASE_URL"] = target.render_as_string(hide_password=False)
get_settings.cache_clear()

from app.main import run_migrations  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> None:
    run_migrations()
