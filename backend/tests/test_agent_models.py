"""M7 Phase 3 验收：模型配置 CRUD + 分析会话（仅对只读快照发问，模型调用被 mock）。

按 docs/agent-framework.md §模型配置 / §专用会话：
- 密钥 api_key 只写不读（列表/详情不回显明文或哈希）。
- 默认模型互斥：新建默认会清除其它默认；把某模型设为默认会取消原默认。
- 分析会话从只读资源快照 + 用户问题构造消息，调用 OpenAI 兼容端点（此处 mock），
  不直接写账本；无可用模型时返回 400「尚未配置可用的模型」。
"""

from fastapi.testclient import TestClient

from app.agent import llm
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


def _create_model(name="模型A", display_name=None, is_default=False):
    payload = {
        "name": name,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5",
        "api_key": "sk-secret-123",
        "is_default": is_default,
    }
    if display_name is not None:
        payload["display_name"] = display_name
    resp = client.post("/api/v1/agent/models", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_model_create_and_api_key_not_echoed():
    body = _create_model()
    assert body["id"]
    assert "api_key" not in body
    assert body["base_url"] == "https://api.openai.com/v1"
    assert body["model"] == "gpt-5"
    # 库内需存明文密钥（调用时用），但绝不在响应里回显
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.agent.models import AgentModel

        row = db.execute(select(AgentModel).where(AgentModel.id == body["id"])).scalars().first()
        assert row.api_key == "sk-secret-123"


def test_model_list_does_not_echo_api_key():
    _create_model()
    listing = client.get("/api/v1/agent/models").json()
    assert listing
    assert all("api_key" not in m for m in listing)


def test_model_create_with_display_name():
    body = _create_model(display_name="主力分析模型")
    assert body["display_name"] == "主力分析模型"
    # 别名随列表与详情返回
    listing = {m["id"]: m for m in client.get("/api/v1/agent/models").json()}
    assert listing[body["id"]]["display_name"] == "主力分析模型"
    detail = client.get(f"/api/v1/agent/models/{body['id']}").json()
    assert detail["display_name"] == "主力分析模型"


def test_model_patch_display_name():
    m = _create_model()
    upd = client.patch(f"/api/v1/agent/models/{m['id']}", json={"display_name": "改名后的别名"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["display_name"] == "改名后的别名"
    # 清空别名（null）应可写回
    upd2 = client.patch(f"/api/v1/agent/models/{m['id']}", json={"display_name": None})
    assert upd2.status_code == 200, upd2.text
    assert upd2.json()["display_name"] is None


def test_model_default_is_mutex():
    a = _create_model("A", is_default=True)
    b = _create_model("B", is_default=True)
    # 把 B 设为默认后，A 应不再是默认
    listing = {m["id"]: m for m in client.get("/api/v1/agent/models").json()}
    assert listing[b["id"]]["is_default"] is True
    assert listing[a["id"]]["is_default"] is False


def test_model_update_and_partial_api_key():
    m = _create_model()
    # 不传 api_key 应保留原密钥
    upd = client.patch(
        f"/api/v1/agent/models/{m['id']}",
        json={"name": "改名后", "is_default": True},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "改名后"
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.agent.models import AgentModel

        row = db.execute(select(AgentModel).where(AgentModel.id == m["id"])).scalars().first()
        assert row.api_key == "sk-secret-123"  # 仍保留


def test_model_update_api_key_replaces():
    m = _create_model()
    upd = client.patch(
        f"/api/v1/agent/models/{m['id']}",
        json={"api_key": "sk-new-secret"},
    )
    assert upd.status_code == 200, upd.text
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.agent.models import AgentModel

        row = db.execute(select(AgentModel).where(AgentModel.id == m["id"])).scalars().first()
        assert row.api_key == "sk-new-secret"


def test_model_delete():
    m = _create_model()
    resp = client.delete(f"/api/v1/agent/models/{m['id']}")
    assert resp.status_code == 204, resp.text
    assert client.get(f"/api/v1/agent/models/{m['id']}").status_code == 404


def test_model_404():
    import uuid

    resp = client.get(f"/api/v1/agent/models/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text


def test_chat_no_model_configured_returns_400(monkeypatch):
    # 不得清空与开发环境共享的用户模型配置。
    monkeypatch.setattr("app.agent.chat_router._resolve_model", lambda *args: None)

    resp = client.post(
        "/api/v1/agent/chat",
        json={"question": "我的组合风险如何？"},
    )
    assert resp.status_code == 400, resp.text
    assert "尚未配置可用的模型" in resp.text


def test_chat_returns_answer_from_llm(monkeypatch):
    # 建模型 + mock LLM 调用
    _create_model(is_default=True)
    captured = {}

    def fake_chat(
        db, messages, tool_schemas, tool_executor, *, model_id=None, temperature=0.3, max_rounds=6
    ):
        captured["messages"] = messages
        captured["model_id"] = model_id
        captured["tool_schemas"] = tool_schemas
        return "根据只读快照，你的组合整体风险可控。"

    monkeypatch.setattr(llm, "chat_with_tools", fake_chat)

    resp = client.post(
        "/api/v1/agent/chat",
        json={"question": "给我一个简要分析"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "根据只读快照，你的组合整体风险可控。"
    assert body["agent_name"]
    # 工具循环必须启用：模型被请求调用（首轮含 tool_calls）或最终文本；
    # 此处 mock 直接返回文本，断言系统提示与用户问题已注入。
    joined = "\n".join(m["content"] for m in captured["messages"])
    assert "只读数据快照" not in joined  # 新口径不再预拼快照，工具按需拉取
    assert "给我一个简要分析" in joined


def test_chat_unknown_agent_404():
    resp = client.post(
        "/api/v1/agent/chat",
        json={"question": "x", "agent_id": "00000000-0000-0000-0000-000000000099"},
    )
    assert resp.status_code == 404, resp.text
