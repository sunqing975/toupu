# Agent 只读资源：把 /api/v1/agent 的各 GET 端点抽成与传输层无关的函数，
# 供 REST 网关与 MCP server 共用（docs/agent-skill.md §5 / docs/risk-agent-rules.md §8）。
# 每个函数返回 (data:list[dict], meta:Meta)。金额一律字符串，禁 float。
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.agent.security import Meta, meta
from app.core.errors import BusinessError
from app.market_data.models import FundNav, MarketQuote
from app.performance.service import derive
from app.risk.models import InvestmentPlan, RiskEvent
from app.transactions.models import InvestmentTransaction


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _rows(rows: list[Any], columns: list[str]) -> list[dict]:
    return [{col: _jsonable(getattr(row, col)) for col in columns} for row in rows]


def accounts(db: Session) -> tuple[list[dict], Meta]:
    rows = db.execute(select(InvestmentAccount).order_by(InvestmentAccount.name)).scalars().all()
    data = _rows(list(rows), ["id", "name", "account_type", "currency", "status", "notes"])
    return data, meta(str(date.today()), "ledger")


def positions(db: Session) -> tuple[list[dict], Meta]:
    from app.positions.router import list_positions

    out = list_positions(None, db)
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
        for p in out
    ]
    return data, meta(str(date.today()), "ledger")


def transactions(db: Session) -> tuple[list[dict], Meta]:
    rows = (
        db.execute(
            select(InvestmentTransaction)
            .order_by(InvestmentTransaction.business_date.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    data = _rows(
        list(rows),
        [
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
        ],
    )
    return data, meta(str(date.today()), "ledger")


def quotes(db: Session) -> tuple[list[dict], Meta]:
    q_rows = db.execute(select(MarketQuote).limit(100)).scalars().all()
    nav_rows = db.execute(select(FundNav).limit(100)).scalars().all()
    data = _rows(
        list(q_rows),
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
    for row, _q in zip(data, q_rows, strict=False):
        row["kind"] = "quote"
    nav_data = _rows(
        list(nav_rows),
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
    delayed = any(q.delayed for q in q_rows)
    return data + nav_data, meta(str(date.today()), "manual-quotes", is_delayed=delayed)


def valuation(db: Session, as_of: date | None = None) -> tuple[list[dict], Meta]:
    as_of = as_of or date.today()
    try:
        derived = derive(db, as_of)
    except ValueError as exc:
        raise BusinessError(str(exc)) from None
    missing = [f"{p.instrument.code} ({p.quote.status})" for p in derived.positions if not p.valued]
    has_estimate = any(p.quote.status == "ESTIMATED" for p in derived.positions)
    data = [
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
    return data, meta(str(as_of), "valuation", is_estimate=has_estimate, missing=missing)


def summary(db: Session, as_of: date | None = None) -> tuple[list[dict], Meta]:
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
    return data, meta(str(as_of), "valuation")


def returns(db: Session, as_of: date | None = None) -> tuple[list[dict], Meta]:
    from app.performance.router import returns as _returns

    as_of = as_of or date.today()
    result = _returns(as_of, 7, db)
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
    return data, meta(str(as_of), "snapshots", missing=missing)


def risk_events(db: Session) -> tuple[list[dict], Meta]:
    rows = (
        db.execute(select(RiskEvent).order_by(RiskEvent.triggered_at.desc()).limit(100))
        .scalars()
        .all()
    )
    data = _rows(
        list(rows),
        [
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
        ],
    )
    return data, meta(str(date.today()), "risk-rules")


def plans(db: Session) -> tuple[list[dict], Meta]:
    rows = db.execute(select(InvestmentPlan).limit(100)).scalars().all()
    data = _rows(list(rows), ["id", "name", "description", "status", "target_amount", "created_at"])
    return data, meta(str(date.today()), "ledger")


def proposals(db: Session) -> tuple[list[dict], Meta]:
    from app.plans.router import _proposal_out
    from app.risk.models import OperationProposal

    rows = (
        db.execute(
            select(OperationProposal).order_by(OperationProposal.created_at.desc()).limit(100)
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    data = [_proposal_out(row, now).model_dump(mode="json") for row in rows]
    return data, meta(str(date.today()), "proposals")


# (resource, scope, callable) 清单 —— MCP server 与文档据此注册工具/资源。
RESOURCE_CATALOG: list[tuple[str, str, Any]] = [
    ("accounts", "read:accounts", accounts),
    ("positions", "read:positions", positions),
    ("transactions", "read:transactions", transactions),
    ("quotes", "read:market", quotes),
    ("valuation", "read:market", valuation),
    ("summary", "read:performance", summary),
    ("returns", "read:performance", returns),
    ("risk-events", "read:risk", risk_events),
    ("plans", "read:plans", plans),
    ("proposals", "read:proposals", proposals),
]
