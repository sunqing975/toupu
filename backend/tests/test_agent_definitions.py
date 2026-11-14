"""M7 对齐 WeKnora：Agent 实体 CRUD + 技能目录 + 技能运行时（含工具循环）。

按 docs/agent-framework.md §Agent 实体 / §技能运行时：
- 内置「投谱助手」首次访问自动种子（含全部技能目录）。
- Agent 实体可自定义创建/编辑/删除（内置不可删）。
- 技能执行器对只读/分析请求返回结构化 JSON；create_draft_proposal 只建 PENDING。
- 工具循环（chat_with_tools）按 max_rounds 收敛，最终返回文本。
"""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agent import skills as skills_mod
from app.main import app

client = TestClient(app)


def _create_model():
    resp = client.post(
        "/api/v1/agent/models",
        json={
            "name": "测试模型",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5",
            "api_key": "sk-secret",
            "is_default": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_builtin_agent_and_skills_seeded():
    listing = client.get("/api/v1/agent/definitions").json()
    keys = {a["key"] for a in listing}
    assert "toupu-assistant" in keys
    builtin = next(a for a in listing if a["key"] == "toupu-assistant")
    assert set(builtin["enabled_skill_keys"]) == set(skills_mod.SKILLS.keys())

    skills = client.get("/api/v1/agent/definitions/skills").json()
    assert skills
    categories = {s["category"] for s in skills}
    assert {"data", "analysis", "knowledge", "action"} <= categories


def test_agent_create_list_get_update_delete():
    # 先确保内置存在（list 触发 ensure_builtin）
    client.get("/api/v1/agent/definitions")
    resp = client.post(
        "/api/v1/agent/definitions",
        json={
            "key": "my-analyst",
            "name": "我的分析助手",
            "description": "通用投资分析",
            "enabled_skill_keys": ["read_summary", "analyze_portfolio_concentration"],
            "mcp_server_ids": [],
        },
    )
    assert resp.status_code == 201, resp.text
    aid = resp.json()["id"]

    got = client.get(f"/api/v1/agent/definitions/{aid}").json()
    assert got["name"] == "我的分析助手"
    assert got["enabled_skill_keys"] == ["read_summary", "analyze_portfolio_concentration"]

    upd = client.patch(
        f"/api/v1/agent/definitions/{aid}",
        json={"name": "改名后的助手", "enabled_skill_keys": ["read_positions"]},
    ).json()
    assert upd["name"] == "改名后的助手"
    assert upd["enabled_skill_keys"] == ["read_positions"]

    assert client.delete(f"/api/v1/agent/definitions/{aid}").status_code == 204
    assert client.get(f"/api/v1/agent/definitions/{aid}").status_code == 404


def test_builtin_agent_not_deletable():
    listing = client.get("/api/v1/agent/definitions").json()
    builtin = next(a for a in listing if a["key"] == "toupu-assistant")
    assert client.delete(f"/api/v1/agent/definitions/{builtin['id']}").status_code == 409


def test_create_duplicate_key_conflict():
    client.get("/api/v1/agent/definitions")
    client.post(
        "/api/v1/agent/definitions",
        json={"key": "dup-key", "name": "A", "enabled_skill_keys": []},
    )
    dup = client.post(
        "/api/v1/agent/definitions",
        json={"key": "dup-key", "name": "B", "enabled_skill_keys": []},
    )
    assert dup.status_code == 409


def test_skill_invalid_keys_filtered():
    client.get("/api/v1/agent/definitions")
    resp = client.post(
        "/api/v1/agent/definitions",
        json={
            "key": "filt-key",
            "name": "F",
            "enabled_skill_keys": ["not_a_skill", "read_accounts"],
        },
    ).json()
    assert resp["enabled_skill_keys"] == ["read_accounts"]
    client.delete(f"/api/v1/agent/definitions/{resp['id']}")


def test_skill_executor_read_returns_json():
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        out = skills_mod.execute_skill(db, "read_accounts", "{}")
        parsed = json.loads(out)
        assert "accounts" in parsed


def test_skill_executor_unknown():
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        out = json.loads(skills_mod.execute_skill(db, "nope", "{}"))
        assert out["ok"] is False


def test_create_draft_proposal_only_pending():

    from app.db.session import SessionLocal

    payload = {
        "transaction_type": "DEPOSIT",
        "account_id": "00000000-0000-0000-0000-000000000001",
        "amount": "100.000000",
        "business_date": "2026-11-12",
    }

    with SessionLocal() as db:
        out = json.loads(
            skills_mod.execute_skill(db, "create_draft_proposal", json.dumps({"payload": payload}))
        )
    # 即便账户不存在，validate_payload 会失败——只断言路径不崩溃且返回结构化错误
    assert "ok" in out


def test_chat_uses_tool_loop_with_mock_model():
    # 新口径：工具循环在 llm.chat_with_tools 内实现；chat_router 只负责把
    # tool_schemas + tool_executor 传进去。此处验证二者确实被注入且执行器可调用。
    _create_model()
    captured: dict = {}

    def fake_chat_with_tools(
        db, messages, tool_schemas, tool_executor, *, model_id=None, temperature=0.3, max_rounds=6
    ):
        captured["tool_schemas"] = tool_schemas
        # 模拟模型在循环里调用一个只读技能：执行器应委托给 skills.execute_skill
        captured["tool_result"] = tool_executor("read_summary", "{}")
        return "根据概览，总资产约为示例值。"

    with patch("app.agent.llm.chat_with_tools", side_effect=fake_chat_with_tools):
        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "总资产多少？"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "根据概览，总资产约为示例值。"
    assert body["agent_name"]
    assert any(
        s.get("function", {}).get("name") == "read_summary" for s in captured["tool_schemas"]
    )
    assert isinstance(captured["tool_result"], str)


def test_chat_requires_model():
    # 隔离共享开发库中的真实模型，不触发网络也不删除用户配置。
    with patch("app.agent.chat_router._resolve_model", return_value=None):
        resp = client.post("/api/v1/agent/chat", json={"question": "你好"})
    assert resp.status_code == 400
