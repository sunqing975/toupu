import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _unique_name() -> str:
    return f"测试账户-{uuid.uuid4().hex[:8]}"


def test_account_crud() -> None:
    body = {"name": _unique_name(), "account_type": "BROKER", "notes": "测试用"}
    resp = client.post("/api/v1/accounts", json=body)
    assert resp.status_code == 201, resp.text
    account = resp.json()
    assert account["status"] == "ACTIVE"
    assert account["currency"] == "CNY"

    resp = client.get(f"/api/v1/accounts/{account['id']}")
    assert resp.status_code == 200

    resp = client.patch(f"/api/v1/accounts/{account['id']}", json={"status": "FROZEN"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "FROZEN"

    resp = client.get("/api/v1/accounts")
    assert resp.status_code == 200
    assert any(a["id"] == account["id"] for a in resp.json())

    resp = client.delete(f"/api/v1/accounts/{account['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/v1/accounts/{account['id']}").status_code == 404


def test_duplicate_account_name_rejected() -> None:
    name = _unique_name()
    first = client.post("/api/v1/accounts", json={"name": name, "account_type": "BANK"})
    assert first.status_code == 201
    resp = client.post("/api/v1/accounts", json={"name": name, "account_type": "BANK"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "HTTP_ERROR"


def test_invalid_account_type_rejected() -> None:
    resp = client.post("/api/v1/accounts", json={"name": _unique_name(), "account_type": "STOCK"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
