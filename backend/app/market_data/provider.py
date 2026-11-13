# 行情 Provider/Adapter 抽象与 MANUAL 实现（architecture.md §3-§5）。
# 业务模块依赖标准化接口，不直接依赖第三方 SDK；本版只有 MANUAL（显式录入），数据源可替换。
# 报价选取规则依据 docs/ledger-rules.md §13 / §17.7：
#   优先 OFFICIAL + FRESH + quote_date<=as_of 最新；ESTIMATED 仅展示不估值；
#   超 stale_days 标 STALE；无报价 UNKNOWN。行情缺失/过期不静默用旧值冒充实时。
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import ClassVar, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.instruments.models import Instrument
from app.market_data.models import FundNav, MarketQuote

QuoteStatus = Literal["FRESH", "STALE", "UNKNOWN", "ESTIMATED"]


@dataclass(frozen=True)
class QuoteView:
    """标准化报价视图：估值输入，保留来源/日期/质量（§13）。"""

    price: Decimal | None
    status: QuoteStatus
    quote_date: date | None = None
    provider: str | None = None
    data_type: str | None = None
    adjust_type: str | None = None
    quality_status: str | None = None


class MarketDataProvider(ABC):
    """统一接口：get_quote / get_daily_history / get_fund_nav / get_trading_calendar。"""

    name: ClassVar[str]

    @abstractmethod
    def get_quote(
        self, db: Session, instrument: Instrument, as_of: date, stale_days: int
    ) -> QuoteView: ...

    @abstractmethod
    def get_fund_nav(
        self, db: Session, instrument: Instrument, as_of: date, stale_days: int
    ) -> QuoteView: ...

    @abstractmethod
    def get_daily_history(
        self, db: Session, instrument: Instrument, start: date, end: date
    ) -> list[QuoteView]: ...

    @abstractmethod
    def get_trading_calendar(self, db: Session, start: date, end: date) -> list[date]: ...


