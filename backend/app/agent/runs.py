"""Database-backed runs. Subscribers never own worker lifetime or business transactions."""

import asyncio
import json
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.conversations import append_message
from app.db.session import SessionLocal, get_db

router = APIRouter(prefix="/api/v1/agent/runs", tags=["agent-runs"])
ACTIVE = ("QUEUED", "RUNNING", "WAITING_APPROVAL")
_workers: dict[str, threading.Thread] = {}
_lock = threading.Lock()


class RunCancelled(Exception):
    pass


def get_run(db, run_id):
    row = (
        db.execute(text("SELECT * FROM agent_runs WHERE id=:id"), {"id": run_id}).mappings().first()
    )
    if row is None:
        raise HTTPException(404, "任务不存在")
    return row


def emit(db, run_id, event):
    # Row lock makes sequence allocation safe against cancellation/approval requests.
    db.execute(text("SELECT id FROM agent_runs WHERE id=:id FOR UPDATE"), {"id": run_id})
    db.execute(
        text("""INSERT INTO agent_run_events(run_id,seq,event)
        SELECT :id, COALESCE(MAX(seq),0)+1, CAST(:event AS jsonb)
        FROM agent_run_events WHERE run_id=:id"""),
        {"id": run_id, "event": json.dumps(event, ensure_ascii=False)},
    )
    db.commit()


def check_cancelled(db, run_id):
    db.expire_all()
    row = get_run(db, run_id)
    db.rollback()
    if row["cancel_requested"] or row["status"] not in ACTIVE:
        raise RunCancelled()


def approved_executor(db, run_id, execute):
    def invoke(name, arguments, call_id):
        check_cancelled(db, run_id)
        if not name.startswith("mcp__"):
            return execute(name, arguments)
        approval_id = uuid.uuid4()
        args = json.loads(arguments)
        db.execute(
            text("""INSERT INTO agent_tool_approvals(id,run_id,call_id,name,arguments)
            VALUES (:id,:run,:call,:name,CAST(:args AS jsonb))"""),
            {
                "id": approval_id,
                "run": run_id,
                "call": call_id,
                "name": name,
                "args": json.dumps(args),
            },
        )
        db.execute(
            text("UPDATE agent_runs SET status='WAITING_APPROVAL',updated_at=now() WHERE id=:id"),
            {"id": run_id},
        )
        emit(
            db,
            run_id,
            {
                "type": "approval_required",
                "approval_id": str(approval_id),
                "id": call_id,
                "name": name,
                "arguments": arguments,
            },
        )
        while True:
            check_cancelled(db, run_id)
            row = db.execute(
                text("SELECT status FROM agent_tool_approvals WHERE id=:id"), {"id": approval_id}
            ).scalar_one()
            db.rollback()
            if row != "PENDING":
                break
            threading.Event().wait(0.25)
        db.execute(
            text("UPDATE agent_runs SET status='RUNNING',updated_at=now() WHERE id=:id"),
            {"id": run_id},
        )
        db.commit()
        check_cancelled(db, run_id)
        if row == "REJECTED":
            return "用户拒绝了此操作；未执行。"
        # Claim once before execution: restart never automatically repeats a side effect.
        db.execute(
            text("UPDATE agent_tool_approvals SET status='EXECUTING' WHERE id=:id"),
            {"id": approval_id},
        )
        db.commit()
        result = execute(name, arguments)
        db.execute(
            text("UPDATE agent_tool_approvals SET status='EXECUTED',result=:result WHERE id=:id"),
            {"id": approval_id, "result": result},
        )
        db.commit()
        return result

    return invoke


def start(run_id, stream, executor_factory):
    def work():
        with SessionLocal() as db:
            try:
                row = get_run(db, run_id)
                data = row["input"]
                claimed = db.execute(
                    text(
                        "UPDATE agent_runs SET status='RUNNING',updated_at=now() "
                        "WHERE id=:id AND status='QUEUED' RETURNING id"
                    ),
                    {"id": run_id},
                ).scalar_one_or_none()
                db.commit()
                if claimed is None:
                    return
                check_cancelled(db, run_id)
                parts = []
                execute = approved_executor(db, run_id, executor_factory(db))
                for event in stream(
                    db,
                    data["messages"],
                    data["schemas"],
                    execute,
                    model_id=data["meta"]["model_id"],
                    check_cancelled=lambda: check_cancelled(db, run_id),
                    executor_with_id=True,
                ):
                    check_cancelled(db, run_id)
                    if event["type"] == "content":
                        parts.append(event["text"])
                    if event["type"] != "complete":
                        emit(db, run_id, event)
                check_cancelled(db, run_id)
                meta = data["meta"]
                for role, content in (("user", data["question"]), ("assistant", "".join(parts))):
                    append_message(
                        db,
                        uuid.UUID(meta["conversation_id"]),
                        role=role,
                        content=content,
                        agent_name=meta["agent_name"],
                        model_name=meta["model_name"],
                        model_id=meta["model_id"],
                    )
                db.execute(
                    text("UPDATE agent_runs SET status='SUCCEEDED',updated_at=now() WHERE id=:id"),
                    {"id": run_id},
                )
                emit(db, run_id, {"type": "done", **meta})
            except Exception as exc:
                db.rollback()
                cancelled = isinstance(exc, RunCancelled)
                db.execute(
                    text("UPDATE agent_runs SET status=:status,updated_at=now() WHERE id=:id"),
                    {"id": run_id, "status": "CANCELLED" if cancelled else "FAILED"},
                )
                emit(
                    db,
                    run_id,
                    {
                        "type": "error",
                        "message": "任务已取消"
                        if cancelled
                        else "任务失败，请检查模型或工具状态；已产生的审批记录保留。",
                    },
                )
            finally:
                with _lock:
                    _workers.pop(str(run_id), None)

    with _lock:
        if str(run_id) in _workers:
            return
        thread = threading.Thread(target=work, name="agent-run-" + str(run_id), daemon=True)
        _workers[str(run_id)] = thread
        thread.start()


