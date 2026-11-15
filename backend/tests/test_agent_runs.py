import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent import chat_router, runs
from app.db.session import SessionLocal
from app.main import app


def test_local_advice_never_waits_for_approval(monkeypatch):
    monkeypatch.setattr(runs, "check_cancelled", lambda *a: None)
    calls = []
    executor = runs.approved_executor(None, "unused", lambda *args: calls.append(args) or "ok")
    assert executor("create_draft_proposal", "{}", "local") == "ok"
    assert executor("read_summary", "{}", "read") == "ok"
    assert len(calls) == 2


def test_approval_wait_replay_and_duplicate_decision(monkeypatch):
    client = TestClient(app)
    ready = threading.Event()
    original = runs.emit
    calls = []

    def emit(db, run_id, event):
        original(db, run_id, event)
        if event["type"] == "approval_required":
            ready.set()

    monkeypatch.setattr(runs, "emit", emit)
    monkeypatch.setattr(
        chat_router, "_tool_executor", lambda *a: lambda *b: calls.append(b) or "created"
    )

    def stream(db, messages, schemas, execute, **kwargs):
        yield {
            "type": "tool_start",
            "id": "call-1",
            "name": "mcp__call",
            "arguments": "{}",
        }
        result = execute("mcp__call", "{}", "call-1")
        yield {"type": "tool_end", "id": "call-1", "result": result}
        yield {"type": "content", "text": "ok"}
        yield {"type": "complete"}

    monkeypatch.setattr(chat_router, "stream_with_tools", stream)
    model = client.post(
        "/api/v1/agent/models",
        json={
            "name": uuid.uuid4().hex,
            "base_url": "https://test/v1",
            "model": "test",
            "api_key": "test",
        },
    ).json()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(
            client.post,
            "/api/v1/agent/chat",
            json={"question": "approval", "model_id": model["id"]},
        )
        assert ready.wait(5)
        with SessionLocal() as db:
            row = (
                db.execute(
                    text(
                        "SELECT run_id,id FROM agent_tool_approvals "
                        "ORDER BY created_at DESC LIMIT 1"
                    )
                )
                .mappings()
                .one()
            )
        rid, aid = str(row["run_id"]), str(row["id"])
        assert calls == []
        assert client.get(f"/api/v1/agent/runs/{rid}").json()["status"] == "WAITING_APPROVAL"
        assert (
            client.post(
                f"/api/v1/agent/runs/{rid}/approvals/{aid}", json={"approve": True}
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/v1/agent/runs/{rid}/approvals/{aid}", json={"approve": True}
            ).status_code
            == 409
        )
        response = future.result(timeout=5)
    assert len(calls) == 1
    assert client.get(f"/api/v1/agent/runs/{rid}").json()["status"] == "SUCCEEDED"
    replay = client.get(f"/api/v1/agent/runs/{rid}/events").text
    assert replay == response.text
    events = [json.loads(line[5:]) for line in replay.splitlines() if line.startswith("data:")]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    remaining = client.get(f"/api/v1/agent/runs/{rid}/events?after=2").text
    assert '"seq": 1,' not in remaining
    assert '"type": "done"' in remaining


@pytest.mark.parametrize("approve", [False, None])
def test_rejection_and_cancellation_do_not_execute(monkeypatch, approve):
    client = TestClient(app)
    ready = threading.Event()
    original = runs.emit

    def emit(db, rid, event):
        original(db, rid, event)
        if event["type"] == "approval_required":
            ready.set()

    monkeypatch.setattr(runs, "emit", emit)

    def execute(*args):
        raise AssertionError("must not execute")

    monkeypatch.setattr(chat_router, "_tool_executor", lambda *a: execute)

    def stream(db, messages, schemas, executor, **kwargs):
        result = executor("mcp__call", "{}", "call")
        yield {"type": "content", "text": result}
        yield {"type": "complete"}

    monkeypatch.setattr(chat_router, "stream_with_tools", stream)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, "/api/v1/agent/chat", json={"question": "deny"})
        assert ready.wait(5)
        with SessionLocal() as db:
            row = (
                db.execute(
                    text(
                        "SELECT run_id,id FROM agent_tool_approvals "
                        "ORDER BY created_at DESC LIMIT 1"
                    )
                )
                .mappings()
                .one()
            )
        rid, aid = str(row["run_id"]), str(row["id"])
        if approve is None:
            assert client.post(f"/api/v1/agent/runs/{rid}/cancel").status_code == 200
        else:
            assert (
                client.post(
                    f"/api/v1/agent/runs/{rid}/approvals/{aid}", json={"approve": False}
                ).status_code
                == 200
            )
        response = future.result(timeout=5)
    assert client.get(f"/api/v1/agent/runs/{rid}").json()["status"] == (
        "CANCELLED" if approve is None else "SUCCEEDED"
    )
    assert ("任务已取消" if approve is None else "用户拒绝") in response.text
