# 投资业务事件模型，对应迁移 0001/0003 的 investment_transactions 表。
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class InvestmentTransaction(Base):
    __tablename__ = "investment_transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investment_accounts.id"))
    counter_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=True
    )
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("instruments.id"), nullable=True
    )
    transaction_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12), default="DRAFT")
    confirmation_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    business_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("investment_transactions.id"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
