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
from app.ledger.models import JournalEntry, JournalLine, LedgerAccount
from app.ledger.service import post_transaction, reverse_transaction
from app.transactions.models import InvestmentTransaction

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])

M1_TYPES = Literal["DEPOSIT", "WITHDRAW", "ACCOUNT_TRANSFER"]


class TransactionIn(BaseModel):
    transaction_type: M1_TYPES
    account_id: uuid.UUID
    counter_account_id: uuid.UUID | None = None
    business_date: date
    amount: Decimal = Field(gt=0)
    memo: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def transfer_needs_counter(self) -> "TransactionIn":
        if self.transaction_type == "ACCOUNT_TRANSFER" and self.counter_account_id is None:
            raise ValueError("转账必须指定转入账户 counter_account_id")
        return self


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    counter_account_id: uuid.UUID | None
    transaction_type: str
    status: str
    business_date: date
    currency: str
    total_amount: Decimal | None
    memo: str | None
    reversal_of_id: uuid.UUID | None


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


def _entry_to_out(db: Session, entry: JournalEntry | None) -> EntryOut | None:
    if entry is None:
        return None
    rows = (
        db.query(JournalLine, LedgerAccount.name)
        .join(LedgerAccount, LedgerAccount.id == JournalLine.ledger_account_id)
        .filter(JournalLine.entry_id == entry.id)
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


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransactionOut)
def create_transaction(
    payload: TransactionIn, db: Session = Depends(get_db)
) -> InvestmentTransaction:
    if db.get(InvestmentAccount, payload.account_id) is None:
        raise HTTPException(status_code=404, detail="转出账户不存在")
    if (
        payload.counter_account_id is not None
        and db.get(InvestmentAccount, payload.counter_account_id) is None
    ):
        raise HTTPException(status_code=404, detail="转入账户不存在")
    if payload.counter_account_id == payload.account_id:
        raise BusinessError("转入账户与转出账户不能相同")

    txn = InvestmentTransaction(
        account_id=payload.account_id,
        counter_account_id=payload.counter_account_id
        if payload.transaction_type == "ACCOUNT_TRANSFER"
        else None,
        transaction_type=payload.transaction_type,
        status="DRAFT",
        business_date=payload.business_date,
        total_amount=payload.amount,
        memo=payload.memo,
        idempotency_key=payload.idempotency_key,
    )
    db.add(txn)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise BusinessError("重复请求：相同幂等键的交易已存在") from None
    db.refresh(txn)
    return txn


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
