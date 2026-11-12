"""M2 验收：证券买卖过账、移动加权平均成本、持仓聚合、冲正限制。"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _account(name: str) -> str:
    resp = client.post("/api/v1/accounts", json={"name": name, "account_type": "BROKER"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _instrument(name: str, code: str, itype: str = "STOCK") -> dict:
    resp = client.post(
        "/api/v1/instruments",
        json={"instrument_type": itype, "market": "CN", "code": code, "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create(txn_type: str, account_id: str, instrument_id: str, executions: list[dict]) -> dict:
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": txn_type,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "business_date": "2026-11-12",
            "executions": executions,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _post(txn_id: str) -> dict:
    # 过账前必须先确认（M1 状态机：DRAFT→CONFIRMED→POSTED）
    assert client.post(f"/api/v1/transactions/{txn_id}/confirm").status_code == 200
    resp = client.post(f"/api/v1/transactions/{txn_id}/post")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _positions(account_id: str) -> list[dict]:
    resp = client.get("/api/v1/positions", params={"account_id": account_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_buy_two_executions_cost_avg() -> None:
    acc = _account(f"证券买入-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"贵州茅台{uuid.uuid4().hex[:4]}", f"6{uuid.uuid4().int % 100000:05d}")

    # 100@10 费5 + 100@12 无费 → 总成本 2205，持仓 200，单位成本 11.025
    txn = _create(
        "STOCK_BUY",
        acc,
        inst["id"],
        [
            {"execution_date": "2026-11-12", "quantity": "100", "price": "10", "fee_amount": "5"},
            {"execution_date": "2026-11-12", "quantity": "100", "price": "12"},
        ],
    )
    assert txn["total_amount"] == "2205.000000"
    assert len(txn["executions"]) == 2

    _post(txn["id"])
    positions = _positions(acc)
    assert len(positions) == 1
    pos = positions[0]
    assert pos["quantity"] == "200.000000"
    assert pos["total_cost"] == "2205.000000"
    assert pos["unit_cost"] == "11.025000"


def test_sell_partial_realized_loss() -> None:
    acc = _account(f"部分卖出-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"测试股份{uuid.uuid4().hex[:4]}", f"0{uuid.uuid4().int % 100000:05d}")
    buy = _create(
        "STOCK_BUY",
        acc,
        inst["id"],
        [
            {"execution_date": "2026-11-10", "quantity": "100", "price": "10", "fee_amount": "5"},
            {"execution_date": "2026-11-11", "quantity": "100", "price": "12"},
        ],
    )
    _post(buy["id"])

    # 卖 50@11 费5：net 545，成本出库 551.25，已实现亏损 6.25
    sell = _create(
        "STOCK_SELL",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-12", "quantity": "50", "price": "11", "fee_amount": "5"}],
    )
    detail = _post(sell["id"])

    names = {
        ln["ledger_account_name"]: (ln["direction"], ln["amount"])
        for ln in detail["entry"]["lines"]
    }
    # 借现金 545；证券科目出库成本 551.25；差额记已实现损失（借方）
    loss_lines = [v for k, v in names.items() if "已实现损失" in k]
    assert len(loss_lines) == 1 and loss_lines[0][0] == "DEBIT"
    assert loss_lines[0][1] == "6.250000"

    pos = _positions(acc)[0]
    assert pos["quantity"] == "150.000000"
    assert pos["total_cost"] == "1653.750000"
    assert pos["unit_cost"] == "11.025000"


def test_full_liquidation_clears_position() -> None:
    acc = _account(f"清仓-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"清仓样本{uuid.uuid4().hex[:4]}", f"3{uuid.uuid4().int % 100000:05d}")

    # 建仓 200 股：100@10 费5 + 100@12 → 总成本 2205、单位成本 11.025
    buy = _create(
        "STOCK_BUY",
        acc,
        inst["id"],
        [
            {"execution_date": "2026-11-10", "quantity": "100", "price": "10", "fee_amount": "5"},
            {"execution_date": "2026-11-11", "quantity": "100", "price": "12"},
        ],
    )
    _post(buy["id"])

    # 先部分卖出 50@11 费5：净 545、出库成本 551.25、已实现亏损 6.25；剩余 150 股、成本 1653.75
    partial = _create(
        "STOCK_SELL",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-12", "quantity": "50", "price": "11", "fee_amount": "5"}],
    )
    _post(partial["id"])

    # 清仓剩余 150@11.5：net 1725，成本出库 = 剩余总成本 1653.75（尾差归零），收益 71.25
    sell = _create(
        "STOCK_SELL",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-13", "quantity": "150", "price": "11.5"}],
    )
    detail = _post(sell["id"])
    gain_lines = [
        ln for ln in detail["entry"]["lines"] if ln["ledger_account_name"] == "已实现收益"
    ]
    assert len(gain_lines) == 1
    assert gain_lines[0]["amount"] == "71.250000"
    assert gain_lines[0]["direction"] == "CREDIT"

    assert _positions(acc) == []


def test_sell_more_than_held_rejected() -> None:
    acc = _account(f"超卖-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"超卖样本{uuid.uuid4().hex[:4]}", f"6{uuid.uuid4().int % 100000:05d}")
    buy = _create(
        "STOCK_BUY",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-10", "quantity": "100", "price": "10"}],
    )
    _post(buy["id"])

    sell = _create(
        "STOCK_SELL",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-12", "quantity": "200", "price": "10"}],
    )
    client.post(f"/api/v1/transactions/{sell['id']}/confirm")
    resp = client.post(f"/api/v1/transactions/{sell['id']}/post")
    assert resp.status_code == 409
    assert "持仓不足" in resp.json()["error"]["message"]


def test_sell_reversal_not_allowed() -> None:
    acc = _account(f"卖出冲正-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"冲正样本{uuid.uuid4().hex[:4]}", f"6{uuid.uuid4().int % 100000:05d}")
    buy = _create(
        "STOCK_BUY",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-10", "quantity": "100", "price": "10"}],
    )
    _post(buy["id"])
    sell = _create(
        "STOCK_SELL",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-12", "quantity": "50", "price": "11"}],
    )
    _post(sell["id"])

    resp = client.post(f"/api/v1/transactions/{sell['id']}/reverse")
    assert resp.status_code == 409
    assert "暂不开放" in resp.json()["error"]["message"]


def test_buy_reversal_restores_position() -> None:
    acc = _account(f"买入冲正-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"冲正回购{uuid.uuid4().hex[:4]}", f"6{uuid.uuid4().int % 100000:05d}")
    buy = _create(
        "STOCK_BUY",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-10", "quantity": "100", "price": "10"}],
    )
    _post(buy["id"])

    resp = client.post(f"/api/v1/transactions/{buy['id']}/reverse")
    assert resp.status_code == 200, resp.text
    assert _positions(acc) == []

    # 已被消耗的批次不能冲正
    buy2 = _create(
        "STOCK_BUY",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-11", "quantity": "100", "price": "10"}],
    )
    _post(buy2["id"])
    sell = _create(
        "STOCK_SELL",
        acc,
        inst["id"],
        [{"execution_date": "2026-11-12", "quantity": "60", "price": "11"}],
    )
    _post(sell["id"])
    resp = client.post(f"/api/v1/transactions/{buy2['id']}/reverse")
    assert resp.status_code == 409
    assert "已被卖出" in resp.json()["error"]["message"]


def test_security_validation() -> None:
    acc = _account(f"校验-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"校验样本{uuid.uuid4().hex[:4]}", f"6{uuid.uuid4().int % 100000:05d}")

    # 缺 instrument_id / 缺成交 → 422
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "STOCK_BUY",
            "account_id": acc,
            "business_date": "2026-11-12",
            "executions": [{"execution_date": "2026-11-12", "quantity": "1", "price": "1"}],
        },
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "STOCK_BUY",
            "account_id": acc,
            "instrument_id": inst["id"],
            "business_date": "2026-11-12",
            "executions": [],
        },
    )
    assert resp.status_code == 422

    # instrument 不存在 → 404
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "STOCK_BUY",
            "account_id": acc,
            "instrument_id": str(uuid.uuid4()),
            "business_date": "2026-11-12",
            "executions": [{"execution_date": "2026-11-12", "quantity": "1", "price": "1"}],
        },
    )
    assert resp.status_code == 404

    # 现金业务带成交 → 422
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "DEPOSIT",
            "account_id": acc,
            "business_date": "2026-11-12",
            "amount": "100",
            "executions": [{"execution_date": "2026-11-12", "quantity": "1", "price": "1"}],
        },
    )
    assert resp.status_code == 422
