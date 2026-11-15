"""Local metadata writes remain separate from financial posting."""

import json
import uuid
from unittest.mock import patch

from sqlalchemy import func, select, text

from app.accounts.models import InvestmentAccount
from app.agent import skills
from app.agent.chat_router import _tool_executor
from app.agent.definitions_router import ensure_builtin
from app.agent.models import AgentDefinition
from app.audit import AuditLog
from app.db.session import SessionLocal


def test_create_account_tool_replay_and_validation():
    with SessionLocal() as db:
        name = f"tool-{uuid.uuid4().hex}"
        before = db.scalar(text("SELECT count(*) FROM investment_transactions"))
        args = {"name": f"  {name}  ", "account_type": "BROKER"}
        result = json.loads(skills.execute_skill(db, "create_account", args))
        assert result["ok"] and result["created"]
        assert result["account"]["name"] == name
        assert result["account"]["status"] == "ACTIVE"
        again = json.loads(skills.execute_skill(db, "create_account", args))
        assert again["ok"] and not again["created"]
        assert again["account"]["id"] == result["account"]["id"]
        conflict = json.loads(
            skills.execute_skill(
                db, "create_account", {"name": name, "account_type": "FUND_PLATFORM"}
            )
        )
        assert not conflict["ok"]
        for invalid in (
            {"name": " "},
            {"name": "bad", "account_type": "BANK"},
            {"name": "bad", "account_type": "BROKER", "balance": "100"},
        ):
            assert not json.loads(skills.execute_skill(db, "create_account", invalid))["ok"]
        assert db.scalar(text("SELECT count(*) FROM investment_transactions")) == before
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "CREATE_ACCOUNT",
                    AuditLog.entity_id == result["account"]["id"],
                )
            )
            == 1
        )


def test_create_account_audit_failure_rolls_back():
    name = f"rollback-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        with patch("app.accounts.service.record_audit", side_effect=RuntimeError("audit failed")):
            result = json.loads(
                skills.execute_skill(db, "create_account", {"name": name, "account_type": "BROKER"})
            )
        assert not result["ok"]
        db.commit()
        assert db.scalar(select(InvestmentAccount).where(InvestmentAccount.name == name)) is None


def test_account_tool_respects_live_agent_binding():
    with SessionLocal() as db:
        ensure_builtin(db)
        agent = AgentDefinition(
            key=f"no-write-{uuid.uuid4().hex}",
            name="no write",
            enabled_skill_keys=["read_accounts"],
            mcp_server_ids=[],
        )
        db.add(agent)
        db.commit()
        result = _tool_executor(db, agent.id)("create_account", "{}")
        assert "授权范围" in result
