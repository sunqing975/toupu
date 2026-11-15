# 行情/净值录入与估值查询 API（M5）。显式 MANUAL 录入，行情是估值输入不是交易事实。
# 规则依据 docs/ledger-rules.md §13 / §17.1/§17.7/§17.8。
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.errors import BusinessError
from app.db.session import get_db
from app.instruments.models import Instrument
from app.market_data.fund_nav_source import sync_held_navs
from app.market_data.ingestion import import_daily
from app.market_data.models import FundNav, MarketQuote
from app.market_data.provider import QuoteStatus
from app.performance.service import PositionValuation, derive

router = APIRouter(prefix="/api/v1/market", tags=["market_data"])

DataType = Literal["OFFICIAL", "ESTIMATED"]
QualityStatus = Literal["FRESH", "STALE", "SUSPENDED", "NO_QUOTE"]
AdjustType = Literal["NONE", "PRE", "POST"]


@router.post("/sync-fund-navs")
def sync_funds(db: Session = Depends(get_db)) -> dict:
    try:
        return sync_held_navs(db)
    except Exception:
        db.rollback()
        raise


class DailyImportIn(BaseModel):
    instrument_id: uuid.UUID
    start: date
    end: date


@router.post("/import-daily")
def ingest_daily(payload: DailyImportIn, db: Session = Depends(get_db)) -> dict:
    return import_daily(db, _get_instrument(db, payload.instrument_id), payload.start, payload.end)


class QuoteIn(BaseModel):
    instrument_id: uuid.UUID
    quote_date: date
    price: Decimal = Field(gt=0)
    provider: str = "MANUAL"
    provider_code: str | None = None
    data_type: DataType = "OFFICIAL"
    quality_status: QualityStatus = "FRESH"
    adjust_type: AdjustType = "NONE"
    delayed: bool = False
    currency: str = "CNY"


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instrument_id: uuid.UUID
    quote_date: date
    provider: str
    provider_code: str | None
    data_type: str
    price: Decimal
    adjust_type: str
    quality_status: str
    delayed: bool
    currency: str
    collected_at: datetime
    market_time: datetime | None


class NavIn(BaseModel):
    instrument_id: uuid.UUID
    nav_date: date
    nav: Decimal = Field(gt=0)
    provider: str = "MANUAL"
    provider_code: str | None = None
    data_type: DataType = "OFFICIAL"
    accumulated_nav: Decimal | None = None
    quality_status: QualityStatus = "FRESH"


class NavOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instrument_id: uuid.UUID
    nav_date: date
    provider: str
    provider_code: str | None
    data_type: str
    nav: Decimal
    accumulated_nav: Decimal | None
    quality_status: str
    collected_at: datetime


class QuoteViewOut(BaseModel):
    price: Decimal | None
    status: QuoteStatus
    quote_date: date | None
    provider: str | None
    data_type: str | None
    adjust_type: str | None
    quality_status: str | None


class ValuationRowOut(BaseModel):
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    instrument_code: str
    instrument_name: str
    instrument_type: str
    quantity: Decimal
    book_cost: Decimal
    quote: QuoteViewOut
    market_value: Decimal | None
    unrealized: Decimal | None
    valued: bool


class ValuationOut(BaseModel):
    as_of: date
    stale_days: int
    positions: list[ValuationRowOut]
    cash_total: Decimal
    market_value: Decimal
    total_assets: Decimal
    realized_total: Decimal
    dividend_income: Decimal
    unrealized_total: Decimal
    coverage: Decimal
    valued_positions: int
    total_positions: int
    data_quality: str


def _get_instrument(db: Session, instrument_id: uuid.UUID) -> Instrument:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="投资品种不存在")
    return instrument


@router.post("/quotes", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
def create_quote(payload: QuoteIn, db: Session = Depends(get_db)) -> MarketQuote:
    _get_instrument(db, payload.instrument_id)
    if payload.data_type == "OFFICIAL" and payload.adjust_type != "NONE":
        raise BusinessError("本版正式行情只接受未复权（adjust_type=NONE）")
    quote = MarketQuote(**payload.model_dump())
    db.add(quote)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("同一来源的该日行情已存在") from None
    db.refresh(quote)
    record_audit(db, "market.quote.create", "market_quote", str(quote.id))
    db.commit()
    return quote


@router.get("/quotes", response_model=list[QuoteOut])
def list_quotes(
    instrument_id: uuid.UUID | None = None,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[MarketQuote]:
    query = select(MarketQuote)
    if instrument_id is not None:
        query = query.where(MarketQuote.instrument_id == instrument_id)
    ordered = query.order_by(MarketQuote.quote_date.desc(), MarketQuote.created_at.desc()).limit(
        limit
    )
    return list(db.execute(ordered).scalars().all())


@router.post("/navs", response_model=NavOut, status_code=status.HTTP_201_CREATED)
def create_nav(payload: NavIn, db: Session = Depends(get_db)) -> FundNav:
    instrument = _get_instrument(db, payload.instrument_id)
    if instrument.instrument_type != "FUND":
        raise BusinessError("基金净值只能录入 FUND 品种")
    nav = FundNav(**payload.model_dump())
    db.add(nav)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("同一来源的该日净值已存在") from None
    db.refresh(nav)
    record_audit(db, "market.nav.create", "fund_nav", str(nav.id))
    db.commit()
    return nav


@router.get("/navs", response_model=list[NavOut])
def list_navs(
    instrument_id: uuid.UUID | None = None,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[FundNav]:
    query = select(FundNav)
    if instrument_id is not None:
        query = query.where(FundNav.instrument_id == instrument_id)
    ordered = query.order_by(FundNav.nav_date.desc(), FundNav.created_at.desc()).limit(limit)
    return list(db.execute(ordered).scalars().all())


def _valuation_row(position: PositionValuation) -> ValuationRowOut:
    quote = position.quote
    return ValuationRowOut(
        account_id=position.account_id,
        instrument_id=position.instrument.id,
        instrument_code=position.instrument.code,
        instrument_name=position.instrument.name,
        instrument_type=position.instrument.instrument_type,
        quantity=position.quantity,
        book_cost=position.book_cost,
        quote=QuoteViewOut(
            price=quote.price,
            status=quote.status,
            quote_date=quote.quote_date,
            provider=quote.provider,
            data_type=quote.data_type,
            adjust_type=quote.adjust_type,
            quality_status=quote.quality_status,
        ),
        market_value=position.market_value,
        unrealized=position.unrealized,
        valued=position.valued,
    )


@router.get("/valuation", response_model=ValuationOut)
def valuation(
    as_of: date | None = None,
    stale_days: int = Query(default=7, ge=0),
    db: Session = Depends(get_db),
) -> ValuationOut:
    as_of = as_of or date.today()
    try:
        derived = derive(db, as_of, stale_days)
    except ValueError as exc:
        raise BusinessError(str(exc)) from None
    return ValuationOut(
        as_of=as_of,
        stale_days=stale_days,
        positions=[_valuation_row(position) for position in derived.positions],
        cash_total=derived.cash_total,
        market_value=derived.market_value,
        total_assets=derived.total_assets,
        realized_total=derived.realized_total,
        dividend_income=derived.dividend_income,
        unrealized_total=derived.unrealized_total,
        coverage=derived.coverage,
        valued_positions=derived.valued_positions,
        total_positions=derived.total_positions,
        data_quality=derived.data_quality,
    )
