"""Explicit, bounded daily-bar import. Never runs on a timer or changes ledger facts."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.errors import BusinessError
from app.instruments.models import Instrument
from app.market_data.models import MarketQuote

URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
PROVIDER = "EASTMONEY"


def fetch_daily(instrument: Instrument, start: date, end: date) -> list[dict]:
    if (
        instrument.instrument_type not in {"STOCK", "ETF"}
        or instrument.market != "CN"
        or instrument.currency != "CNY"
        or not re.fullmatch(r"[0-9]{6}", instrument.code)
    ):
        raise BusinessError("日线导入仅支持人民币沪深股票/ETF 六位代码；基金净值不使用股票日线接口")
    exchanges = {"SH": "1", "SSE": "1", "SZ": "0", "SZSE": "0"}
    exchange = exchanges.get(instrument.exchange or "")
    if exchange is None:
        raise BusinessError("请先明确设置交易所 SH/SSE 或 SZ/SZSE，不根据代码猜测市场")
    try:
        with (
            httpx.Client(timeout=20, follow_redirects=False) as client,
            client.stream(
                "GET",
                URL,
                params={
                    "secid": exchange + "." + instrument.code,
                    "klt": "101",
                    "fqt": "0",
                    "beg": start.strftime("%Y%m%d"),
                    "end": end.strftime("%Y%m%d"),
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53",
                },
            ) as response,
        ):
            response.raise_for_status()
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > 2_000_000:
                    raise ValueError("response too large")
        import json

        result = json.loads(chunks, parse_float=Decimal)
        data = result["data"]
        if not data or str(data.get("code")) != instrument.code:
            raise ValueError("unexpected instrument")
        bars = data["klines"]
        if not isinstance(bars, list) or len(bars) > 370:
            raise ValueError("invalid bars")
        rows, seen = [], set()
        for bar in bars:
            parts = bar.split(",")
            day, close = date.fromisoformat(parts[0]), Decimal(parts[2])
            if (
                not start <= day <= end
                or day in seen
                or not close.is_finite()
                or close <= 0
                or close >= Decimal("100000000000000")
                or close != close.quantize(Decimal("0.000001"))
            ):
                raise ValueError("invalid daily close")
            seen.add(day)
            rows.append(
                {
                    "instrument_id": instrument.id,
                    "quote_date": day,
                    "price": close,
                    "provider": PROVIDER,
                    "provider_code": exchange + "." + instrument.code,
                    "data_type": "OFFICIAL",
                    "adjust_type": "NONE",
                    "quality_status": "FRESH",
                    "delayed": True,
                    "currency": "CNY",
                }
            )
        return rows
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, InvalidOperation):
        raise BusinessError(
            "日线数据源请求失败或数据校验未通过，未写入；请检查代码或稍后重试"
        ) from None


def import_daily(db: Session, instrument: Instrument, start: date, end: date) -> dict:
    if start > end or (end - start).days > 366 or end >= date.today():
        raise BusinessError("仅支持过去已结束日期，单次范围不超过 366 天")
    rows = fetch_daily(instrument, start, end)
    inserted = 0
    # Never silently revise source/day facts; ON CONFLICT handles concurrent imports.
    for row in rows:
        result = db.execute(
            insert(MarketQuote).values(**row).on_conflict_do_nothing().returning(MarketQuote.id)
        ).scalar_one_or_none()
        inserted += result is not None
    record_audit(db, "market.daily.import", "instrument", str(instrument.id))
    db.commit()
    return {
        "provider": PROVIDER,
        "received": len(rows),
        "inserted": inserted,
        "skipped": len(rows) - inserted,
        "start": start,
        "end": end,
    }
