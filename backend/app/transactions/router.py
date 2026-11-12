# 投资交易 API：草稿创建、确认、过账（幂等）、冲正、取消。
import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.audit import record_audit
from app.core.errors import BusinessError
from app.db.session import get_db
from app.executions.models import TradeExecution
from app.instruments.models import Instrument
from app.ledger.models import JournalEntry, JournalLine, LedgerAccount
from app.ledger.service import FUND_CONFIRM_REQUIRED, post_transaction, reverse_transaction
from app.transactions.models import InvestmentTransaction

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])

CASH_TYPES = ("DEPOSIT", "WITHDRAW", "ACCOUNT_TRANSFER")
SECURITY_BUY_TYPES = ("STOCK_BUY", "ETF_BUY")
SECURITY_SELL_TYPES = ("STOCK_SELL", "ETF_SELL")
SECURITY_TYPES = SECURITY_BUY_TYPES + SECURITY_SELL_TYPES
TxnType = Literal[
    "DEPOSIT",
    "WITHDRAW",
    "ACCOUNT_TRANSFER",
    "STOCK_BUY",
    "STOCK_SELL",
    "ETF_BUY",
    "ETF_SELL",
]


class ExecutionIn(BaseModel):
    execution_date: date
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee_amount: Decimal = Field(default=Decimal(0), ge=0)


class TransactionIn(BaseModel):
    transaction_type: TxnType
    account_id: uuid.UUID
    counter_account_id: uuid.UUID | None = None
    instrument_id: uuid.UUID | None = None
    business_date: date
    amount: Decimal | None = Field(default=None, gt=0)
    memo: str | None = None
    idempotency_key: str | None = None
    executions: list[ExecutionIn] = []

    @model_validator(mode="after")
    def check_shape(self) -> "TransactionIn":
        if self.transaction_type == "ACCOUNT_TRANSFER" and self.counter_account_id is None:
            raise ValueError("转账必须指定转入账户 counter_account_id")
        if self.transaction_type in SECURITY_TYPES:
            if self.instrument_id is None:
                raise ValueError("证券交易必须指定 instrument_id")
            if not self.executions:
                raise ValueError("证券交易必须至少包含一笔成交")
        else:
            if self.amount is None:
                raise ValueError("现金业务必须指定金额 amount")
            if self.executions:
                raise ValueError("现金业务不包含成交明细")
        return self


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    counter_account_id: uuid.UUID | None
    instrument_id: uuid.UUID | None
    transaction_type: str
    status: str
    business_date: date
    currency: str
    total_amount: Decimal | None
    memo: str | None
    reversal_of_id: uuid.UUID | None


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence_no: int
    execution_date: date
    quantity: Decimal
    price: Decimal
    gross_amount: Decimal
    fee_amount: Decimal
    net_amount: Decimal


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    direction: str
    amount: Decimal
    ledger_account_id: uuid.UUID
    ledger_account_name: str


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_type: str
    posted_at: object
    lines: list[LineOut]


class TransactionDetail(TransactionOut):
    entry: EntryOut | None = None
    executions: list[ExecutionOut] = []


def _executions_to_out(db: Session, txn_id: uuid.UUID) -> list[ExecutionOut]:
    rows = (
        db.query(TradeExecution)
        .filter_by(transaction_id=txn_id)
        .order_by(TradeExecution.sequence_no)
        .all()
    )
    return [ExecutionOut.model_validate(ex, from_attributes=True) for ex in rows]


