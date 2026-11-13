# Agent API：Token 管理（用户侧）+ 只读查询网关 + 待审批提案（docs/risk-agent-rules.md §7/§8/§9）。
# 安全边界：/api/v1/agent 下除 POST /proposals 外只有 GET；无 /post /confirm /reverse。
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.agent.security import (
    VALID_SCOPES,
    Meta,
    generate_token,
    hash_token,
    log_success,
    meta,
    require_scope,
)
from app.audit import record_audit
from app.core.errors import BusinessError
from app.db.session import get_db
from app.market_data.models import FundNav, MarketQuote
from app.performance.service import derive
from app.plans.proposal_service import validate_payload
from app.risk.models import (
    AgentToken,
    InvestmentPlan,
    OperationProposal,
    RiskEvent,
)
from app.transactions.models import InvestmentTransaction

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _jsonable(value: Any) -> Any:
    """把 ORM/Decimal/UUID/date 递归转成 JSON 可序列化结构（金额一律字符串，禁 float）。"""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _rows(rows: list[Any], columns: list[str]) -> list[dict]:
    return [{col: _jsonable(getattr(row, col)) for col in columns} for row in rows]


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
    meta: Meta


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


# ---------- 只读查询网关 ----------


def _gate(x_agent_token: str | None, scope: str, resource: str, db: Session) -> AgentToken:
    token = require_scope(x_agent_token, scope, resource, db)
    log_success(db, token, resource, scope)
    return token