class ManualProvider(MarketDataProvider):
    """从本地录入的行情/净值表读取，不发起任何外部请求（agent.md §4 模块化单体）。"""

    name = "MANUAL"

    def get_quote(
        self, db: Session, instrument: Instrument, as_of: date, stale_days: int
    ) -> QuoteView:
        official = (
            db.execute(
                select(MarketQuote)
                .where(
                    MarketQuote.instrument_id == instrument.id,
                    MarketQuote.quote_date <= as_of,
                    MarketQuote.data_type == "OFFICIAL",
                    MarketQuote.quality_status == "FRESH",
                    MarketQuote.adjust_type == "NONE",
                )
                .order_by(MarketQuote.quote_date.desc(), MarketQuote.created_at.desc())
            )
            .scalars()
            .first()
        )
        if official is not None:
            status: QuoteStatus = (
                "FRESH" if (as_of - official.quote_date).days <= stale_days else "STALE"
            )
            return QuoteView(
                price=official.price,
                status=status,
                quote_date=official.quote_date,
                provider=official.provider,
                data_type=official.data_type,
                adjust_type=official.adjust_type,
                quality_status=official.quality_status,
            )
        return self._estimated_or_unknown_quote(db, instrument.id, as_of)

    def get_fund_nav(
        self, db: Session, instrument: Instrument, as_of: date, stale_days: int
    ) -> QuoteView:
        official = (
            db.execute(
                select(FundNav)
                .where(
                    FundNav.instrument_id == instrument.id,
                    FundNav.nav_date <= as_of,
                    FundNav.data_type == "OFFICIAL",
                    FundNav.quality_status == "FRESH",
                )
                .order_by(FundNav.nav_date.desc(), FundNav.created_at.desc())
            )
            .scalars()
            .first()
        )
        if official is not None:
            status: QuoteStatus = (
                "FRESH" if (as_of - official.nav_date).days <= stale_days else "STALE"
            )
            return QuoteView(
                price=official.nav,
                status=status,
                quote_date=official.nav_date,
                provider=official.provider,
                data_type=official.data_type,
                quality_status=official.quality_status,
            )
        return self._estimated_or_unknown_nav(db, instrument.id, as_of)

    def _estimated_or_unknown_quote(
        self, db: Session, instrument_id: object, as_of: date
    ) -> QuoteView:
        estimated = (
            db.execute(
                select(MarketQuote)
                .where(
                    MarketQuote.instrument_id == instrument_id,
                    MarketQuote.quote_date <= as_of,
                    MarketQuote.data_type == "ESTIMATED",
                )
                .order_by(MarketQuote.quote_date.desc(), MarketQuote.created_at.desc())
            )
            .scalars()
            .first()
        )
        if estimated is not None:
            return QuoteView(
                price=estimated.price,
                status="ESTIMATED",
                quote_date=estimated.quote_date,
                provider=estimated.provider,
                data_type=estimated.data_type,
                quality_status=estimated.quality_status,
            )
        return QuoteView(price=None, status="UNKNOWN")

    def _estimated_or_unknown_nav(
        self, db: Session, instrument_id: object, as_of: date
    ) -> QuoteView:
        estimated = (
            db.execute(
                select(FundNav)
                .where(
                    FundNav.instrument_id == instrument_id,
                    FundNav.nav_date <= as_of,
                    FundNav.data_type == "ESTIMATED",
                )
                .order_by(FundNav.nav_date.desc(), FundNav.created_at.desc())
            )
            .scalars()
            .first()
        )
        if estimated is not None:
            return QuoteView(
                price=estimated.nav,
                status="ESTIMATED",
                quote_date=estimated.nav_date,
                provider=estimated.provider,
                data_type=estimated.data_type,
                quality_status=estimated.quality_status,
            )
        return QuoteView(price=None, status="UNKNOWN")

    def get_daily_history(
        self, db: Session, instrument: Instrument, start: date, end: date
    ) -> list[QuoteView]:
        rows = (
            db.execute(
                select(MarketQuote)
                .where(
                    MarketQuote.instrument_id == instrument.id,
                    MarketQuote.quote_date >= start,
                    MarketQuote.quote_date <= end,
                )
                .order_by(MarketQuote.quote_date)
            )
            .scalars()
            .all()
        )
        return [
            QuoteView(
                price=row.price,
                status="FRESH" if row.quality_status == "FRESH" else "STALE",
                quote_date=row.quote_date,
                provider=row.provider,
                data_type=row.data_type,
                adjust_type=row.adjust_type,
                quality_status=row.quality_status,
            )
            for row in rows
        ]

    def get_trading_calendar(self, db: Session, start: date, end: date) -> list[date]:
        rows = db.execute(
            select(MarketQuote.quote_date)
            .where(MarketQuote.quote_date >= start, MarketQuote.quote_date <= end)
            .distinct()
            .order_by(MarketQuote.quote_date)
        ).all()
        return [row[0] for row in rows]


_PROVIDERS: dict[str, type[MarketDataProvider]] = {"MANUAL": ManualProvider}


def get_provider(name: str = "MANUAL") -> MarketDataProvider:
    """工厂：数据源可替换（architecture.md §3），本版仅注册 MANUAL。"""
    provider_cls = _PROVIDERS.get(name)
    if provider_cls is None:
        raise ValueError(f"未注册的行情数据源：{name}")
    return provider_cls()


def resolve_quote(
    db: Session,
    instrument: Instrument,
    as_of: date,
    stale_days: int = 7,
    provider_name: str = "MANUAL",
) -> QuoteView:
    """按品种类型分派：FUND 用正式净值，STOCK/ETF 用日行情（§17.7）。"""
    provider = get_provider(provider_name)
    if instrument.instrument_type == "FUND":
        return provider.get_fund_nav(db, instrument, as_of, stale_days)
    return provider.get_quote(db, instrument, as_of, stale_days)