def recover_interrupted():
    # Single-process local deployment. Never replay uncertain side effects on restart.
    with SessionLocal() as db:
        ids = (
            db.execute(
                text(
                    "UPDATE agent_runs SET status='INTERRUPTED',updated_at=now() "
                    "WHERE status IN ('QUEUED','RUNNING','WAITING_APPROVAL') RETURNING id"
                )
            )
            .scalars()
            .all()
        )
        for run_id in ids:
            emit(
                db,
                run_id,
                {
                    "type": "error",
                    "message": "服务重启，任务中断；未自动重试，请核对审批和业务记录。",
                },
            )
        db.commit()


async def event_stream(run_id, after=0):
    cursor = after
    while True:
        with SessionLocal() as db:
            run = get_run(db, run_id)
            rows = db.execute(
                text(
                    "SELECT seq,event FROM agent_run_events WHERE run_id=:id "
                    "AND seq>:seq ORDER BY seq LIMIT 200"
                ),
                {"id": run_id, "seq": cursor},
            ).all()
            active = run["status"] in ACTIVE
        for seq, event in rows:
            cursor = seq
            yield (
                "id: "
                + str(seq)
                + "\ndata: "
                + json.dumps({**event, "seq": seq}, ensure_ascii=False)
                + "\n\n"
            )
        if not active and len(rows) < 200:
            return
        if not rows:
            yield ": heartbeat\n\n"
        await asyncio.sleep(0.2)


@router.get("")
def list_runs(conversation_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    query = "SELECT id,conversation_id,status,created_at,updated_at FROM agent_runs"
    if conversation_id:
        query += " WHERE conversation_id=:cid"
    return [
        dict(row)
        for row in db.execute(
            text(query + " ORDER BY created_at DESC LIMIT 100"), {"cid": conversation_id}
        ).mappings()
    ]


@router.get("/{run_id}")
def run_detail(run_id: uuid.UUID, db: Session = Depends(get_db)):
    row = get_run(db, run_id)
    approvals = (
        db.execute(
            text("SELECT * FROM agent_tool_approvals WHERE run_id=:id ORDER BY created_at"),
            {"id": run_id},
        )
        .mappings()
        .all()
    )
    return {
        "id": run_id,
        "status": row["status"],
        "meta": row["input"]["meta"],
        "question": row["input"]["question"],
        "approvals": [dict(a) for a in approvals],
    }


@router.get("/{run_id}/events")
def subscribe(run_id: uuid.UUID, after: int = Query(0, ge=0), db: Session = Depends(get_db)):
    get_run(db, run_id)
    return StreamingResponse(
        event_stream(run_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/cancel")
def cancel(run_id: uuid.UUID, db: Session = Depends(get_db)):
    get_run(db, run_id)
    db.execute(
        text("UPDATE agent_runs SET cancel_requested=TRUE,updated_at=now() WHERE id=:id"),
        {"id": run_id},
    )
    db.commit()
    return {"status": "cancel_requested"}


class Decision(BaseModel):
    approve: bool


@router.post("/{run_id}/approvals/{approval_id}")
def decide(
    run_id: uuid.UUID, approval_id: uuid.UUID, payload: Decision, db: Session = Depends(get_db)
):
    db.execute(text("SELECT id FROM agent_runs WHERE id=:id FOR UPDATE"), {"id": run_id})
    run = get_run(db, run_id)
    if run["status"] != "WAITING_APPROVAL" or run["cancel_requested"]:
        raise HTTPException(409, "任务已结束或不在等待审批")
    result = db.execute(
        text(
            "UPDATE agent_tool_approvals SET status=:status,decided_at=now() "
            "WHERE id=:id AND run_id=:run AND status='PENDING' RETURNING id"
        ),
        {"id": approval_id, "run": run_id, "status": "APPROVED" if payload.approve else "REJECTED"},
    ).scalar_one_or_none()
    if result is None:
        raise HTTPException(409, "审批不存在或已处理")
    emit(
        db,
        run_id,
        {"type": "approval_decided", "approval_id": str(approval_id), "approved": payload.approve},
    )
    return {"approved": payload.approve}
