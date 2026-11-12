# 投资标的 API：CRUD，market+code 唯一（重复返回 409）。第一版类型：FUND/ETF/STOCK。
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.instruments.models import Instrument

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])

InstrumentType = Literal["FUND", "ETF", "STOCK"]


class InstrumentIn(BaseModel):
    instrument_type: InstrumentType
    market: str = "CN"
    exchange: str | None = None
    code: str
    name: str
    currency: str = "CNY"


class InstrumentPatch(BaseModel):
    name: str | None = None
    status: Literal["ACTIVE", "DELISTED"] | None = None


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instrument_type: str
    market: str
    exchange: str | None
    code: str
    name: str
    currency: str
    status: str


@router.post("", status_code=status.HTTP_201_CREATED, response_model=InstrumentOut)
def create_instrument(payload: InstrumentIn, db: Session = Depends(get_db)) -> Instrument:
    instrument = Instrument(**payload.model_dump())
    db.add(instrument)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="同一市场下代码已存在") from None
    db.refresh(instrument)
    return instrument


@router.get("", response_model=list[InstrumentOut])
def list_instruments(
    instrument_type: InstrumentType | None = None, db: Session = Depends(get_db)
) -> list[Instrument]:
    query = db.query(Instrument).order_by(Instrument.market, Instrument.code)
    if instrument_type:
        query = query.filter(Instrument.instrument_type == instrument_type)
    return list(query)


@router.get("/{instrument_id}", response_model=InstrumentOut)
def get_instrument(instrument_id: uuid.UUID, db: Session = Depends(get_db)) -> Instrument:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="标的不存在")
    return instrument


@router.patch("/{instrument_id}", response_model=InstrumentOut)
def update_instrument(
    instrument_id: uuid.UUID, payload: InstrumentPatch, db: Session = Depends(get_db)
) -> Instrument:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="标的不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(instrument, field, value)
    db.commit()
    db.refresh(instrument)
    return instrument
