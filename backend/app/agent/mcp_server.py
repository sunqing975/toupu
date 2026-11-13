# Agent MCP 服务：对外暴露只读资源 + 待审批提案工具（docs/risk-agent-rules.md §8/§9）。
# 复用 resources.py 的只读资源函数与 security.require_scope；鉴权从 MCP 请求头
# X-Agent-Token 取（由 Starlette 中间件注入到 contextvar，供无参资源/工具读取）。
# 安全边界：除 create_proposal 外只有只读资源（无 /post /confirm /reverse），且工具调用
# 只生成 PENDING 提案，绝不入账。
from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from app.agent.resources import (
    accounts,
    plans,
    positions,
    proposals,
    quotes,
    returns,
    risk_events,
    summary,
    transactions,
    valuation,
)
from app.agent.security import require_scope
from app.db.session import get_db
from app.plans.proposal_service import validate_payload

try:  # FastMCP 是可选依赖，导入失败不影响主应用其余部分。
    from mcp.server.fastmcp import FastMCP as _FastMCP

    _HAVE_MCP = True
except Exception:  # noqa: BLE001
    _HAVE_MCP = False
    _FastMCP = None  # type: ignore[assignment, misc]


# 每个 MCP 请求的 Agent Token（由 AgentTokenMiddleware 注入）。
current_agent_token: ContextVar[str | None] = ContextVar("agent_token", default=None)

_INSTRUCTIONS = (
    "投谱 Toupu Agent 服务：只读查询账户/持仓/交易/行情/估值/收益/风险事件/投资计划/提案，"
    "并支持创建待审批的现金类交易提案（仅生成草稿，需用户在网页端审批后才入账）。"
    "所有写入必须经过用户确认，Agent 无法直接改动账本。"
)

# 资源清单：uri -> (scope, resource_label, fetch, with_as_of)
# fetch 签名：(db) 或 (db, as_of)。as_of=None 时资源函数回退到当天。
_READ_RESOURCES: list[tuple[str, str, str, Any, bool]] = [
    ("accounts", "read:accounts", "accounts", accounts, False),
    ("positions", "read:positions", "positions", positions, False),
    ("transactions", "read:transactions", "transactions", transactions, False),
    ("quotes", "read:market", "quotes", quotes, False),
    ("valuation", "read:market", "valuation", valuation, True),
    ("summary", "read:performance", "summary", summary, True),
    ("returns", "read:performance", "returns", returns, True),
    ("risk-events", "read:risk", "risk-events", risk_events, False),
    ("plans", "read:plans", "plans", plans, False),
    ("proposals", "read:proposals", "proposals", proposals, False),
]


def _utcnow():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _build_proposal(db: Session, payload: dict, validated: dict, now, expires_hours: int):
    from datetime import timedelta

    from app.audit import record_audit
    from app.risk.models import OperationProposal

    proposal = OperationProposal(
        proposal_type="DRAFT_CASH_TRANSACTION",
        status="PENDING",
        created_by="agent:mcp",
        payload=payload,
        impact_preview=validated["impact"],
        validation_snapshot=validated["snapshot"],
        expires_at=now + timedelta(hours=expires_hours),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    record_audit(
        db,
        "agent.proposal.create",
        "operation_proposal",
        str(proposal.id),
        {"proposal_type": "DRAFT_CASH_TRANSACTION", "via": "mcp"},
    )
    db.commit()
    return proposal


def build_mcp_server() -> _FastMCP | None:
    """构造 FastMCP 实例并注册无参资源/工具；无 MCP 依赖时返回 None。

    注意：FastMCP 的 streamable_http_app 自带 lifespan（启动 session_manager.run()），
    但 FastAPI/Starlette 的 Mount 不会触发被挂载子应用的 lifespan，因此由 app.main
    的 lifespan 显式运行 mcp_server.session_manager.run()（见 app.main.lifespan）。
    """
    if not _HAVE_MCP:
        return None

    mcp = _FastMCP("toupu-agent", instructions=_INSTRUCTIONS, streamable_http_path="/")

    for _uri, _scope, _label, _fetch, _with_as_of in _READ_RESOURCES:

        def _make(scope=_scope, label=_label, fetch=_fetch, with_as_of=_with_as_of):
            def _resource_fn() -> str:
                token = current_agent_token.get()
                db: Session = next(get_db())
                try:
                    require_scope(token, scope, label, db)
                    if with_as_of:
                        data, meta_obj = fetch(db, None)
                    else:
                        data, meta_obj = fetch(db)
                    return json.dumps(
                        {"data": data, "meta": meta_obj.model_dump()}, ensure_ascii=False
                    )
                finally:
                    db.close()

            return _resource_fn

        mcp.resource(
            f"toupu://data/{_uri}",
            name=f"read_{_uri}",
            description=f"只读查询 {_uri}",
            mime_type="application/json",
        )(_make())

    @mcp.tool(
        name="create_proposal",
        description="创建待审批的现金类交易提案（仅生成草稿，不入账）",
    )
    def create_proposal(
        transaction_type: str,
        account_id: str,
        amount: str,
        business_date: str,
        counter_account_id: str | None = None,
        expires_hours: int = 48,
    ) -> dict:
        """创建一笔现金类交易提案（DEPOSIT/WITHDRAW/ACCOUNT_TRANSFER）。

        Agent 只能创建待审批提案；用户在网页端审批后才会生成交易草稿并人工确认入账。
        """
        token = current_agent_token.get()
        db: Session = next(get_db())
        try:
            require_scope(token, "write:proposals", "proposals.create", db)
            payload = {
                "transaction_type": transaction_type,
                "account_id": account_id,
                "counter_account_id": counter_account_id,
                "amount": amount,
                "business_date": business_date,
            }
            validated = validate_payload(db, payload)
            now = _utcnow()
            proposal = _build_proposal(db, payload, validated, now, expires_hours)
            return {
                "id": str(proposal.id),
                "status": proposal.status,
                "impact_preview": proposal.impact_preview,
                "expires_at": proposal.expires_at.isoformat(),
            }
        finally:
            db.close()

    return mcp


# 模块级单例，供 main.py 挂载。
mcp_server: _FastMCP | None = build_mcp_server() if _HAVE_MCP else None


class AgentTokenMiddleware:
    """从请求头 X-Agent-Token 取出 Agent Token，注入到 current_agent_token。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            token = None
            for raw_key, raw_val in scope.get("headers") or []:
                if raw_key.lower() == b"x-agent-token":
                    token = raw_val.decode("latin-1")
                    break
            cv = current_agent_token.set(token)
            try:
                await self.app(scope, receive, send)
            finally:
                current_agent_token.reset(cv)
        else:
            await self.app(scope, receive, send)


def mount_mcp(app) -> bool:
    """把 MCP 的 Starlette 应用挂到主 app 的 /mcp 下；成功返回 True。

    FastMCP 的 streamable_http_app 自带 lifespan（启动 session_manager.run()），
    但 FastAPI/Starlette 的 Mount 不会触发被挂载子应用的 lifespan，因此由 app.main
    的 lifespan 在启动后显式运行 mcp_server.session_manager.run()。
    """
    if mcp_server is None:
        return False

    inner = mcp_server.streamable_http_app()
    inner.add_middleware(AgentTokenMiddleware)
    app.mount("/mcp", inner, name="mcp")
    return True