def _entry_to_out(db: Session, entry: JournalEntry | None) -> EntryOut | None:
    if entry is None:
        return None
    rows = (
        db.query(JournalLine, LedgerAccount.name)
        .join(LedgerAccount, LedgerAccount.id == JournalLine.ledger_account_id)
        .filter(JournalLine.entry_id == entry.id)
        .order_by(JournalLine.line_no, JournalLine.id)
        .all()
    )
    return EntryOut(
        id=entry.id,
        entry_type=entry.entry_type,
        posted_at=entry.posted_at,
        lines=[
            LineOut(
                direction=line.direction,
                amount=line.amount,
                ledger_account_id=line.ledger_account_id,
                ledger_account_name=name,
            )
            for line, name in rows
        ],
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransactionDetail)
def create_transaction(payload: TransactionIn, db: Session = Depends(get_db)) -> TransactionDetail:
    if db.get(InvestmentAccount, payload.account_id) is None:
        raise HTTPException(status_code=404, detail="转出账户不存在")
    if (
        payload.counter_account_id is not None
        and db.get(InvestmentAccount, payload.counter_account_id) is None
    ):
        raise HTTPException(status_code=404, detail="转入账户不存在")
    if payload.counter_account_id == payload.account_id:
        raise BusinessError("转入账户与转出账户不能相同")

    is_security = payload.transaction_type in SECURITY_TYPES
    instrument_id = payload.instrument_id
    if is_security:
        if db.get(Instrument, instrument_id) is None:
            raise HTTPException(status_code=404, detail="投资品种不存在")
    else:
        instrument_id = None

    # 金额一律服务端计算：gross = 数量×价格；买入 net = gross+费用，卖出 net = gross−费用
    total_amount = payload.amount
    if is_security:
        nets = [
            (
                ex.quantity * ex.price + ex.fee_amount
                if payload.transaction_type in SECURITY_BUY_TYPES
                else ex.quantity * ex.price - ex.fee_amount
            )
            for ex in payload.executions
        ]
        total_amount = sum(nets, Decimal(0))

    txn = InvestmentTransaction(
        account_id=payload.account_id,
        counter_account_id=payload.counter_account_id
        if payload.transaction_type == "ACCOUNT_TRANSFER"
        else None,
        instrument_id=instrument_id,
        transaction_type=payload.transaction_type,
        status="DRAFT",
        business_date=payload.business_date,
        total_amount=total_amount,
        memo=payload.memo,
        idempotency_key=payload.idempotency_key,
    )
    db.add(txn)
    try:
        db.flush()
        if is_security:
            # txn.id 由 flush 生成后再落成交，避免主键为 None
            for no, ex in enumerate(payload.executions, start=1):
                gross = ex.quantity * ex.price
                net = (
                    gross + ex.fee_amount
                    if payload.transaction_type in SECURITY_BUY_TYPES
                    else gross - ex.fee_amount
                )
                db.add(
                    TradeExecution(
                        transaction_id=txn.id,
                        sequence_no=no,
                        execution_date=ex.execution_date,
                        quantity=ex.quantity,
                        price=ex.price,
                        gross_amount=gross,
                        fee_amount=ex.fee_amount,
                        net_amount=net,
                    )
                )
        db.commit()
    except Exception:
        db.rollback()
        raise BusinessError("重复请求：相同幂等键的交易已存在") from None
    db.refresh(txn)
    detail = TransactionDetail.model_validate(txn, from_attributes=True)
    detail.executions = _executions_to_out(db, txn.id)
    detail.entry = None
    return detail


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    status_filter: Literal["DRAFT", "CONFIRMED", "PARTIAL", "POSTED", "REVERSED", "CANCELLED"]
    | None = None,
    account_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> list[InvestmentTransaction]:
    query = select(InvestmentTransaction).order_by(
        InvestmentTransaction.business_date.desc(), InvestmentTransaction.created_at.desc()
    )
    if status_filter:
        query = query.where(InvestmentTransaction.status == status_filter)
    if account_id:
        query = query.where(
            (InvestmentTransaction.account_id == account_id)
            | (InvestmentTransaction.counter_account_id == account_id)
        )
    return list(db.execute(query.limit(100)).scalars())


@router.get("/{transaction_id}", response_model=TransactionDetail)
def get_transaction(transaction_id: uuid.UUID, db: Session = Depends(get_db)) -> TransactionDetail:
    txn = db.get(InvestmentTransaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="交易不存在")
    detail = TransactionDetail.model_validate(txn, from_attributes=True)
    detail.entry = _entry_to_out(
        db, db.query(JournalEntry).filter_by(transaction_id=txn.id).one_or_none()
    )
    detail.executions = _executions_to_out(db, txn.id)
    return detail


@router.post("/{transaction_id}/confirm", response_model=TransactionOut)
def confirm_transaction(
    transaction_id: uuid.UUID, db: Session = Depends(get_db)
) -> InvestmentTransaction:
    txn = db.get(InvestmentTransaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="交易不存在")
    if txn.status != "DRAFT":
        raise BusinessError("只有草稿状态可以确认")
    # 场外基金两段式申请必须走 /api/v1/funds/orders/{id}/confirm 写入确认数据，
    # 不能用通用确认端点绕过确认状态（ledger-rules §15.1）
    if txn.transaction_type in FUND_CONFIRM_REQUIRED:
        raise BusinessError("基金申请请通过基金确认接口录入确认净值与份额")
    txn.status = "CONFIRMED"
    record_audit(db, "transaction.confirm", "investment_transaction", str(txn.id))
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/{transaction_id}/post", response_model=TransactionDetail)
def post(transaction_id: uuid.UUID, db: Session = Depends(get_db)) -> TransactionDetail:
    txn = db.get(InvestmentTransaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="交易不存在")
    entry = post_transaction(db, txn)
    db.commit()
    detail = TransactionDetail.model_validate(txn, from_attributes=True)
    detail.entry = _entry_to_out(db, entry)
    detail.executions = _executions_to_out(db, txn.id)
    return detail


@router.post("/{transaction_id}/reverse", response_model=TransactionDetail)
def reverse(transaction_id: uuid.UUID, db: Session = Depends(get_db)) -> TransactionDetail:
    txn = db.get(InvestmentTransaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="交易不存在")
    reverse_transaction(db, txn)
    db.commit()
    db.refresh(txn)
    detail = TransactionDetail.model_validate(txn, from_attributes=True)
    detail.entry = _entry_to_out(db, db.query(JournalEntry).filter_by(transaction_id=txn.id).one())
    detail.executions = _executions_to_out(db, txn.id)
    return detail


@router.post("/{transaction_id}/cancel", response_model=TransactionOut)
def cancel(transaction_id: uuid.UUID, db: Session = Depends(get_db)) -> InvestmentTransaction:
    txn = db.get(InvestmentTransaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="交易不存在")
    if txn.status not in ("DRAFT", "CONFIRMED"):
        raise BusinessError("只有未入账的交易可以取消")
    txn.status = "CANCELLED"
    record_audit(db, "transaction.cancel", "investment_transaction", str(txn.id))
    db.commit()
    db.refresh(txn)
    return txn
