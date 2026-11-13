"""M1 验收：现金入金/出金/转账记账、幂等、平衡校验、冲正、精度。"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _account(name: str) -> str:
    resp = client.post("/api/v1/accounts", json={"name": name, "account_type": "BROKER"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create(txn_type: str, account_id: str, amount: str, **kw) -> dict:
    body = {
        "transaction_type": txn_type,
        "account_id": account_id,
        "business_date": "2026-11-12",
        "amount": amount,
        **kw,
    }
    resp = client.post("/api/v1/transactions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _confirm(txn_id: str) -> None:
    assert client.post(f"/api/v1/transactions/{txn_id}/confirm").status_code == 200


def _post(txn_id: str) -> dict:
    resp = client.post(f"/api/v1/transactions/{txn_id}/post")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _cash_lines(detail: dict) -> list[tuple[str, str]]:
    return [
        (ln["direction"], ln["amount"])
        for ln in detail["entry"]["lines"]
        if ln["ledger_account_name"].startswith("现金·")
    ]


def test_deposit_full_flow() -> None:
    acc = _account(f"入金测试-{uuid.uuid4().hex[:6]}")
    txn = _create("DEPOSIT", acc, "10000.00")
    assert txn["status"] == "DRAFT"

    # 草稿不能直接过账
    resp = client.post(f"/api/v1/transactions/{txn['id']}/post")
    assert resp.status_code == 409

    _confirm(txn["id"])
    detail = _post(txn["id"])
    assert detail["status"] == "POSTED"

    # 借现金 贷 外部资金平衡，借贷平衡
    lines = detail["entry"]["lines"]
    debit = sum(float(ln["amount"]) for ln in lines if ln["direction"] == "DEBIT")
    credit = sum(float(ln["amount"]) for ln in lines if ln["direction"] == "CREDIT")
    assert debit == credit == 10000.0
    assert _cash_lines(detail) == [("DEBIT", "10000.000000")]


def test_double_post_is_idempotent() -> None:
    acc = _account(f"幂等测试-{uuid.uuid4().hex[:6]}")
    txn = _create("DEPOSIT", acc, "100")
    _confirm(txn["id"])
    first = _post(txn["id"])
    second = _post(txn["id"])
    assert first["entry"]["id"] == second["entry"]["id"]


def test_withdraw_and_transfer() -> None:
    a = _account(f"转账A-{uuid.uuid4().hex[:6]}")
    b = _account(f"转账B-{uuid.uuid4().hex[:6]}")
    _confirm(_create("DEPOSIT", a, "5000")["id"])

    w = _create("WITHDRAW", a, "1000")
    _confirm(w["id"])
    detail = _post(w["id"])
    assert _cash_lines(detail) == [("CREDIT", "1000.000000")]

    t = _create("ACCOUNT_TRANSFER", a, "2000", counter_account_id=b)
    _confirm(t["id"])
    detail = _post(t["id"])
    # 转出贷、转入借
    assert _cash_lines(detail) == [("DEBIT", "2000.000000"), ("CREDIT", "2000.000000")]


def test_transfer_requires_counter_account() -> None:
    acc = _account(f"无转入账户-{uuid.uuid4().hex[:6]}")
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "ACCOUNT_TRANSFER",
            "account_id": acc,
            "business_date": "2026-11-12",
            "amount": "100",
        },
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "ACCOUNT_TRANSFER",
            "account_id": acc,
            "counter_account_id": acc,
            "business_date": "2026-11-12",
            "amount": "100",
        },
    )
    assert resp.status_code == 409  # 相同账户


def test_unbalanced_lines_rejected(monkeypatch) -> None:
    from app.ledger import service as ledger_service

    acc = _account(f"不平衡测试-{uuid.uuid4().hex[:6]}")
    txn = _create("DEPOSIT", acc, "100")
    _confirm(txn["id"])

    def bad_lines(db, t):  # 故意生成不平衡分录
        cash = ledger_service.get_or_create_cash(db, t.account_id)
        return [(cash, "DEBIT", t.total_amount), (cash, "DEBIT", t.total_amount)]

    monkeypatch.setitem(ledger_service.HANDLERS, "DEPOSIT", bad_lines)
    resp = client.post(f"/api/v1/transactions/{txn['id']}/post")
    assert resp.status_code == 409
    assert "借贷不平衡" in resp.json()["error"]["message"]
    # 状态未变、无分录
    detail = client.get(f"/api/v1/transactions/{txn['id']}").json()
    assert detail["status"] == "CONFIRMED"
    assert detail["entry"] is None


def test_reverse_flow() -> None:
    acc = _account(f"冲正测试-{uuid.uuid4().hex[:6]}")
    txn = _create("DEPOSIT", acc, "300")
    _confirm(txn["id"])
    _post(txn["id"])

    resp = client.post(f"/api/v1/transactions/{txn['id']}/reverse")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "REVERSED"

    detail = client.get(f"/api/v1/transactions/{txn['id']}").json()
    assert detail["entry"]["entry_type"] == "NORMAL"
    # 冲正交易存在且已入账，分录为 REVERSAL（按账户过滤，避免被列表 100 条上限截断）
    reversal = client.get(
        "/api/v1/transactions", params={"status_filter": "POSTED", "account_id": acc}
    ).json()
    rev = [t for t in reversal if str(t["reversal_of_id"]) == txn["id"]]
    assert len(rev) == 1
    rev_detail = client.get(f"/api/v1/transactions/{rev[0]['id']}").json()
    assert rev_detail["entry"]["entry_type"] == "REVERSAL"

    # 不能重复冲正；冲正交易也不能再冲正
    assert client.post(f"/api/v1/transactions/{txn['id']}/reverse").status_code == 409
    assert client.post(f"/api/v1/transactions/{rev[0]['id']}/reverse").status_code == 409


def test_cancel_rules() -> None:
    acc = _account(f"取消测试-{uuid.uuid4().hex[:6]}")
    draft = _create("DEPOSIT", acc, "50")
    assert client.post(f"/api/v1/transactions/{draft['id']}/cancel").status_code == 200

    posted = _create("DEPOSIT", acc, "60")
    _confirm(posted["id"])
    _post(posted["id"])
    resp = client.post(f"/api/v1/transactions/{posted['id']}/cancel")
    assert resp.status_code == 409


def test_amount_precision_and_validation() -> None:
    acc = _account(f"精度测试-{uuid.uuid4().hex[:6]}")
    txn = _create("DEPOSIT", acc, "1000.005")
    detail = client.get(f"/api/v1/transactions/{txn['id']}").json()
    assert detail["total_amount"] == "1000.005000"

    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "DEPOSIT",
            "account_id": acc,
            "business_date": "2026-11-12",
            "amount": "0",
        },
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "DEPOSIT",
            "account_id": acc,
            "business_date": "2026-11-12",
            "amount": "-5",
        },
    )
    assert resp.status_code == 422


def test_audit_trail_written() -> None:
    acc = _account(f"审计测试-{uuid.uuid4().hex[:6]}")
    txn = _create("DEPOSIT", acc, "10")
    _confirm(txn["id"])
    _post(txn["id"])
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        actions = {
            r[0]
            for r in db.execute(
                text(
                    "SELECT action FROM audit_logs "
                    "WHERE entity_id = :eid AND action LIKE 'transaction.%'"
                ),
                {"eid": txn["id"]},
            )
        }
    assert {"transaction.confirm", "transaction.post"} <= actions
