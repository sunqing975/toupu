"""Version-matched data backups. Never executes uploaded SQL."""

import base64
import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import inspect, text

from app.db.session import engine

router = APIRouter(prefix="/api/v1/backups", tags=["backups"])
MAX_BYTES = 50 * 1024 * 1024
HEADER = "-- TOUPU_DATA_BACKUP_V1 "


def snapshot(conn) -> dict:
    inspector = inspect(conn)
    tables = {}
    for name in sorted(inspector.get_table_names()):
        rows = conn.execute(text('SELECT row_to_json(t)::text FROM "' + name + '" t')).scalars()
        tables[name] = list(rows)
    schema = {
        name: {c["name"]: str(c["type"]) for c in inspector.get_columns(name)} for name in tables
    }
    return {"format": "toupu-data-v1", "schema": schema, "tables": tables}


def encode(data: dict) -> bytes:
    # SQL-comment envelope prevents accidental execution and preserves JSON/Decimal strings.
    payload = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    return (
        HEADER + payload + "\n-- Restore this full-data backup through Toupu Settings.\n"
    ).encode()


def decode(raw: bytes) -> dict:
    try:
        if len(raw) > MAX_BYTES or not raw.startswith(HEADER.encode()):
            raise ValueError()
        line = raw.decode().splitlines()[0][len(HEADER) :]
        data = json.loads(base64.b64decode(line, validate=True))
        if data["format"] != "toupu-data-v1" or not isinstance(data["tables"], dict):
            raise ValueError()
        return data
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(422, "不是有效的投谱完整备份，或超过50MB") from None


def validate(conn, data):
    inspector = inspect(conn)
    names = set(inspector.get_table_names())
    if set(data["tables"]) != names:
        raise HTTPException(409, "备份表结构与当前版本不一致，请使用相同版本恢复")
    current = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if sorted(json.loads(r)["version_num"] for r in data["tables"]["alembic_version"]) != sorted(
        current
    ):
        raise HTTPException(409, "数据库迁移版本不一致")
    for name, rows in data["tables"].items():
        definitions = inspector.get_columns(name)
        columns = {c["name"] for c in definitions}
        if data.get("schema", {}).get(name) != {c["name"]: str(c["type"]) for c in definitions}:
            raise HTTPException(409, "备份字段类型与当前数据库不同：" + name)
        if not isinstance(rows, list) or any(
            not isinstance(r, str) or set(json.loads(r)) != columns for r in rows
        ):
            raise HTTPException(422, "备份列结构不一致：" + name)
    if any(
        json.loads(r).get("status") in {"QUEUED", "RUNNING", "WAITING_APPROVAL"}
        for r in data["tables"].get("agent_runs", [])
    ):
        raise HTTPException(409, "备份含未结束助手任务，不支持恢复后自动重放")
    return inspector


def inactive(conn):
    if conn.scalar(
        text(
            "SELECT count(*) FROM agent_runs "
            "WHERE status IN ('QUEUED','RUNNING','WAITING_APPROVAL')"
        )
    ):
        raise HTTPException(409, "有助手任务运行中，请先停止任务再备份或恢复")


@router.get("/export")
def export():
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        conn.begin(),
    ):
        inactive(conn)
        raw = encode(snapshot(conn))
    return Response(
        raw,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="toupu-full-backup.sql"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/preview")
async def preview(file: UploadFile = File(...)):
    try:
        raw = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()
    data = decode(raw)
    with engine.connect() as conn:
        validate(conn, data)
    return {
        "tables": {k: len(v) for k, v in data["tables"].items()},
        "warning": "包含所有投资数据和密钥；覆盖/清空会修改已入账历史，仅用于维护恢复。",
    }


@router.post("/restore")
async def restore(
    file: UploadFile = File(...),
    mode: Literal["clear", "overwrite", "incremental"] = Form(...),
    confirmation: str = Form(...),
):
    if confirmation != "确认恢复":
        raise HTTPException(422, "请输入“确认恢复”")
    try:
        raw = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()
    data = decode(raw)
    try:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout='5s'"))
            # Fixed current-schema table names only. Locks block concurrent API writes.
            inspector = validate(conn, data)
            names = sorted(data["tables"])
            quoted = ",".join('"' + n + '"' for n in names)
            conn.execute(text("LOCK TABLE " + quoted + " IN ACCESS EXCLUSIVE MODE"))
            inactive(conn)
            backup = encode(snapshot(conn))
            root = Path.home() / ".toupu-backups" / "before-restore"
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = root / (str(uuid.uuid4()) + ".sql")
            path.write_bytes(backup)
            path.chmod(0o600)
            if mode == "clear":
                clear_tables = ",".join('"' + n + '"' for n in names if n != "alembic_version")
                conn.execute(text("TRUNCATE " + clear_tables))
            # Retry unresolved FK dependencies, including self-references, using savepoints.
            pending = [(n, r) for n in names if n != "alembic_version" for r in data["tables"][n]]
            changed = 0
            while pending:
                remaining = []
                progress = 0
                for name, raw_row in pending:
                    row = json.loads(raw_row)
                    pk = inspector.get_pk_constraint(name)["constrained_columns"]
                    conflict = ",".join('"' + k + '"' for k in pk)
                    columns = ",".join('"' + k + '"' for k in row)
                    update = ",".join(
                        '"' + k + '"=EXCLUDED."' + k + '"' for k in row if k not in pk
                    )
                    action = (
                        ("DO UPDATE SET " + update)
                        if mode == "overwrite" and update
                        else "DO NOTHING"
                    )
                    sql = (
                        'INSERT INTO "'
                        + name
                        + '" ('
                        + columns
                        + ") SELECT "
                        + columns
                        + ' FROM jsonb_populate_record(NULL::"'
                        + name
                        + '",CAST(:row AS jsonb)) ON CONFLICT ('
                        + conflict
                        + ") "
                        + action
                    )
                    try:
                        with conn.begin_nested():
                            result = conn.execute(text(sql), {"row": raw_row})
                            changed += result.rowcount
                        progress += 1
                    except Exception as exc:
                        if getattr(getattr(exc, "orig", None), "sqlstate", None) == "23503":
                            remaining.append((name, raw_row))
                        else:
                            raise
                if remaining and not progress:
                    raise ValueError("foreign key dependencies unresolved")
                pending = remaining
            bad = conn.scalar(
                text(
                    "SELECT count(*) FROM (SELECT entry_id FROM journal_lines GROUP BY entry_id "
                    "HAVING sum(CASE WHEN direction='DEBIT' THEN amount ELSE -amount END)<>0) t"
                )
            )
            if bad:
                raise ValueError("unbalanced journal")
            if "audit_logs" in names:
                conn.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(id,actor,action,entity_type,entity_id,detail) "
                        "VALUES (:id,'user','RESTORE_DATABASE','database','restore',"
                        "CAST(:detail AS jsonb))"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "detail": json.dumps(
                            {"mode": mode, "changed": changed, "safety_backup": path.name}
                        ),
                    },
                )
            return {"mode": mode, "changed": changed, "safety_backup": path.name}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            409, "恢复失败，已整批回滚；可能存在业务唯一键冲突、引用缺失或账务不平衡"
        ) from None
