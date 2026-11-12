# 账本模型：科目、分录、分录行，对应迁移 0001 的 ledger_* 表。
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_type: Mapped[str] = mapped_column(String(20))
    investment_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=True
    )
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("instruments.id"), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_transactions.id"), unique=True
    )
    entry_type: Mapped[str] = mapped_column(String(10), default="NORMAL")
    reversal_of_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id"), nullable=True
    )
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journal_entries.id"))
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_accounts.id"))
    direction: Mapped[str] = mapped_column(String(6))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    line_no: Mapped[int] = mapped_column(Integer, default=0)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
