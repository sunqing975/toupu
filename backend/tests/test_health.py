from fastapi.testclient import TestClient

from app.main import app


def test_health_ok() -> None:
    # TestClient 上下文会触发 lifespan：启动时执行未应用的迁移
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "app": "toupu", "version": "0.0.1"}


def test_migrations_up_to_date() -> None:
    # alembic_version 只存当前 head；与版本目录的实际 head 比对，加迁移无需改测试
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from app.db.session import SessionLocal

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()

    with TestClient(app), SessionLocal() as db:
        versions = {r[0] for r in db.execute(text("SELECT version_num FROM alembic_version"))}
    assert versions == {head}


def test_error_response_is_unified() -> None:
    with TestClient(app) as client:
        resp = client.get("/not-exists")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_health_ok_no_client() -> None:
    # 无 lifespan 场景下 /health 也可用（迁移在 lifespan 中执行）
    client = TestClient(app)
    assert client.get("/health").status_code == 200
