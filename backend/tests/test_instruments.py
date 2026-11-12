import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_instrument_create_and_duplicate_rejected() -> None:
    code = f"TS{uuid.uuid4().hex[:6]}"
    body = {"instrument_type": "STOCK", "market": "CN", "code": code, "name": "测试标的"}
    resp = client.post("/api/v1/instruments", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "ACTIVE"

    resp = client.post("/api/v1/instruments", json=body)
    assert resp.status_code == 409

    listed = client.get("/api/v1/instruments", params={"instrument_type": "STOCK"})
    assert listed.status_code == 200
    assert any(i["code"] == code for i in listed.json())


def test_fund_without_exchange_ok() -> None:
    code = f"FD{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/api/v1/instruments",
        json={"instrument_type": "FUND", "market": "CN", "code": code, "name": "测试基金"},
    )
    assert resp.status_code == 201
    assert resp.json()["exchange"] is None
