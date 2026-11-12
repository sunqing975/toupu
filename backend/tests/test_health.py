from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "toupu"


def test_error_response_is_unified() -> None:
    resp = client.get("/not-exists")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"
