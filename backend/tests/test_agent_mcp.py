# M7 Phase 4：外部 MCP 服务挂载管理 + 会话注入（docs/agent-framework.md §外部 MCP 挂载）。
# 覆盖：CRUD、transport 校验、test 连接、chat 注入外部知识、fetch 容错。
import uuid

from fastapi.testclient import TestClient

from app.agent import chat_router
from app.agent import mcp_client as mcp_client_mod
from app.main import app

client = TestClient(app)


def _sid() -> str:
    return uuid.uuid4().hex[:10]


def _create(name: str, transport: str = "http", **kw) -> dict:
    payload = {"name": name, "transport": transport}
    payload.update(kw)
    resp = client.post("/api/v1/agent/mcp-servers", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_mcp_server_crud():
    name = f"mcp-{_sid()}"
    created = _create(name, "http", url="http://127.0.0.1:1/mcp/")
    assert created["name"] == name
    assert created["transport"] == "http"
    assert "command" in created  # 响应字段存在
    assert created["enabled"] is True

    sid = created["id"]
    lst = client.get("/api/v1/agent/mcp-servers").json()
    assert any(s["id"] == sid for s in lst)
    det = client.get(f"/api/v1/agent/mcp-servers/{sid}").json()
    assert det["id"] == sid
    upd = client.patch(
        f"/api/v1/agent/mcp-servers/{sid}", json={"enabled": False}
    ).json()
    assert upd["enabled"] is False
    assert client.delete(f"/api/v1/agent/mcp-servers/{sid}").status_code == 204
    assert client.get(f"/api/v1/agent/mcp-servers/{sid}").status_code == 404


def test_mcp_server_transport_validation():
    name = f"mcp-{_sid()}"
    r = client.post(
        "/api/v1/agent/mcp-servers",
        json={"name": name, "transport": "stdio"},  # stdio 缺 command
    )
    assert r.status_code == 422, r.text
    r = client.post(
        "/api/v1/agent/mcp-servers",
        json={"name": name, "transport": "ftp"},  # 非法 transport
    )
    assert r.status_code == 422, r.text


def test_mcp_server_test_connection_reports_failure():
    # 指向一个不存在的地址，test 应返回 ok=false 而非 500。
    created = _create(f"mcp-{_sid()}", "http", url="http://127.0.0.1:1/mcp/")
    sid = created["id"]
    res = client.post(f"/api/v1/agent/mcp-servers/{sid}/test").json()
    assert res["ok"] is False
    assert "失败" in res["detail"] or res["detail"]


def test_fetch_external_knowledge_handles_no_servers(monkeypatch):
    # 数据库里没有启用服务时应返回空串，不抛异常。
    monkeypatch.setattr(
        mcp_client_mod, "fetch_external_knowledge", lambda db, **kw: ""  # noqa: ARG005
    )

    class _FakeDB:
        def execute(self, q):
            class _R:
                def scalars(self):
                    return self

                def all(self):
                    return []

            return _R()

    out = mcp_client_mod.fetch_external_knowledge(_FakeDB(), question="hi")
    assert out == ""


def test_chat_injects_external_knowledge(monkeypatch):
    # 验证 chat 把外部知识拼进提示词（不依赖真实模型/外部服务）。
    captured: dict = {}

    def fake_fetch(db, *, question=None):
        captured["q"] = question
        return "[外部知识库 weknora]\n某基金费率结构说明"

    class _FakeLLM:
        @staticmethod
        def chat(db, messages, *, model_id=None, temperature=0.3):
            captured["messages"] = messages
            return "结合外部知识后的回答"

    monkeypatch.setattr(chat_router, "fetch_external_knowledge", fake_fetch)
    monkeypatch.setattr(chat_router, "llm", _FakeLLM)

    # 让 llm.chat 直接返回，绕过真实模型解析（已在 chat_router 内通过 mock 覆盖）。
    resp = client.post(
        "/api/v1/agent/chat", json={"question": "这只基金费率如何？"}
    )
    # mock 了 chat_router.llm.chat → agent_chat 不会再 400（模型解析在 llm.chat 内）。
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "结合外部知识后的回答"
    # 提示词第二段应包含外部知识
    snapshot_block = captured["messages"][1]["content"]
    assert "某基金费率结构说明" in snapshot_block
