"""用户反馈 (m05823)：历史会话持久化 + 对话框换模型 + 技能管理界面。

覆盖：
- 会话 CRUD（列表/详情/改名/删除/404）。
- /chat 自动落库问答两轮、续聊注入历史、标题=首问。
- 对话框 model_id 覆盖优先于默认模型。
- 技能总开关：停用后不再注入工具、重新启用恢复。
"""

import json
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create_model(name="模型A", is_default=True):
    resp = client.post(
        "/api/v1/agent/models",
        json={
            "name": name,
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-x",
            "api_key": "sk-secret",
            "is_default": is_default,
        },
    )
    assert resp.status_code == 201, resp.text
    return _chat_body(resp)


def _fake_chat(db, messages, tool_schemas, tool_executor, *, model_id=None, **kwargs):
    # 记录注入给 LLM 的消息，便于断言「历史续聊」。
    _fake_chat.last_messages = messages
    _fake_chat.last_schemas = tool_schemas
    yield {"type": "content", "text": "这是一段模拟回答。"}
    yield {"type": "complete"}


def test_conversation_crud():
    crt = client.post("/api/v1/agent/conversations")
    assert crt.status_code == 201, crt.text
    cid = crt.json()["id"]

    listing = client.get("/api/v1/agent/conversations").json()
    assert any(c["id"] == cid for c in listing)

    detail = client.get(f"/api/v1/agent/conversations/{cid}").json()
    assert detail["messages"] == []
    assert detail["message_count"] == 0

    renamed = client.patch(f"/api/v1/agent/conversations/{cid}", json={"title": "重命名会话"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "重命名会话"

    assert client.delete(f"/api/v1/agent/conversations/{cid}").status_code == 405
    archived = client.post(f"/api/v1/agent/conversations/{cid}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert client.post(f"/api/v1/agent/conversations/{cid}/archive").status_code == 200
    assert all(c["id"] != cid for c in client.get("/api/v1/agent/conversations").json())
    assert any(
        c["id"] == cid for c in client.get("/api/v1/agent/conversations?archived=true").json()
    )
    assert client.get(f"/api/v1/agent/conversations/{cid}").status_code == 200
    assert client.post(f"/api/v1/agent/conversations/{cid}/restore").status_code == 200


def test_conversation_not_found():
    assert client.get(f"/api/v1/agent/conversations/{uuid.uuid4()}").status_code == 404
    assert client.post(f"/api/v1/agent/conversations/{uuid.uuid4()}/archive").status_code == 404


def test_chat_persists_messages_and_history():
    _create_model()
    with patch("app.agent.chat_router.stream_with_tools", side_effect=_fake_chat):
        first = client.post(
            "/api/v1/agent/chat",
            json={"question": "第一个问题：总资产多少？"},
        )
        assert first.status_code == 200, first.text
        cid = _chat_body(first)["conversation_id"]
        assert _chat_body(first)["title"] == "第一个问题：总资产多少？"

        # 续聊：历史应被注入，且会话里已有两条消息（user+assistant）
        second = client.post(
            "/api/v1/agent/chat",
            json={"question": "第二个问题：那风险呢？", "conversation_id": cid},
        )
        assert second.status_code == 200, second.text
        assert _chat_body(second)["conversation_id"] == cid
        assert "第一个问题" in "\n".join(m["content"] for m in _fake_chat.last_messages), (
            "续聊必须把上轮问答注入 LLM"
        )

    detail = client.get(f"/api/v1/agent/conversations/{cid}").json()
    assert detail["message_count"] == 4
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][0]["content"] == "第一个问题：总资产多少？"
    assert detail["messages"][1]["content"] == "这是一段模拟回答。"

    # 列表里的 message_count 也要对得上
    listing = client.get("/api/v1/agent/conversations").json()
    row = next(c for c in listing if c["id"] == cid)
    assert row["message_count"] == 4

    client.post(f"/api/v1/agent/conversations/{cid}/archive")
    preserved = client.get(f"/api/v1/agent/conversations/{cid}").json()
    assert preserved["message_count"] == 4
    assert preserved["messages"] == detail["messages"]


def test_chat_model_override_takes_priority():
    default = _create_model("默认模型", is_default=True)
    override = _create_model("临时模型", is_default=False)
    with patch("app.agent.chat_router.stream_with_tools", side_effect=_fake_chat) as mocked:
        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "用临时模型", "model_id": override["id"]},
        )
        assert resp.status_code == 200, resp.text
        assert _chat_body(resp)["model_id"] == override["id"]
        assert mocked.call_args.kwargs["model_id"] == override["id"]
    assert default["id"] != override["id"]


def test_skill_toggle_affects_tool_injection():
    _create_model()
    key = "read_summary"
    # 先确保启用
    client.patch(f"/api/v1/agent/definitions/skills/{key}", json={"enabled": True})
    with patch("app.agent.chat_router.stream_with_tools", side_effect=_fake_chat):
        client.post("/api/v1/agent/chat", json={"question": "概览"})
        names_on = [s.get("function", {}).get("name") for s in _fake_chat.last_schemas]
        assert key in names_on

    # 停用 -> 不再注入
    off = client.patch(f"/api/v1/agent/definitions/skills/{key}", json={"enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    with patch("app.agent.chat_router.stream_with_tools", side_effect=_fake_chat):
        client.post("/api/v1/agent/chat", json={"question": "概览2"})
        names_off = [s.get("function", {}).get("name") for s in _fake_chat.last_schemas]
        assert key not in names_off

    # 恢复启用，避免污染其他测试
    client.patch(f"/api/v1/agent/definitions/skills/{key}", json={"enabled": True})


def test_skill_toggle_unknown_404():
    resp = client.patch("/api/v1/agent/definitions/skills/not_a_skill", json={"enabled": False})
    assert resp.status_code == 404


def _chat_body(response):
    if "text/event-stream" not in response.headers.get("content-type", ""):
        return response.json()
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert not any(e["type"] == "error" for e in events), events
    return {
        **next(e for e in events if e["type"] == "meta"),
        "answer": "".join(e.get("text", "") for e in events if e["type"] == "content"),
    }
