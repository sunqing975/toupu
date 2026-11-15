import json
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.errors import BusinessError
from app.instruments.models import Instrument
from app.main import app
from app.market_data import ingestion


def test_daily_parser_validates_source_and_close(monkeypatch):
    original = httpx.Client
    payload = {"data": {"code": "600000", "klines": ["2026-01-02,9.9,10.123456"]}}
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=json.dumps(payload).encode())

    monkeypatch.setattr(
        ingestion.httpx,
        "Client",
        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)),
    )
    instrument = Instrument(
        id=uuid.uuid4(),
        instrument_type="STOCK",
        market="CN",
        currency="CNY",
        code="600000",
        exchange="SH",
    )
    rows = ingestion.fetch_daily(instrument, date(2026, 1, 1), date(2026, 1, 5))
    assert rows[0]["price"] == Decimal("10.123456")
    assert requests[0].url.params["fqt"] == "0"
    assert requests[0].url.params["secid"] == "1.600000"
    payload["data"]["klines"] = ["2026-01-02,9.9,NaN"]
    with pytest.raises(BusinessError):
        ingestion.fetch_daily(instrument, date(2026, 1, 1), date(2026, 1, 5))
    instrument.instrument_type = "FUND"
    with pytest.raises(BusinessError):
        ingestion.fetch_daily(instrument, date(2026, 1, 1), date(2026, 1, 5))


def test_daily_import_idempotent_and_future_rejected(monkeypatch):
    client = TestClient(app)
    instrument = client.post(
        "/api/v1/instruments",
        json={
            "instrument_type": "STOCK",
            "market": "CN",
            "exchange": "SH",
            "code": uuid.uuid4().hex[:10],
            "name": "import-test",
        },
    ).json()

    def fetch(item, start, end):
        return [
            {
                "instrument_id": item.id,
                "quote_date": date(2026, 1, 2),
                "price": Decimal("10.12"),
                "provider": "EASTMONEY",
                "data_type": "OFFICIAL",
                "adjust_type": "NONE",
                "quality_status": "FRESH",
                "delayed": True,
                "currency": "CNY",
            }
        ]

    monkeypatch.setattr(ingestion, "fetch_daily", fetch)
    payload = {"instrument_id": instrument["id"], "start": "2026-01-01", "end": "2026-01-05"}
    first = client.post("/api/v1/market/import-daily", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["inserted"] == 1
    assert client.post("/api/v1/market/import-daily", json=payload).json()["skipped"] == 1
    payload["end"] = date.today().isoformat()
    assert client.post("/api/v1/market/import-daily", json=payload).status_code == 409
