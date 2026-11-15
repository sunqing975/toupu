"""User-confirmed historical reconstruction. Caller owns the single commit."""

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.audit import record_audit
from app.core.errors import BusinessError
from app.funds.models import FundConfirmation, FundOrderDetail
from app.instruments.models import Instrument
from app.ledger.service import post_transaction
from app.opening_balances.models import OpeningBalanceDetail
from app.positions.service import PositionLot
from app.transactions.models import InvestmentTransaction


class HistoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=80)
    kind: Literal["SUBSCRIBE", "REDEEM", "CONVERSION_BOUNDARY"]
    posting_date: date
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    shares: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    nav: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    fee: Decimal = Field(default=Decimal(0), ge=0, max_digits=20, decimal_places=6)
    evidence: dict

    @model_validator(mode="after")
    def check(self):
        if self.amount <= self.fee:
            raise ValueError("金额必须大于手续费")
        if not self.evidence.get("source_image"):
            raise ValueError("必须保留截图来源")
        return self


class HistoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    request_key: str = Field(min_length=1, max_length=100)
    user_confirmed: Literal[True]
    expected_shares: Decimal = Field(gt=0)
    rows: list[HistoryRow] = Field(min_length=1, max_length=1000)


def import_history(db: Session, payload: HistoryIn) -> dict:
    data = payload.model_dump(mode="json")
    # Lock account so separate request keys cannot race to reconstruct the same position.
    account = db.scalar(
        select(InvestmentAccount)
        .where(InvestmentAccount.id == payload.account_id)
        .with_for_update()
    )
    if not account or account.account_type != "FUND_PLATFORM" or account.status != "ACTIVE":
        raise BusinessError("需要有效的基金平台账户")
    old = (
        db.execute(
            text("""SELECT payload,result FROM fund_history_imports
        WHERE account_id=:a AND instrument_id=:i"""),
            {"a": payload.account_id, "i": payload.instrument_id},
        )
        .mappings()
        .first()
    )
    if old:
        if old["payload"] != data:
            raise BusinessError("该基金已有历史重建记录，不能重复或变更导入")
        return old["result"]
    instrument = db.get(Instrument, payload.instrument_id)
    if not instrument or instrument.instrument_type != "FUND" or instrument.currency != "CNY":
        raise BusinessError("需要有效的人民币场外基金")
    if db.scalar(
        select(InvestmentTransaction.id)
        .where(
            InvestmentTransaction.account_id == account.id,
            InvestmentTransaction.instrument_id == instrument.id,
        )
        .limit(1)
    ):
        raise BusinessError("基金已有交易，禁止重叠重建")
    if len({r.order_id for r in payload.rows}) != len(payload.rows):
        raise BusinessError("订单号重复")
    net = sum((r.shares if r.kind != "REDEEM" else -r.shares for r in payload.rows), Decimal(0))
    if net != payload.expected_shares:
        raise BusinessError("历史份额合计与预期不一致")
    ids = []

    def transaction(row: HistoryRow, kind: str, suffix: str, amount: Decimal):
        key = hashlib.sha256((str(account.id) + row.order_id + suffix).encode()).hexdigest()
        txn = InvestmentTransaction(
            account_id=account.id,
            instrument_id=instrument.id if kind not in ("DEPOSIT", "WITHDRAW") else None,
            transaction_type=kind,
            status="CONFIRMED",
            business_date=row.posting_date,
            currency="CNY",
            total_amount=amount,
            idempotency_key="fund-history:" + key,
            memo=json.dumps(
                {
                    "origin": "user_confirmed_screenshot_history",
                    "order_id": row.order_id,
                    "evidence": row.evidence,
                    "role": suffix,
                },
                ensure_ascii=False,
            ),
        )
        db.add(txn)
        db.flush()
        ids.append(str(txn.id))
        return txn

    for row in sorted(payload.rows, key=lambda r: (r.posting_date, r.order_id)):
        if row.kind == "SUBSCRIBE":
            bridge = transaction(row, "DEPOSIT", "external_payment_bridge", row.amount)
            post_transaction(db, bridge)
            db.flush()
        kind = {
            "SUBSCRIBE": "FUND_SUBSCRIBE",
            "REDEEM": "FUND_REDEEM",
            "CONVERSION_BOUNDARY": "OPENING_BALANCE",
        }[row.kind]
        txn = transaction(row, kind, row.kind, row.amount)
        if row.kind == "CONVERSION_BOUNDARY":
            db.add(
                OpeningBalanceDetail(
                    transaction_id=txn.id,
                    row_kind="POSITION",
                    quantity=row.shares,
                    total_cost=row.amount,
                    cost_source=json.dumps(
                        {
                            "boundary": "转换转入历史边界，原基金历史成本未知",
                            "nav": str(row.nav),
                            "evidence": row.evidence,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
        else:
            txn.confirmation_status = "CONFIRMED"
            db.add(
                FundOrderDetail(
                    transaction_id=txn.id,
                    platform="ALIPAY",
                    apply_amount=row.amount if row.kind == "SUBSCRIBE" else None,
                    apply_shares=row.shares if row.kind == "REDEEM" else None,
                    expected_fee=row.fee,
                )
            )
            db.add(
                FundConfirmation(
                    transaction_id=txn.id,
                    confirmation_date=row.posting_date,
                    nav=row.nav,
                    confirmed_shares=row.shares,
                    confirmed_amount=row.amount - row.fee
                    if row.kind == "SUBSCRIBE"
                    else row.amount,
                    fee_amount=row.fee,
                    raw=row.evidence,
                )
            )
        db.flush()
        post_transaction(db, txn)
        db.flush()
        if row.kind == "REDEEM":
            bridge = transaction(row, "WITHDRAW", "external_receipt_bridge", row.amount - row.fee)
            post_transaction(db, bridge)
            db.flush()
    lots = db.scalars(
        select(PositionLot).where(
            PositionLot.investment_account_id == account.id,
            PositionLot.instrument_id == instrument.id,
        )
    ).all()
    quantity = sum((lot.remaining_quantity for lot in lots), Decimal(0))
    cost = sum((lot.total_cost for lot in lots), Decimal(0))
    if quantity != payload.expected_shares:
        raise BusinessError("过账后份额不一致，整批回滚")
    result = {
        "quantity": str(quantity),
        "book_cost": str(cost),
        "transaction_ids": ids,
        "history_rows": len(payload.rows),
        "conversion_source_history_complete": False,
        "notice": "份额按用户提供的交易重建，未由平台当前份额独立验证；转换前历史不完整。",
    }
    db.execute(
        text("""INSERT INTO fund_history_imports
        (id,account_id,instrument_id,request_key,payload,result)
        VALUES (:id,:a,:i,:key,CAST(:p AS jsonb),CAST(:r AS jsonb))"""),
        {
            "id": uuid.uuid4(),
            "a": account.id,
            "i": instrument.id,
            "key": payload.request_key,
            "p": json.dumps(data),
            "r": json.dumps(result),
        },
    )
    record_audit(db, "IMPORT_FUND_HISTORY", "fund_history", str(instrument.id), result)
    db.flush()
    return result
