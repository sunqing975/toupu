"""A portfolio-level cash-flow subledger; never invent underlying trades or quantities."""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.audit import record_audit
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/advisory", tags=["advisory"])


class FlowIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    external_id: str = Field(min_length=1, max_length=100)
    kind: Literal["CONTRIBUTION", "WITHDRAWAL", "FEE", "REFUND"]
    occurred_on: date
    confirmed_on: date | None = None
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    subsidy: Decimal = Field(default=Decimal(0), ge=0, max_digits=20, decimal_places=2)
    fee_scope: Literal["INTERNAL", "EXTERNAL", "UNKNOWN"] = "UNKNOWN"
    evidence: dict

    @model_validator(mode="after")
    def valid(self):
        if self.subsidy > self.amount or (self.kind != "CONTRIBUTION" and self.subsidy):
            raise ValueError("仅转入允许福利抵扣且不能超过金额")
        if self.confirmed_on and self.confirmed_on < self.occurred_on:
            raise ValueError("确认日期不能早于申请日期")
        if (
            max(self.occurred_on, self.confirmed_on or self.occurred_on)
            > datetime.now(ZoneInfo("Asia/Shanghai")).date()
        ):
            raise ValueError("不能录入未来流水")
        if not self.evidence:
            raise ValueError("需要来源证据")
        return self


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    account_id: uuid.UUID
    portfolio_name: str = Field(min_length=1, max_length=100)
    flows: list[FlowIn] = Field(min_length=1, max_length=500)


def save_flows(db: Session, payload: BatchIn) -> dict:
    account = db.scalar(
        select(InvestmentAccount)
        .where(InvestmentAccount.id == payload.account_id)
        .with_for_update()
    )
    if not account or account.account_type != "FUND_PLATFORM" or account.status != "ACTIVE":
        raise HTTPException(422, "需要有效的基金平台账户")
    exists = db.scalar(
        text("""SELECT count(*) FROM platform_asset_items i
        JOIN platform_asset_batches b ON b.id=i.batch_id
        WHERE b.account_id=:a AND i.name=:n AND i.kind='ADVISORY'"""),
        {"a": payload.account_id, "n": payload.portfolio_name},
    )
    if not exists:
        raise HTTPException(422, "请先建立该账户的投顾组合平台快照")
    if len({f.external_id for f in payload.flows}) != len(payload.flows):
        raise HTTPException(422, "同批流水标识重复")
    inserted = 0
    for flow in payload.flows:
        params = {"a": payload.account_id, "n": payload.portfolio_name, "key": flow.external_id}
        old = (
            db.execute(
                text("""SELECT * FROM advisory_flows
            WHERE account_id=:a AND portfolio_name=:n AND external_id=:key"""),
                params,
            )
            .mappings()
            .first()
        )
        if old:
            if any(old[k] != v for k, v in flow.model_dump().items()):
                raise HTTPException(409, "同一流水标识已有不同数据，不覆盖")
            continue
        d = flow.model_dump()
        d["evidence"] = json.dumps(d["evidence"], ensure_ascii=False)
        db.execute(
            text("""INSERT INTO advisory_flows
            (id,account_id,portfolio_name,external_id,kind,occurred_on,confirmed_on,
             amount,subsidy,fee_scope,evidence)
            VALUES (:id,:a,:n,:external_id,:kind,:occurred_on,:confirmed_on,
                    :amount,:subsidy,:fee_scope,CAST(:evidence AS jsonb))"""),
            {**d, "id": uuid.uuid4(), "a": payload.account_id, "n": payload.portfolio_name},
        )
        inserted += 1
    if inserted:
        record_audit(
            db,
            "SAVE_ADVISORY_FLOWS",
            "advisory",
            str(payload.account_id),
            {
                "portfolio": payload.portfolio_name,
                "inserted": inserted,
                "underlying_trades_required": False,
            },
        )
    db.flush()
    return {"inserted": inserted, "portfolio_name": payload.portfolio_name}


def portfolio_summary(
    db: Session, account_id, name: str, as_of: date, market_value: Decimal
) -> dict:
    rows = (
        db.execute(
            text("""SELECT * FROM advisory_flows WHERE account_id=:a
        AND portfolio_name=:n AND COALESCE(confirmed_on,occurred_on)<=:day
        ORDER BY occurred_on,external_id"""),
            {"a": account_id, "n": name, "day": as_of},
        )
        .mappings()
        .all()
    )

    def total(kind):
        return sum((r["amount"] for r in rows if r["kind"] == kind), Decimal(0))

    nominal = total("CONTRIBUTION")
    subsidy = sum((r["subsidy"] for r in rows), Decimal(0))
    withdrawals = total("WITHDRAWAL")
    refunds = total("REFUND")
    external_fee = sum(
        (r["amount"] for r in rows if r["kind"] == "FEE" and r["fee_scope"] == "EXTERNAL"),
        Decimal(0),
    )
    unknown_fee = sum(
        (r["amount"] for r in rows if r["kind"] == "FEE" and r["fee_scope"] == "UNKNOWN"),
        Decimal(0),
    )
    return {
        "flow_count": len(rows),
        "nominal_contributions": str(nominal),
        "personal_contributions": str(nominal - subsidy),
        "subsidy": str(subsidy),
        "withdrawals": str(withdrawals),
        "refunds": str(refunds),
        "external_fees": str(external_fee),
        "unknown_fees": str(unknown_fee),
        "nominal_pnl": str(market_value + withdrawals + refunds - nominal - external_fee)
        if rows
        else None,
        "personal_pnl": str(
            market_value + withdrawals + refunds - (nominal - subsidy) - external_fee
        )
        if rows
        else None,
        "fees_deducted_again": False,
        "underlying_trades_required": False,
        "flows": [
            {k: str(v) if isinstance(v, (Decimal, uuid.UUID, date)) else v for k, v in r.items()}
            for r in rows
        ],
        "warning": (
            "组合整体资金流水；内部费用已含平台市值，不再次扣除；"
            "来源未知费用只作明细。收益以已录完整流水为前提。"
        ),
    }


@router.post("/flows", status_code=201)
def create(payload: BatchIn, db: Session = Depends(get_db)) -> dict:
    try:
        result = save_flows(db, payload)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
