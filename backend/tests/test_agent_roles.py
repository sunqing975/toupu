"""Operator cannot regain investment-analysis tools through old bindings."""

from sqlalchemy import select

from app.agent import skills
from app.agent.chat_router import _tool_executor, _tool_schemas
from app.agent.definitions_router import ensure_builtin
from app.agent.models import AgentDefinition
from app.agent.roles import OPERATOR_PROMPT, operator_tools
from app.db.session import SessionLocal


def test_operator_policy_and_runtime_filter():
    assert "不是投资分析师" in OPERATOR_PROMPT
    assert "create_account" in operator_tools(skills.SKILLS)
    assert "read_positions" in operator_tools(skills.SKILLS)
    with SessionLocal() as db:
        ensure_builtin(db)
        agent = db.scalar(select(AgentDefinition).where(AgentDefinition.key == "toupu-assistant"))
        original = list(agent.enabled_skill_keys)
        agent.enabled_skill_keys = original + ["draft_rebalance_plan"]
        db.flush()
        names = {s["function"]["name"] for s in _tool_schemas(db, agent)}
        assert "draft_rebalance_plan" not in names
        assert "create_account" in names
        assert "授权范围" in _tool_executor(db, agent.id)("draft_rebalance_plan", "{}")
        db.rollback()
