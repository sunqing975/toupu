# Agent API：Token 管理（用户侧）+ 只读查询网关 + 待审批提案（docs/risk-agent-rules.md §7/§8/§9）。
# 安全边界：/api/v1/agent 下除 POST /proposals 外只有 GET；无 /post /confirm /reverse。
# 只读资源的查询逻辑抽到 app/agent/resources.py，供 REST 网关与 MCP server 共用。
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent.resources import (
    accounts,
    positions,
    proposals,
    quotes,
    returns,
    risk_events,
    summary,
    transactions,
    valuation,
)
from app.agent.resources import (
    plans as _plans,
)
from app.agent.security import (
    VALID_SCOPES,
    generate_token,
    hash_token,
    log_success,
    require_scope,
)
from app.audit import record_audit
from app.db.session import get_db
from app.plans.proposal_service import validate_payload
from app.risk.models import AgentToken, OperationProposal

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class TokenIn(BaseModel):
    name: str
    scopes: list[str]


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    scopes: list[str]
    active: bool
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class TokenCreated(BaseModel):
    token: str  # 明文只在本次响应返回一次
    id: uuid.UUID
    name: str
    scopes: list[str]


class GatewayOut(BaseModel):
    data: list[dict]
    meta: Any


class ProposalIn(BaseModel):
    proposal_type: str
    payload: dict
    expires_hours: int = Field(default=48, ge=1, le=720)


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    proposal_type: str
    status: str
    created_by: str
    payload: dict
    impact_preview: dict
    validation_snapshot: dict
    expires_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    resulting_transaction_id: uuid.UUID | None
    created_at: datetime
    is_expired: bool = False


def _proposal_out(proposal: OperationProposal, now: datetime | None = None) -> ProposalOut:
    out = ProposalOut.model_validate(proposal, from_attributes=True)
    out.is_expired = (
        proposal.status == "PENDING" and (now or datetime.now(UTC)) > proposal.expires_at
    )
    return out


# ---------- Token 管理（用户侧，不需要 X-Agent-Token） ----------


@router.post("/tokens", status_code=status.HTTP_201_CREATED, response_model=TokenCreated)
def create_token(payload: TokenIn, db: Session = Depends(get_db)) -> TokenCreated:
    scopes = payload.scopes
    if not scopes or len(set(scopes)) != len(scopes):
        raise HTTPException(status_code=422, detail="不允许的 scope")
    illegal = [s for s in scopes if s not in VALID_SCOPES]
    if illegal:
        raise HTTPException(status_code=422, detail="不允许的 scope")
    plain = generate_token()
    token = AgentToken(name=payload.name, token_hash=hash_token(plain), scopes=scopes)
    db.add(token)
    db.commit()
    db.refresh(token)
    record_audit(db, "agent.token.create", "agent_token", str(token.id), {"scopes": scopes})
    db.commit()
    return TokenCreated(token=plain, id=token.id, name=token.name, scopes=token.scopes)


@router.get("/tokens", response_model=list[TokenOut])
def list_tokens(db: Session = Depends(get_db)) -> list[AgentToken]:
    return list(db.query(AgentToken).order_by(AgentToken.created_at.desc()))


@router.post("/tokens/{token_id}/revoke", response_model=TokenOut)
def revoke_token(token_id: uuid.UUID, db: Session = Depends(get_db)) -> AgentToken:
    token = db.get(AgentToken, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Agent Token 不存在")
    token.active = False
    token.revoked_at = datetime.now(UTC)
    db.commit()
    db.refresh(token)
    record_audit(db, "agent.token.revoke", "agent_token", str(token_id))
    db.commit()
    return token


# ---------- 只读查询网关（委托 resources.py） ----------


def _gate(x_agent_token: str | None, scope: str, resource: str, db: Session) -> AgentToken:
    token = require_scope(x_agent_token, scope, resource, db)
    log_success(db, token, resource, scope)
    return token


def _gateway(
    x_agent_token: str | None, scope: str, resource: str, fetch, db: Session, *args
) -> GatewayOut:
    _gate(x_agent_token, scope, resource, db)
    data, meta_obj = fetch(db, *args)
    return GatewayOut(data=data, meta=meta_obj)


@router.get("/accounts", response_model=GatewayOut)
def agent_accounts(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    return _gateway(x_agent_token, "read:accounts", "accounts", accounts, db)


@router.get("/positions", response_model=GatewayOut)
def agent_positions(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    return _gateway(x_agent_token, "read:positions", "positions", positions, db)


@router.get("/transactions", response_model=GatewayOut)
def agent_transactions(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    return _gateway(x_agent_token, "read:transactions", "transactions", transactions, db)


@router.get("/quotes", response_model=GatewayOut)
def agent_quotes(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    return _gateway(x_agent_token, "read:market", "quotes", quotes, db)


@router.get("/valuation", response_model=GatewayOut)
def agent_valuation(
    as_of: date | None = None,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> GatewayOut:
    return _gateway(x_agent_token, "read:market", "valuation", valuation, db, as_of)


@router.get("/summary", response_model=GatewayOut)
def agent_summary(
    as_of: date | None = None,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> GatewayOut:
    return _gateway(x_agent_token, "read:performance", "summary", summary, db, as_of)


@router.get("/returns", response_model=GatewayOut)
def agent_returns(
    as_of: date | None = None,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> GatewayOut:
    return _gateway(x_agent_token, "read:performance", "returns", returns, db, as_of)


@router.get("/risk-events", response_model=GatewayOut)
def agent_risk_events(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    return _gateway(x_agent_token, "read:risk", "risk-events", risk_events, db)


@router.get("/plans", response_model=GatewayOut)
def agent_plans(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    return _gateway(x_agent_token, "read:plans", "plans", _plans, db)


@router.get("/proposals", response_model=GatewayOut)
def agent_proposals(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    return _gateway(x_agent_token, "read:proposals", "proposals", proposals, db)


# ---------- 提案创建（Agent 侧，唯一写端点：只建 PENDING） ----------


@router.post("/proposals", status_code=status.HTTP_201_CREATED, response_model=ProposalOut)
def create_proposal(
    payload: ProposalIn,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ProposalOut:
    token = require_scope(x_agent_token, "write:proposals", "proposals.create", db)
    log_success(db, token, "proposals.create", "write:proposals")
    if payload.proposal_type != "DRAFT_CASH_TRANSACTION":
        raise HTTPException(status_code=422, detail="不支持的 proposal_type")
    validated = validate_payload(db, payload.payload)
    now = datetime.now(UTC)
    proposal = OperationProposal(
        proposal_type=payload.proposal_type,
        status="PENDING",
        created_by=f"agent:{token.name}",
        payload=payload.payload,
        impact_preview=validated["impact"],
        validation_snapshot=validated["snapshot"],
        expires_at=now + timedelta(hours=payload.expires_hours),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    record_audit(
        db,
        "agent.proposal.create",
        "operation_proposal",
        str(proposal.id),
        {"proposal_type": payload.proposal_type},
    )
    db.commit()
    return _proposal_out(proposal, now)
