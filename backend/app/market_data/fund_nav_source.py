"""Bounded published NAV adapter. No estimated prices or transaction mutations."""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.errors import BusinessError
from app.instruments.models import Instrument
from app.market_data.models import FundNav
from app.positions.service import PositionLot

URL = "https://api.fund.eastmoney.com/f10/lsjz"
PROVIDER = "EASTMONEY_NAV"


def parse_navs(data: dict, instrument: Instrument) -> list[dict]:
    if data.get("ErrCode") != 0:
        raise ValueError("NAV provider error")
    source = data["Data"]["LSJZList"]
    if not isinstance(source, list) or not 1 <= len(source) <= 10:
        raise ValueError("NAV rows missing or excessive")
    rows, seen = [], set()
    for item in source:
        day = date.fromisoformat(item["FSRQ"])
        nav = Decimal(item["DWJZ"])
        accumulated = Decimal(item["LJJZ"]) if item.get("LJJZ") else None
        for number in (nav, accumulated):
            if number is not None and (
                not number.is_finite()
                or number <= 0
                or number >= Decimal("100000000000000")
                or number != number.quantize(Decimal("0.000001"))
            ):
                raise ValueError("invalid NAV")
        if day > datetime.now(ZoneInfo("Asia/Shanghai")).date() or day in seen:
            raise ValueError("invalid NAV date")
        seen.add(day)
        rows.append(
            dict(
                instrument_id=instrument.id,
                nav_date=day,
                nav=nav,
                accumulated_nav=accumulated,
                provider=PROVIDER,
                provider_code=instrument.code,
                data_type="OFFICIAL",
                quality_status="FRESH",
            )
        )
    return rows


def fetch_navs(instrument: Instrument) -> list[dict]:
    if (
        instrument.instrument_type != "FUND"
        or instrument.currency != "CNY"
        or instrument.market != "CN"
        or not re.fullmatch(r"[0-9]{6}", instrument.code)
    ):
        raise BusinessError("仅支持六位代码人民币公募基金")
    try:
        with (
            httpx.Client(timeout=15, follow_redirects=False) as client,
            client.stream(
                "GET",
                URL,
                params={"fundCode": instrument.code, "pageIndex": 1, "pageSize": 10},
                headers={"Referer": "https://fundf10.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
            ) as r,
        ):
            r.raise_for_status()
            body = bytearray()
            for chunk in r.iter_bytes():
                body.extend(chunk)
                if len(body) > 500000:
                    raise ValueError("NAV response too large")
        return parse_navs(json.loads(body), instrument)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ArithmeticError):
        raise BusinessError("公开基金净值获取或校验失败，未写入；请稍后重试") from None


def sync_held_navs(db: Session) -> dict:
    instruments = db.scalars(
        select(Instrument)
        .join(PositionLot, PositionLot.instrument_id == Instrument.id)
        .where(PositionLot.remaining_quantity > 0, Instrument.instrument_type == "FUND")
        .distinct()
    ).all()
    if len(instruments) > 50:
        raise BusinessError("单次最多同步50只持仓基金")
    results = []
    # Fetch all before persistence: source failure cannot leave an incomplete batch.
    fetched = [(i, fetch_navs(i)) for i in instruments]
    for instrument, rows in fetched:
        inserted = 0
        for row in rows:
            inserted += len(
                db.execute(
                    insert(FundNav).values(**row).on_conflict_do_nothing().returning(FundNav.id)
                ).all()
            )
        latest = max(rows, key=lambda r: r["nav_date"])
        results.append(
            {
                "code": instrument.code,
                "name": instrument.name,
                "inserted": inserted,
                "nav_date": str(latest["nav_date"]),
                "nav": str(latest["nav"]),
            }
        )
    record_audit(db, "SYNC_FUND_NAVS", "market_data", PROVIDER, {"funds": results})
    db.commit()
    return {"provider": PROVIDER, "funds": results, "inserted": sum(r["inserted"] for r in results)}
