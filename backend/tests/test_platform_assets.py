"""Platform evidence must never create fake ledger positions."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import SessionLocal
from app.main import app


def payload(client):
    account = client.post(
        "/api/v1/accounts",
        json={"name": "platform-" + uuid.uuid4().hex, "account_type": "FUND_PLATFORM"},
    ).json()
    return {
        "account_id": account["id"],
        "observed_on": "2026-11-14",
        "source": "test screenshot",
        "request_key": uuid.uuid4().hex,
        "items": [
            {
                "name": "测试基金",
                "kind": "FUND",
                "code": "008585",
                "market_value": "12068.73",
                "holding_pnl": "-1529.32",
                "cumulative_pnl": "303.45",
            }
        ],
    }


def test_exact_snapshot_replay_and_no_ledger_side_effect():
    with TestClient(app) as client, SessionLocal() as db:
        p = payload(client)
        tables = ["investment_transactions", "journal_entries", "position_lots"]
        before = [db.scalar(text("select count(*) from " + t)) for t in tables]
        r = client.post("/api/v1/platform-assets", json=p)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["market_value"] == "12068.73"
        assert data["holding_pnl"] == "-1529.32"
        assert data["items"][0]["reference_cost"] == "13598.05"
        assert data["items"][0]["quantity"] is None
        assert data["ledger_included"] is False
        assert client.post("/api/v1/platform-assets", json=p).json()["id"] == data["id"]
        assert before == [db.scalar(text("select count(*) from " + t)) for t in tables]
        p["items"][0]["market_value"] = "12000.00"
        assert client.post("/api/v1/platform-assets", json=p).status_code == 409
        p["request_key"] = uuid.uuid4().hex
        assert client.post("/api/v1/platform-assets", json=p).status_code == 409


def test_validation_and_atomic_audit_failure(monkeypatch):
    with TestClient(app, raise_server_exceptions=False) as client, SessionLocal() as db:
        p = payload(client)
        p["items"] *= 2
        assert client.post("/api/v1/platform-assets", json=p).status_code == 422
        p["items"] = p["items"][:1]
        p["items"][0]["kind"] = "ADVISORY"
        assert client.post("/api/v1/platform-assets", json=p).status_code == 422
        p["items"][0]["kind"] = "FUND"
        p["items"][0]["market_value"] = "NaN"
        assert client.post("/api/v1/platform-assets", json=p).status_code == 422
        p["items"][0]["market_value"] = "10.00"
        from app.imports import platform_assets

        def fail(*args, **kwargs):
            raise RuntimeError("audit unavailable")

        monkeypatch.setattr(platform_assets, "record_audit", fail)
        assert client.post("/api/v1/platform-assets", json=p).status_code == 500
        assert (
            db.scalar(
                text("SELECT count(*) FROM platform_asset_batches WHERE request_key=:k"),
                {"k": p["request_key"]},
            )
            == 0
        )
