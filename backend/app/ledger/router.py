# 账本只读 API：复式记账分录流水（journal_entries / journal_lines）。
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.ledger.models import JournalEntry, JournalLine, LedgerAccount

router = APIRouter(prefix="/api/v1/ledger", tags=["ledger"])


class LedgerLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ledger_account_id: uuid.UUID
    ledger_account_name: str
    direction: str
    amount: Decimal
    line_no: int


class LedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    entry_type: str
    reversal_of_entry_id: uuid.UUID | None
    posted_at: datetime
    lines: list[LedgerLineOut] = []


@router.get("/entries", response_model=list[LedgerEntryOut])
def list_entries(
    account_id: uuid.UUID | None = None,
    entry_type: str | None = Query(default=None, pattern="^(NORMAL|REVERSAL)$"),
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[LedgerEntryOut]:
    """只读的复式记账分录流水。

    - 可选按主体投资账户过滤（该账户相关的证券/现金科目分录）。
    - 可选按分录类型（NORMAL / REVERSAL）过滤。
    - 可选按过账日期区间过滤。
    账本是事实来源，本接口只暴露查询，不提供任何写操作。
    """
    query = (
        select(JournalEntry)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .join(LedgerAccount, LedgerAccount.id == JournalLine.ledger_account_id)
    )

    if account_id is not None:
        query = query.where(LedgerAccount.investment_account_id == account_id)
    if entry_type is not None:
        query = query.where(JournalEntry.entry_type == entry_type)
    if from_date is not None:
        query = query.where(JournalEntry.posted_at >= from_date)
    if to_date is not None:
        query = query.where(JournalEntry.posted_at < to_date)

    entries = db.execute(
        query.distinct()
        .order_by(JournalEntry.posted_at.desc(), JournalEntry.id.desc())
        .limit(limit)
    ).scalars()

    result: list[LedgerEntryOut] = []
    for entry in entries:
        result.append(_entry_out(db, entry))
    return result


def _entry_out(db: Session, entry: JournalEntry) -> LedgerEntryOut:
    lines = (
        db.query(JournalLine, LedgerAccount.name)
        .join(LedgerAccount, LedgerAccount.id == JournalLine.ledger_account_id)
        .filter(JournalLine.entry_id == entry.id)
        .order_by(JournalLine.line_no, JournalLine.id)
        .all()
    )
    return LedgerEntryOut(
        id=entry.id,
        transaction_id=entry.transaction_id,
        entry_type=entry.entry_type,
        reversal_of_entry_id=entry.reversal_of_entry_id,
        posted_at=entry.posted_at,
        lines=[
            LedgerLineOut(
                ledger_account_id=line.ledger_account_id,
                ledger_account_name=name,
                direction=line.direction,
                amount=line.amount,
                line_no=line.line_no,
            )
            for line, name in lines
        ],
    )


@router.get("/entries/{entry_id}", response_model=LedgerEntryOut)
def get_entry(entry_id: uuid.UUID, db: Session = Depends(get_db)) -> LedgerEntryOut:
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="分录不存在")
    return _entry_out(db, entry)
