# 行情/净值与快照 ORM 模型，逐列对齐迁移 0008 的原生 DDL。
# 教训（0007）：op.execute 建表时 ORM 不得多写 DDL 中不存在的列（否则 UndefinedColumn 500）。
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MarketQuote(Base):
    """股票/ETF 日行情：估值输入，不是交易事实（§13 / §17.1）。"""

    __tablename__ = "market_quotes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"))
    quote_date: Mapped[date] = mapped_column(Date)
    provider: Mapped[str] = mapped_column(String(50))
    provider_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    market_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_type: Mapped[str] = mapped_column(String(10))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    adjust_type: Mapped[str] = mapped_column(String(10), default="NONE")
    quality_status: Mapped[str] = mapped_column(String(10), default="FRESH")
    delayed: Mapped[bool] = mapped_column(Boolean, default=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundNav(Base):
    """基金正式净值/盘中估值，以 data_type 区分；估值不用于核算（§13 / §17.1）。"""

    __tablename__ = "fund_nav_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"))
    nav_date: Mapped[date] = mapped_column(Date)
    provider: Mapped[str] = mapped_column(String(50))
    provider_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    data_type: Mapped[str] = mapped_column(String(10))
    nav: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    accumulated_nav: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    quality_status: Mapped[str] = mapped_column(String(10), default="FRESH")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PositionSnapshot(Base):
    """逐账户×品种持仓快照：派生结果，可删除重建（database-design §3 / §17.7）。"""

    __tablename__ = "position_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investment_accounts.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    book_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    quote_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    quote_status: Mapped[str] = mapped_column(String(10))
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quote_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    unrealized: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PortfolioSnapshot(Base):
    """组合快照：MDD/TWR 的统一口径净值序列（§17.6 / §17.7）。"""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_date: Mapped[date] = mapped_column(Date, unique=True)
    cash_total: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    total_assets: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    realized_total: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    dividend_income: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unrealized_total: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    coverage: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    valued_positions: Mapped[int] = mapped_column(Integer, default=0)
    total_positions: Mapped[int] = mapped_column(Integer, default=0)
    data_quality: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
