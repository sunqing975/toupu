"""M5 验收：行情/净值录入、估值覆盖状态、快照幂等重建、收益指标 API。

注意：测试与 dev 共用 toupu 库，derive() 是全库派生（现金/持仓/科目余额都是全局合计），
因此本文件只断言「自己创建的标的行/自己的效应」，绝不断言全局总金额。
依据 docs/ledger-rules.md §13 / §17.7 / §17.9。
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.performance.service import external_cashflows

client = TestClient(app)

AS_OF = "2026-11-13"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _account(account_type: str = "BROKER") -> str:
    resp = client.post(
        "/api/v1/accounts",
        json={"name": f"M5账户-{_uid()}", "account_type": account_type},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _instrument(instrument_type: str = "STOCK") -> dict:
    resp = client.post(
        "/api/v1/instruments",
        json={
            "instrument_type": instrument_type,
            "market": "CN",
            "code": _uid(),
            "name": f"M5品种{_uid()}",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _buy(account_id: str, instrument_id: str, price: str = "10", qty: str = "100") -> dict:
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "STOCK_BUY",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "business_date": AS_OF,
            "executions": [{"execution_date": AS_OF, "quantity": qty, "price": price}],
        },
    )
    assert resp.status_code == 201, resp.text
    txn_id = resp.json()["id"]
    assert client.post(f"/api/v1/transactions/{txn_id}/confirm").status_code == 200
    posted = client.post(f"/api/v1/transactions/{txn_id}/post")
    assert posted.status_code == 200, posted.text
    return posted.json()


def _setup_position(price: str = "10") -> tuple[str, dict]:
    account_id = _account()
    instrument = _instrument()
    _buy(account_id, instrument["id"], price=price)
    return account_id, instrument


def _quote(instrument_id: str, quote_date: str, price: str, **kwargs: object) -> dict:
    payload = {
        "instrument_id": instrument_id,
        "quote_date": quote_date,
        "price": price,
    }
    payload.update(kwargs)
    resp = client.post("/api/v1/market/quotes", json=payload)
    return resp


def _valuation(as_of: str = AS_OF, stale_days: int = 7) -> dict:
    resp = client.get(
        "/api/v1/market/valuation",
        params={"as_of": as_of, "stale_days": stale_days},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _find_row(data: dict, instrument_id: str) -> dict:
    return next(row for row in data["positions"] if row["instrument_id"] == instrument_id)


# ---- 行情/净值录入（正常 + 边界 + 幂等校验）----


def test_create_and_list_quote() -> None:
    instrument = _instrument()
    resp = _quote(instrument["id"], AS_OF, "12.5", provider="MANUAL", provider_code="600519")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["price"] == "12.500000"
    assert body["data_type"] == "OFFICIAL"
    assert body["adjust_type"] == "NONE"
    assert body["quality_status"] == "FRESH"

    listed = client.get("/api/v1/market/quotes", params={"instrument_id": instrument["id"]})
    assert listed.status_code == 200
    assert any(row["id"] == body["id"] for row in listed.json())


def test_quote_official_must_be_unadjusted() -> None:
    instrument = _instrument()
    resp = _quote(instrument["id"], AS_OF, "12", data_type="OFFICIAL", adjust_type="PRE")
    assert resp.status_code == 409
    assert "未复权" in resp.json()["error"]["message"]


def test_duplicate_quote_rejected() -> None:
    instrument = _instrument()
    assert _quote(instrument["id"], AS_OF, "12").status_code == 201
    resp = _quote(instrument["id"], AS_OF, "13")
    assert resp.status_code == 409
    assert "行情已存在" in resp.json()["error"]["message"]


def test_quote_price_must_be_positive() -> None:
    instrument = _instrument()
    resp = _quote(instrument["id"], AS_OF, "-1")
    assert resp.status_code == 422


def test_nav_only_for_fund_instrument() -> None:
    stock = _instrument("STOCK")
    resp = client.post(
        "/api/v1/market/navs",
        json={"instrument_id": stock["id"], "nav_date": AS_OF, "nav": "1.5"},
    )
    assert resp.status_code == 409
    assert "FUND" in resp.json()["error"]["message"]

    fund = _instrument("FUND")
    resp = client.post(
        "/api/v1/market/navs",
        json={
            "instrument_id": fund["id"],
            "nav_date": AS_OF,
            "nav": "1.500000",
            "accumulated_nav": "2.000000",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["nav"] == "1.500000"


# ---- 估值覆盖状态：FRESH / STALE / UNKNOWN / ESTIMATED ----


def test_valuation_quote_statuses() -> None:
    account_id = _account()
    fresh = _instrument()
    stale = _instrument()
    unknown = _instrument()
    estimated = _instrument()
    for inst in (fresh, stale, unknown, estimated):
        _buy(account_id, inst["id"])

    # FRESH：报价日期 = as_of
    assert _quote(fresh["id"], AS_OF, "12").status_code == 201
    # STALE：报价日期早于 as_of 超过 stale_days（存储质量仍为 FRESH）
    assert _quote(stale["id"], "2026-10-01", "12").status_code == 201
    # UNKNOWN：不录报价
    # ESTIMATED：仅盘中估值，不用于估值
    assert _quote(estimated["id"], AS_OF, "12", data_type="ESTIMATED").status_code == 201

    data = _valuation()
    f_row = _find_row(data, fresh["id"])
    assert f_row["quote"]["status"] == "FRESH"
    assert f_row["valued"] is True
    assert f_row["market_value"] == "1200.000000"  # 100 × 12
    assert f_row["unrealized"] == "200.000000"  # 成本 1000

    s_row = _find_row(data, stale["id"])
    assert s_row["quote"]["status"] == "STALE"
    assert s_row["valued"] is True  # STALE 仍计入估值，但要标状态
    assert s_row["market_value"] == "1200.000000"

    u_row = _find_row(data, unknown["id"])
    assert u_row["quote"]["status"] == "UNKNOWN"
    assert u_row["valued"] is False
    assert u_row["market_value"] is None

    e_row = _find_row(data, estimated["id"])
    assert e_row["quote"]["status"] == "ESTIMATED"
    assert e_row["valued"] is False
    assert e_row["market_value"] is None  # 盘中估值不用于核算

    assert data["data_quality"] in {"COMPLETE", "PARTIAL", "NO_QUOTES"}
    assert data["coverage"] != "" and Decimal(data["coverage"]) <= 1


def test_valuation_missing_quote_is_not_silently_zero() -> None:
    """无报价持仓必须从市值合计排除，且六位小数口径不被 0 冒充。"""
    _, instrument = _setup_position()
    data = _valuation()
    row = _find_row(data, instrument["id"])
    assert row["market_value"] is None
    assert row["unrealized"] is None
    # 汇总数字自身始终保持六位小数
    assert len(data["cash_total"].split(".")[-1]) == 6


# ---- 快照：幂等重建、可删除重建、不写账本 ----


def test_rebuild_is_idempotent() -> None:
    account_id, instrument = _setup_position()
    assert _quote(instrument["id"], AS_OF, "12").status_code == 201

    first = client.post("/api/v1/snapshots/rebuild", json={"snapshot_date": AS_OF})
    assert first.status_code == 200, first.text
    first_positions = first.json()["positions"]
    mine_first = [r for r in first_positions if r["instrument_id"] == instrument["id"]]
    assert len(mine_first) == 1
    assert mine_first[0]["quote_status"] == "FRESH"
    assert mine_first[0]["market_value"] == "1200.000000"

    # 同日重复重建：先删后建，不产生重复行
    second = client.post("/api/v1/snapshots/rebuild", json={"snapshot_date": AS_OF})
    assert second.status_code == 200, second.text
    assert len(second.json()["positions"]) == len(first_positions)

    rows = client.get(f"/api/v1/snapshots/{AS_OF}/positions")
    assert rows.status_code == 200
    mine = [r for r in rows.json() if r["instrument_id"] == instrument["id"]]
    assert len(mine) == 1
    assert mine[0]["account_id"] == account_id

    listed = client.get("/api/v1/snapshots")
    assert listed.status_code == 200
    assert any(s["snapshot_date"] == AS_OF for s in listed.json())


def test_snapshot_contains_only_derived_fields() -> None:
    """快照是派生结果：只读取账本/批次/行情，不改动交易或批次。"""
    _, instrument = _setup_position()
    positions_before = client.get("/api/v1/positions").json()
    client.post("/api/v1/snapshots/rebuild", json={"snapshot_date": AS_OF})
    positions_after = client.get("/api/v1/positions").json()
    assert positions_after == positions_before
    assert any(row["instrument_id"] == instrument["id"] for row in positions_after)


# ---- 收益指标 API：结构、状态、缺失处理 ----


def test_summary_structure_and_six_decimals() -> None:
    resp = client.get("/api/v1/performance/summary", params={"as_of": AS_OF})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "cash_total",
        "market_value",
        "total_assets",
        "realized_total",
        "dividend_income",
        "unrealized_total",
        "book_cost_total",
    ):
        assert len(body[key].split(".")[-1]) == 6
    assert body["data_quality"] in {"COMPLETE", "PARTIAL", "NO_QUOTES"}
    assert Decimal(body["coverage"]) <= 1


def test_returns_metrics_have_status() -> None:
    """估值覆盖不全时 XIRR 返回 INSUFFICIENT_DATA，不输出看似合理的数字。"""
    resp = client.get("/api/v1/performance/returns", params={"as_of": AS_OF})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("xirr", "twr", "max_drawdown"):
        assert body[key]["status"] in {"OK", "INSUFFICIENT_DATA", "NO_SOLUTION"}
    # 全库 200+ 持仓、仅少数有报价 → 覆盖率必然 < 1
    assert body["xirr"]["status"] == "INSUFFICIENT_DATA"
    assert body["xirr"]["value"] is None
    assert body["xirr"]["reason"]


# ---- 外部现金流边界（§17.3）：转账不算外部现金流 ----


def test_external_cashflows_sign_and_transfer_exclusion() -> None:
    account_id = _account()
    counter_id = _account()
    dep_date = "2026-03-07"
    dep_amount = Decimal("864209.753186")
    trf_date = "2026-03-08"
    trf_amount = Decimal("531800.642857")

    dep = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "DEPOSIT",
            "account_id": account_id,
            "business_date": dep_date,
            "amount": str(dep_amount),
        },
    )
    assert dep.status_code == 201, dep.text
    assert client.post(f"/api/v1/transactions/{dep.json()['id']}/confirm").status_code == 200
    assert client.post(f"/api/v1/transactions/{dep.json()['id']}/post").status_code == 200

    trf = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "ACCOUNT_TRANSFER",
            "account_id": account_id,
            "counter_account_id": counter_id,
            "business_date": trf_date,
            "amount": str(trf_amount),
        },
    )
    assert trf.status_code == 201, trf.text
    assert client.post(f"/api/v1/transactions/{trf.json()['id']}/confirm").status_code == 200
    assert client.post(f"/api/v1/transactions/{trf.json()['id']}/post").status_code == 200

    db = SessionLocal()
    try:
        flows, has_capital = external_cashflows(db, date(2026, 11, 13))
    finally:
        db.close()
    # DEPOSIT：投入为负
    assert (date(2026, 3, 7), -dep_amount) in flows
    # ACCOUNT_TRANSFER：绝不作为外部现金流
    assert all(amount not in (trf_amount, -trf_amount) for _, amount in flows)
    assert has_capital is True
