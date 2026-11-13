# 快照 API：重建（幂等先删后建）、查询组合快照序列与逐持仓明细（§17.7/§17.8）。
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.models import PortfolioSnapshot, PositionSnapshot
from app.snapshots.service import list_snapshots, positions_on, rebuild_snapshots

router = APIRouter(prefix="/api/v1/snapshots", tags=["snapshots"])

QuoteStatus = Literal["FRESH", "STALE", "UNKNOWN", "ESTIMATED"]
DataQuality = Literal["COMPLETE", "PARTIAL", "NO_QUOTES"]


class RebuildIn(BaseModel):
    snapshot_date: date


class PositionSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_date: date
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    quantity: Decimal
    book_cost: Decimal
    quote_price: Decimal | None
    quote_status: QuoteStatus
    quote_date: date | None
    quote_provider: str | None
    market_value: Decimal | None
    unrealized: Decimal | None
    created_at: datetime


class PortfolioSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_date: date
    cash_total: Decimal
    market_value: Decimal
    total_assets: Decimal
    realized_total: Decimal
    dividend_income: Decimal
    unrealized_total: Decimal
    coverage: Decimal
    valued_positions: int
    total_positions: int
    data_quality: DataQuality
    created_at: datetime


class RebuildOut(BaseModel):
    snapshot: PortfolioSnapshotOut
    positions: list[PositionSnapshotOut]


@router.post("/rebuild", response_model=RebuildOut)
def rebuild(
    payload: RebuildIn,
    stale_days: int = Query(default=7, ge=0),
    db: Session = Depends(get_db),
) -> RebuildOut:
    portfolio, _ = rebuild_snapshots(db, payload.snapshot_date, stale_days)
    rows = positions_on(db, payload.snapshot_date)
    return RebuildOut(
        snapshot=PortfolioSnapshotOut.model_validate(portfolio),
        positions=[PositionSnapshotOut.model_validate(row) for row in rows],
    )


@router.get("", response_model=list[PortfolioSnapshotOut])
def list_all(
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[PortfolioSnapshot]:
    return list_snapshots(db, limit)


@router.get("/{snapshot_date}/positions", response_model=list[PositionSnapshotOut])
def positions(
    snapshot_date: date,
    db: Session = Depends(get_db),
) -> list[PositionSnapshot]:
    return positions_on(db, snapshot_date)
