# 场外基金申请明细与确认结果模型，对应迁移 0001/0006 的 fund_order_details / fund_confirmations。
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FundOrderDetail(Base):
    """基金申赎申请明细。一笔基金交易一条。

    apply_amount 仅申购时为「实际扣款总额（含申购费）」；
    赎回/红利再投资确认前无实际金额，保持 NULL（不猜测，docs/ledger-rules.md §15.2）。
    apply_shares 为赎回申请份额（红利再投资可存预计份额）。
    """

    __tablename__ = "fund_order_details"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_transactions.id"), unique=True
    )
    platform: Mapped[str] = mapped_column(String(50))
    apply_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    apply_shares: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    expected_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundConfirmation(Base):
    """基金申赎确认结果：确认净值、确认份额、确认金额、费用。申请≠份额到账。"""

    __tablename__ = "fund_confirmations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_transactions.id"), unique=True
    )
    confirmation_date: Mapped[date] = mapped_column(Date)
    nav: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    confirmed_shares: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    confirmed_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal(0))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
