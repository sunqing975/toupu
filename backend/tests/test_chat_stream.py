import json
import uuid

from fastapi.testclient import TestClient

from app.agent import chat_router
from app.main import app


def test_stream_route_persists_only_successful_pair(monkeypatch):
    client = TestClient(app)
    model = client.post(
        "/api/v1/agent/models",
        json={
            "name": "stream-" + uuid.uuid4().hex,
            "base_url": "https://test/v1",
            "model": "test",
            "api_key": "test",
        },
    ).json()

    def success(*args, **kwargs):
        yield {"type": "reasoning", "text": "check"}
        yield {"type": "content", "text": "**ok**"}
        yield {"type": "complete"}

    monkeypatch.setattr(chat_router, "stream_with_tools", success)
    response = client.post(
        "/api/v1/agent/chat?stream=true", json={"question": "stream test", "model_id": model["id"]}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")
    ]
    assert [e["type"] for e in events] == ["meta", "reasoning", "content", "done"]
    cid = events[0]["conversation_id"]
    detail = client.get("/api/v1/agent/conversations/" + cid).json()
    assert [m["content"] for m in detail["messages"]] == ["stream test", "**ok**"]

    def failure(*args, **kwargs):
        yield {"type": "content", "text": "partial"}
        raise RuntimeError("private upstream failure")

    monkeypatch.setattr(chat_router, "stream_with_tools", failure)
    response = client.post(
        "/api/v1/agent/chat?stream=true",
        json={"question": "fail test", "model_id": model["id"], "conversation_id": cid},
    )
    assert '"type": "error"' in response.text
    assert "private upstream failure" not in response.text
    assert len(client.get("/api/v1/agent/conversations/" + cid).json()["messages"]) == 2
