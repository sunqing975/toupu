# 期初资产明细模型，对应迁移 0007 的 opening_balance_details。
# docs/ledger-rules.md §10 / §16.3：期初余额不是历史买入，
# 需保留数量、账面成本、成本口径来源与估值日期，不得伪造历史成交日期。
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OpeningBalanceDetail(Base):
    """一笔 OPENING_BALANCE 交易一条：CASH（期初现金）或 POSITION（期初持仓）。"""

    __tablename__ = "opening_balance_details"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_transactions.id"), unique=True
    )
    row_kind: Mapped[str] = mapped_column(String(10))  # CASH / POSITION
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    cost_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    valuation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
