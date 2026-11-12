# 持仓查询 API：聚合 remaining lots 得到各账户×品种的持仓与成本。
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.instruments.models import Instrument
from app.positions.service import PositionLot

router = APIRouter(prefix="/api/v1/positions", tags=["positions"])


class PositionOut(BaseModel):
    account_id: uuid.UUID
    instrument_id: uuid.UUID
    instrument_code: str
    instrument_name: str
    instrument_type: str
    quantity: Decimal
    total_cost: Decimal
    unit_cost: Decimal


@router.get("", response_model=list[PositionOut])
def list_positions(
    account_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> list[PositionOut]:
    query = (
        select(PositionLot, Instrument)
        .join(Instrument, Instrument.id == PositionLot.instrument_id)
        .where(PositionLot.remaining_quantity > 0)
        .order_by(PositionLot.investment_account_id, PositionLot.open_date)
    )
    if account_id:
        query = query.where(PositionLot.investment_account_id == account_id)

    # 同一账户×品种的多个批次聚合：数量、总成本求和，单位成本=总成本/数量
    grouped: dict[tuple[uuid.UUID, uuid.UUID], dict] = {}
    for lot, inst in db.execute(query):
        key = (lot.investment_account_id, lot.instrument_id)
        g = grouped.get(key)
        if g is None:
            g = {
                "quantity": Decimal(0),
                "total_cost": Decimal(0),
                "instrument": inst,
            }
            grouped[key] = g
        g["quantity"] += lot.remaining_quantity
        g["total_cost"] += lot.total_cost

    return [
        PositionOut(
            account_id=acc,
            instrument_id=inst,
            instrument_code=g["instrument"].code,
            instrument_name=g["instrument"].name,
            instrument_type=g["instrument"].instrument_type,
            quantity=g["quantity"],
            total_cost=g["total_cost"],
            unit_cost=(
                (g["total_cost"] / g["quantity"]).quantize(Decimal("0.000001"))
                if g["quantity"]
                else Decimal(0)
            ),
        )
        for (acc, inst), g in grouped.items()
    ]
