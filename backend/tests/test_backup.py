import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.db import backup
from app.db.session import engine
from app.main import app


def test_backup_modes_and_exact_roundtrip(monkeypatch):
    schema = "backup_test_" + uuid.uuid4().hex
    with engine.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
    isolated = create_engine(engine.url, connect_args={"options": "-csearch_path=" + schema})
    try:
        with isolated.begin() as c:
            c.execute(text("CREATE TABLE alembic_version(version_num text primary key)"))
            c.execute(text("INSERT INTO alembic_version VALUES ('test')"))
            c.execute(text("CREATE TABLE agent_runs(id uuid primary key,status text)"))
            c.execute(
                text(
                    "CREATE TABLE journal_lines(id uuid primary key,entry_id uuid,"
                    "direction text,amount numeric)"
                )
            )
            c.execute(
                text("CREATE TABLE parents(id uuid primary key,amount numeric,payload jsonb)")
            )
            c.execute(
                text(
                    "CREATE TABLE children(id uuid primary key,"
                    "parent_id uuid references parents(id))"
                )
            )
            key = uuid.uuid4()
            c.execute(
                text("INSERT INTO parents VALUES (:id,123456789012.123456,CAST(:p AS jsonb))"),
                {"id": key, "p": '{"n":1.234567890123456789}'},
            )
            c.execute(text("INSERT INTO children VALUES (:id,:p)"), {"id": uuid.uuid4(), "p": key})
        monkeypatch.setattr(backup, "engine", isolated)
        with TestClient(app) as client:
            raw = client.get("/api/v1/backups/export").content
            assert (
                client.post("/api/v1/backups/preview", files={"file": ("b.sql", raw)}).status_code
                == 200
            )

            def restore(mode, content=raw):
                return client.post(
                    "/api/v1/backups/restore",
                    files={"file": ("b.sql", content)},
                    data={"mode": mode, "confirmation": "确认恢复"},
                )

            assert restore("incremental").status_code == 200
            with isolated.begin() as c:
                c.execute(text("UPDATE parents SET amount=1"))
            assert restore("overwrite").status_code == 200
            with isolated.connect() as c:
                assert str(c.scalar(text("SELECT amount FROM parents"))) == "123456789012.123456"
            assert restore("clear").status_code == 200
            with isolated.connect() as c:
                assert c.scalar(text("SELECT count(*) FROM children")) == 1
                assert c.scalar(text("SELECT count(*) FROM alembic_version")) == 1
            assert restore("clear", b"DROP TABLE parents;").status_code == 422
    finally:
        isolated.dispose()
        with engine.begin() as c:
            c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
