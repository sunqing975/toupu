# 股票/ETF 实际成交模型，对应迁移 0001 的 trade_executions 表。
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TradeExecution(Base):
    __tablename__ = "trade_executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investment_transactions.id"))
    sequence_no: Mapped[int] = mapped_column(Integer)
    execution_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
