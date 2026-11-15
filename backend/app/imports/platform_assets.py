"""Reported observations are evidence, never transactions, net values or ledger positions."""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.audit import record_audit
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/platform-assets", tags=["platform-assets"])
Money = Decimal


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["FUND", "ADVISORY", "STOCK", "ETF"]
    code: str | None = Field(default=None, min_length=1, max_length=20)
    market_value: Money = Field(ge=0, max_digits=20, decimal_places=2)
    holding_pnl: Money = Field(max_digits=20, decimal_places=2)
    cumulative_pnl: Money | None = Field(default=None, max_digits=20, decimal_places=2)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    valuation_date: date | None = None


class PendingIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=20)
    amount: Money = Field(gt=0, max_digits=20, decimal_places=2)
    expected_confirmation_date: date
    note: str = Field(default="平台显示待确认，不计入已确认持仓", max_length=300)


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    account_id: uuid.UUID
    observed_on: date
    source: str = Field(min_length=1, max_length=200)
    request_key: str = Field(min_length=1, max_length=100)
    items: list[AssetIn] = Field(min_length=1, max_length=500)
    pending: list[PendingIn] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_observation(self):
        if self.observed_on > datetime.now(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("观察日期不能在未来")
        keys = [(i.kind, i.code or i.name) for i in self.items]
        if len(set(keys)) != len(keys) or len({i.name for i in self.items}) != len(self.items):
            raise ValueError("同一快照不能重复录入资产")
        for item in self.items:
            if item.kind == "ADVISORY" and (item.code or item.quantity):
                raise ValueError("投顾组合不伪造基金代码或份额；底层持仓另行核对")
            if item.valuation_date and item.valuation_date > self.observed_on:
                raise ValueError("估值日期不能晚于观察日期")
        return self


def batch_detail(db: Session, batch_id: uuid.UUID) -> dict:
    batch = (
        db.execute(text("SELECT * FROM platform_asset_batches WHERE id=:id"), {"id": batch_id})
        .mappings()
        .one()
    )
    rows = (
        db.execute(
            text("SELECT * FROM platform_asset_items WHERE batch_id=:id ORDER BY name"),
            {"id": batch_id},
        )
        .mappings()
        .all()
    )
    items = []
    for r in rows:
        item = dict(r)
        for key in ("market_value", "holding_pnl", "cumulative_pnl", "quantity"):
            item[key] = str(r[key]) if r[key] is not None else None
        item["reference_cost"] = str(r["market_value"] - r["holding_pnl"])
        reconstruction = db.execute(
            text("""SELECT h.result FROM fund_history_imports h
            JOIN instruments i ON i.id=h.instrument_id
            WHERE h.account_id=:account AND i.code=:code"""),
            {"account": batch["account_id"], "code": r["code"]},
        ).scalar()
        item["status"] = "HISTORY_POSTED" if reconstruction else "PLATFORM_REPORTED_NOT_POSTED"
        item["reconstructed_quantity"] = reconstruction["quantity"] if reconstruction else None
        if r["kind"] == "ADVISORY":
            from app.funds.advisory import portfolio_summary

            item["advisory"] = portfolio_summary(
                db, batch["account_id"], r["name"], batch["observed_on"], r["market_value"]
            )
        items.append(item)
    return {
        "id": batch["id"],
        "account_id": batch["account_id"],
        "observed_on": batch["observed_on"],
        "source": batch["source"],
        "items": items,
        "pending": batch["payload"].get("pending", []),
        "market_value": str(sum((r["market_value"] for r in rows), Decimal(0))),
        "holding_pnl": str(sum((r["holding_pnl"] for r in rows), Decimal(0))),
        "ledger_included": False,
        "warning": "仅平台观察值，未入账；不得与账本持仓相加。参考成本按金额减持有收益推算。",
    }


def save_batch(db: Session, payload: BatchIn) -> dict:
    data = payload.model_dump(mode="json")
    existing = (
        db.execute(
            text("SELECT id,payload FROM platform_asset_batches WHERE request_key=:key"),
            {"key": payload.request_key},
        )
        .mappings()
        .first()
    )
    if existing:
        if existing["payload"] != data:
            raise HTTPException(409, "同一请求标识不能用于不同数据")
        return batch_detail(db, existing["id"])
    account = db.get(InvestmentAccount, payload.account_id)
    if not account or account.status != "ACTIVE" or account.currency != "CNY":
        raise HTTPException(422, "需要有效的人民币投资账户")
    allowed = (
        {"FUND", "ADVISORY"}
        if account.account_type == "FUND_PLATFORM"
        else {"STOCK", "ETF", "FUND"}
    )
    if any(item.kind not in allowed for item in payload.items):
        raise HTTPException(422, "资产类型与账户类型不匹配")
    codes = {item.code for item in payload.items if item.code}
    if any(p.code not in codes for p in payload.pending):
        raise HTTPException(422, "待确认事项必须关联本批资产代码")
    batch_id = uuid.uuid4()
    try:
        db.execute(
            text("""INSERT INTO platform_asset_batches
            (id,account_id,observed_on,source,request_key,payload)
            VALUES (:id,:account,:day,:source,:key,CAST(:payload AS jsonb))"""),
            {
                "id": batch_id,
                "account": payload.account_id,
                "day": payload.observed_on,
                "source": payload.source,
                "key": payload.request_key,
                "payload": json.dumps(data),
            },
        )
        for item in payload.items:
            db.execute(
                text("""INSERT INTO platform_asset_items
                (id,batch_id,name,kind,code,market_value,holding_pnl,cumulative_pnl,quantity,valuation_date)
                VALUES (:id,:batch_id,:name,:kind,:code,:market_value,:holding_pnl,
                        :cumulative_pnl,:quantity,:valuation_date)"""),
                {**item.model_dump(), "id": uuid.uuid4(), "batch_id": batch_id},
            )
        record_audit(
            db,
            "SAVE_PLATFORM_ASSETS",
            "platform_assets",
            str(batch_id),
            {"source": payload.source, "items": len(payload.items), "ledger_included": False},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "同账户同日期快照或请求标识已存在，不重复导入") from None
    return batch_detail(db, batch_id)


@router.post("", status_code=201)
def create(payload: BatchIn, db: Session = Depends(get_db)) -> dict:
    return save_batch(db, payload)


@router.get("")
def latest(db: Session = Depends(get_db)) -> list[dict]:
    # One observation per account; historical observations are not added together.
    ids = db.execute(
        text("""SELECT DISTINCT ON (account_id) id
        FROM platform_asset_batches ORDER BY account_id, observed_on DESC, created_at DESC""")
    ).scalars()
    return [batch_detail(db, bid) for bid in ids.all()]
