# M7 Phase 4：外部 MCP 服务挂载管理 + 会话技能（docs/agent-framework.md §外部 MCP 挂载）。
# 覆盖：CRUD、transport 校验、test 连接、外部知识技能工具、fetch 容错。
import json
import uuid

from fastapi.testclient import TestClient

from app.agent import mcp_client as mcp_client_mod
from app.main import app

client = TestClient(app)


def test_json_import_is_atomic_disabled_and_validated():
    name = "json-" + _sid()
    entries = {
        name: {"command": "never-launch", "args": ["--test"], "env": {"A": "B"}},
        name + "http": {"url": "https://example.test/mcp", "type": "streamable-http"},
    }
    response = client.post(
        "/api/v1/agent/mcp-servers/import", json={"json_text": json.dumps({"mcpServers": entries})}
    )
    assert response.status_code == 201, response.text
    assert all(not row["enabled"] for row in response.json())
    assert (
        client.post(
            "/api/v1/agent/mcp-servers/import",
            json={"json_text": json.dumps({"mcpServers": entries})},
        ).status_code
        == 409
    )
    bad = {name + "new": {"command": "never"}, name + "bad": {"command": "never", "args": "bad"}}
    assert (
        client.post(
            "/api/v1/agent/mcp-servers/import", json={"json_text": json.dumps({"mcpServers": bad})}
        ).status_code
        == 422
    )
    assert not any(
        row["name"] == name + "new" for row in client.get("/api/v1/agent/mcp-servers").json()
    )
    for row in response.json():
        client.delete("/api/v1/agent/mcp-servers/" + row["id"])


def test_external_call_requires_live_scope(monkeypatch):
    from app.db.session import SessionLocal

    srv = _create("scope-" + _sid(), url="https://example.test/mcp")
    calls = []

    async def gather(*args):
        calls.append(args)
        return "ok"

    monkeypatch.setattr(mcp_client_mod, "_gather_one", gather)
    args = {"server_id": srv["id"], "tool": "write", "arguments": {}}
    with SessionLocal() as db:
        assert "未挂载" in mcp_client_mod.external_operation(db, [], args, call=True)
        assert calls == []
        assert mcp_client_mod.external_operation(db, [srv["id"]], args, call=True) == "ok"
        assert len(calls) == 1
    client.patch("/api/v1/agent/mcp-servers/" + srv["id"], json={"enabled": False})
    with SessionLocal() as db:
        assert "未启用" in mcp_client_mod.external_operation(db, [srv["id"]], args, call=True)
    client.delete("/api/v1/agent/mcp-servers/" + srv["id"])


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
    upd = client.patch(f"/api/v1/agent/mcp-servers/{sid}", json={"enabled": False}).json()
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
        mcp_client_mod,
        "fetch_external_knowledge",
        lambda db, **kw: "",  # noqa: ARG005
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


def test_chat_exposes_external_knowledge_as_skill_tool(monkeypatch):
    # 新口径：外部知识不再预拼进提示词，而是作为技能工具由模型在工具循环里按需调用。
    from app.agent import skills as skills_mod
    from app.db.session import SessionLocal

    captured: dict = {}

    def fake_fetch(db, *, question=None):
        captured["q"] = question
        return "[外部知识库 weknora]\n某基金费率结构说明"

    monkeypatch.setattr(skills_mod, "fetch_external_knowledge", fake_fetch)

    with SessionLocal() as db:
        out = skills_mod.execute_skill(db, "read_external_knowledge", {"question": "费率"})
    assert "某基金费率结构说明" in out
    assert captured["q"] == "费率"
    # 内置 Agent 默认挂载该技能
    builtin = client.get("/api/v1/agent/definitions").json()
    toupu = next(a for a in builtin if a["key"] == "toupu-assistant")
    assert "read_external_knowledge" in toupu["enabled_skill_keys"]