@router.get("/accounts", response_model=GatewayOut)
def agent_accounts(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    _gate(x_agent_token, "read:accounts", "accounts", db)
    rows = db.execute(select(InvestmentAccount).order_by(InvestmentAccount.name)).scalars().all()
    columns = ["id", "name", "account_type", "currency", "status", "notes"]
    return GatewayOut(data=_rows(list(rows), columns), meta=meta(str(date.today()), "ledger"))


@router.get("/positions", response_model=GatewayOut)
def agent_positions(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    from app.positions.router import list_positions

    _gate(x_agent_token, "read:positions", "positions", db)
    positions = list_positions(None, db)
    data = [
        {
            "account_id": str(p.account_id),
            "instrument_id": str(p.instrument_id),
            "instrument_code": p.instrument_code,
            "instrument_name": p.instrument_name,
            "instrument_type": p.instrument_type,
            "quantity": format(p.quantity, "f"),
            "total_cost": format(p.total_cost, "f"),
            "unit_cost": format(p.unit_cost, "f"),
        }
        for p in positions
    ]
    return GatewayOut(data=data, meta=meta(str(date.today()), "ledger"))


@router.get("/transactions", response_model=GatewayOut)
def agent_transactions(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    _gate(x_agent_token, "read:transactions", "transactions", db)
    rows = (
        db.execute(
            select(InvestmentTransaction)
            .order_by(InvestmentTransaction.business_date.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    columns = [
        "id",
        "account_id",
        "counter_account_id",
        "instrument_id",
        "transaction_type",
        "status",
        "confirmation_status",
        "business_date",
        "currency",
        "total_amount",
        "memo",
        "reversal_of_id",
    ]
    return GatewayOut(data=_rows(list(rows), columns), meta=meta(str(date.today()), "ledger"))


@router.get("/quotes", response_model=GatewayOut)
def agent_quotes(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    _gate(x_agent_token, "read:market", "quotes", db)
    quotes = db.execute(select(MarketQuote).limit(100)).scalars().all()
    navs = db.execute(select(FundNav).limit(100)).scalars().all()
    data = _rows(
        list(quotes),
        [
            "id",
            "instrument_id",
            "quote_date",
            "provider",
            "data_type",
            "price",
            "quality_status",
            "delayed",
            "created_at",
        ],
    )
    for row, q in zip(data, quotes, strict=False):
        row["kind"] = "quote"
        row["is_delayed"] = q.delayed
    nav_data = _rows(
        list(navs),
        [
            "id",
            "instrument_id",
            "nav_date",
            "provider",
            "data_type",
            "nav",
            "quality_status",
            "created_at",
        ],
    )
    for row in nav_data:
        row["kind"] = "nav"
        row["is_delayed"] = False
    delayed = any(q.delayed for q in quotes)
    return GatewayOut(
        data=data + nav_data,
        meta=meta(str(date.today()), "manual-quotes", is_delayed=delayed),
    )


@router.get("/valuation", response_model=GatewayOut)
def agent_valuation(
    as_of: date | None = None,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> GatewayOut:
    _gate(x_agent_token, "read:market", "valuation", db)
    as_of = as_of or date.today()
    try:
        derived = derive(db, as_of)
    except ValueError as exc:
        raise BusinessError(str(exc)) from None
    missing = [f"{p.instrument.code} ({p.quote.status})" for p in derived.positions if not p.valued]
    has_estimate = any(p.quote.status == "ESTIMATED" for p in derived.positions)
    rows = [
        {
            "account_id": str(p.account_id),
            "instrument_code": p.instrument.code,
            "instrument_name": p.instrument.name,
            "quantity": format(p.quantity, "f"),
            "book_cost": format(p.book_cost, "f"),
            "quote_status": p.quote.status,
            "quote_price": format(p.quote.price, "f") if p.quote.price is not None else None,
            "market_value": format(p.market_value, "f") if p.market_value is not None else None,
            "unrealized": format(p.unrealized, "f") if p.unrealized is not None else None,
        }
        for p in derived.positions
    ]
    return GatewayOut(
        data=rows,
        meta=meta(str(as_of), "valuation", is_estimate=has_estimate, missing=missing),
    )


@router.get("/summary", response_model=GatewayOut)
def agent_summary(
    as_of: date | None = None,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> GatewayOut:
    _gate(x_agent_token, "read:performance", "summary", db)
    as_of = as_of or date.today()
    try:
        derived = derive(db, as_of)
    except ValueError as exc:
        raise BusinessError(str(exc)) from None
    data = [
        {
            "as_of": str(as_of),
            "cash_total": format(derived.cash_total, "f"),
            "market_value": format(derived.market_value, "f"),
            "total_assets": format(derived.total_assets, "f"),
            "realized_total": format(derived.realized_total, "f"),
            "dividend_income": format(derived.dividend_income, "f"),
            "unrealized_total": format(derived.unrealized_total, "f"),
            "coverage": format(derived.coverage, "f"),
            "data_quality": derived.data_quality,
        }
    ]
    return GatewayOut(data=data, meta=meta(str(as_of), "valuation"))


@router.get("/returns", response_model=GatewayOut)
def agent_returns(
    as_of: date | None = None,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> GatewayOut:
    from app.performance.router import returns

    _gate(x_agent_token, "read:performance", "returns", db)
    as_of = as_of or date.today()
    result = returns(as_of, 7, db)
    data = [
        {
            "metric": name,
            "status": getattr(result, name).status,
            "value": (
                format(getattr(result, name).value, "f")
                if getattr(result, name).value is not None
                else None
            ),
            "reason": getattr(result, name).reason,
        }
        for name in ("xirr", "twr", "max_drawdown")
    ]
    missing = [str(d) for d in result.twr.missing]
    return GatewayOut(data=data, meta=meta(str(as_of), "snapshots", missing=missing))


@router.get("/risk-events", response_model=GatewayOut)
def agent_risk_events(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    _gate(x_agent_token, "read:risk", "risk-events", db)
    rows = (
        db.execute(select(RiskEvent).order_by(RiskEvent.triggered_at.desc()).limit(100))
        .scalars()
        .all()
    )
    columns = [
        "id",
        "rule_id",
        "as_of",
        "scope",
        "subject",
        "rule_type",
        "severity",
        "trigger_value",
        "threshold",
        "message",
        "status",
        "triggered_at",
    ]
    return GatewayOut(data=_rows(list(rows), columns), meta=meta(str(date.today()), "risk-rules"))


@router.get("/plans", response_model=GatewayOut)
def agent_plans(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    _gate(x_agent_token, "read:plans", "plans", db)
    rows = db.execute(select(InvestmentPlan).limit(100)).scalars().all()
    columns = ["id", "name", "description", "status", "target_amount", "created_at"]
    return GatewayOut(data=_rows(list(rows), columns), meta=meta(str(date.today()), "ledger"))


@router.get("/proposals", response_model=GatewayOut)
def agent_proposals(
    x_agent_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> GatewayOut:
    _gate(x_agent_token, "read:proposals", "proposals", db)
    rows = (
        db.execute(
            select(OperationProposal).order_by(OperationProposal.created_at.desc()).limit(100)
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    data = [_proposal_out(row, now).model_dump(mode="json") for row in rows]
    return GatewayOut(data=data, meta=meta(str(date.today()), "proposals"))


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
