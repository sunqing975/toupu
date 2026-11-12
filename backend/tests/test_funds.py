"""M3 验收：场外基金申购/赎回/分红、两段式确认、金额守恒、移动加权平均成本、冲正限制。

依据 docs/ledger-rules.md §15 与 agent.md §9：正常 / 边界 / 幂等 / 回滚 / 冲正 / 精度。
"""

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from httpx import Response

from app.main import app

client = TestClient(app)


def _account(name: str) -> str:
    resp = client.post("/api/v1/accounts", json={"name": name, "account_type": "FUND_PLATFORM"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _fund(name: str, code: str) -> dict:
    resp = client.post(
        "/api/v1/instruments",
        json={"instrument_type": "FUND", "market": "CN", "code": code, "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _fund_setup() -> tuple[str, str]:
    """返回一组独立的 (账户 id, 基金标的 id)，避免与 dev 库既有数据冲突。"""
    suffix = uuid.uuid4().hex[:6]
    acc = _account(f"基金-{suffix}")
    inst = _fund(f"样本基金{suffix}", f"F{suffix}")
    return acc, inst["id"]


def _order_raw(ttype: str, account_id: str, instrument_id: str, **fields: object) -> Response:
    payload: dict = {
        "transaction_type": ttype,
        "account_id": account_id,
        "instrument_id": instrument_id,
        "business_date": "2026-11-12",
        **fields,
    }
    return client.post("/api/v1/funds/orders", json=payload)


def _order(ttype: str, account_id: str, instrument_id: str, **fields: object) -> dict:
    resp = _order_raw(ttype, account_id, instrument_id, **fields)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _confirmation_payload(
    confirmation_date: str,
    nav: str,
    confirmed_shares: str,
    confirmed_amount: str,
    fee_amount: str = "0",
) -> dict:
    return {
        "confirmation_date": confirmation_date,
        "nav": nav,
        "confirmed_shares": confirmed_shares,
        "confirmed_amount": confirmed_amount,
        "fee_amount": fee_amount,
    }


def _confirm(order_id: str, payload: dict) -> Response:
    return client.post(f"/api/v1/funds/orders/{order_id}/confirm", json=payload)


def _post(txn_id: str) -> dict:
    resp = client.post(f"/api/v1/transactions/{txn_id}/post")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _positions(account_id: str) -> list[dict]:
    resp = client.get("/api/v1/positions", params={"account_id": account_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _detail(order_id: str) -> dict:
    resp = client.get(f"/api/v1/funds/orders/{order_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _lines(detail: dict, name_contains: str) -> list[tuple[str, Decimal]]:
    return [
        (ln["direction"], Decimal(ln["amount"]))
        for ln in detail["entry"]["lines"]
        if name_contains in ln["ledger_account_name"]
    ]


def _subscribe(
    acc: str,
    inst: str,
    apply_amount: str,
    confirmed_amount: str,
    fee_amount: str,
    nav: str,
    shares: str,
    confirmation_date: str = "2026-11-10",
    idempotency_key: str | None = None,
) -> dict:
    fields: dict = {"apply_amount": apply_amount}
    if idempotency_key is not None:
        fields["idempotency_key"] = idempotency_key
    order = _order("FUND_SUBSCRIBE", acc, inst, **fields)
    resp = _confirm(
        order["id"],
        _confirmation_payload(confirmation_date, nav, shares, confirmed_amount, fee_amount),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()  # 返回确认后的详情（status=CONFIRMED、含确认数据）


def _redeem(
    acc: str,
    inst: str,
    confirmed_shares: str,
    confirmed_amount: str,
    fee_amount: str,
    nav: str,
    confirmation_date: str = "2026-11-12",
) -> dict:
    order = _order("FUND_REDEEM", acc, inst, apply_shares=confirmed_shares)
    resp = _confirm(
        order["id"],
        _confirmation_payload(
            confirmation_date, nav, confirmed_shares, confirmed_amount, fee_amount
        ),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_subscribe_confirm_post_and_precision() -> None:
    acc, inst = _fund_setup()
    order = _subscribe(acc, inst, "10050", "10000", "50", "2", "5000")
    assert order["status"] == "CONFIRMED"
    assert order["confirmation_status"] == "CONFIRMED"
    assert Decimal(order["apply_amount"]) == Decimal("10050")
    assert Decimal(order["total_amount"]) == Decimal("10050")
    assert Decimal(order["confirmation"]["nav"]) == Decimal("2")
    assert Decimal(order["confirmation"]["confirmed_shares"]) == Decimal("5000")
    assert Decimal(order["confirmation"]["confirmed_amount"]) == Decimal("10000")
    assert Decimal(order["confirmation"]["fee_amount"]) == Decimal("50")
    assert order["entry"] is None

    detail = _post(order["id"])
    assert detail["status"] == "POSTED"
    # 申购：借证券资产 = 实际扣款（含申购费），贷现金同额；费用不单独借记
    assert _lines(detail, "证券") == [("DEBIT", Decimal("10050"))]
    assert _lines(detail, "现金·") == [("CREDIT", Decimal("10050"))]
    assert len(detail["entry"]["lines"]) == 2

    # 六位小数精度：GET 详情从 DB 重新加载分录行（Decimal→JSON 字符串）
    fresh = _detail(order["id"])
    assert fresh["entry"]["lines"][0]["amount"] == "10050.000000"
    assert fresh["apply_amount"] == "10050.000000"

    pos = _positions(acc)
    assert len(pos) == 1
    assert pos[0]["quantity"] == "5000.000000"
    assert pos[0]["total_cost"] == "10050.000000"
    assert pos[0]["unit_cost"] == "2.010000"


def test_subscribe_amount_conservation_violation() -> None:
    acc, inst = _fund_setup()
    order = _order("FUND_SUBSCRIBE", acc, inst, apply_amount="10000")
    resp = _confirm(order["id"], _confirmation_payload("2026-11-10", "2", "5000", "9900", "0"))
    assert resp.status_code == 409
    assert "申购金额不守恒" in resp.json()["error"]["message"]
    assert _detail(order["id"])["status"] == "DRAFT"
    assert _positions(acc) == []


def test_generic_confirm_cannot_bypass_two_stage() -> None:
    acc, inst = _fund_setup()
    order = _order("FUND_SUBSCRIBE", acc, inst, apply_amount="10000")
    resp = client.post(f"/api/v1/transactions/{order['id']}/confirm")
    assert resp.status_code == 409
    assert "基金申请请通过基金确认接口" in resp.json()["error"]["message"]
    assert _detail(order["id"])["confirmation_status"] == "PENDING"


def test_post_before_confirmation_rejected() -> None:
    acc, inst = _fund_setup()
    order = _order("FUND_SUBSCRIBE", acc, inst, apply_amount="10000")
    resp = client.post(f"/api/v1/transactions/{order['id']}/post")
    assert resp.status_code == 409
    assert "交易未确认" in resp.json()["error"]["message"]
    assert _positions(acc) == []


def test_redeem_partial_realized_loss() -> None:
    acc, inst = _fund_setup()
    buy = _subscribe(acc, inst, "10050", "10000", "50", "2", "5000")
    _post(buy["id"])

    # 赎回 2000 份：净到账 3950，出库成本 4020，已实现亏损 70
    sell = _redeem(acc, inst, "2000", "4000", "50", "2")
    detail = _post(sell["id"])
    assert _lines(detail, "现金·") == [("DEBIT", Decimal("3950"))]
    assert _lines(detail, "证券") == [("CREDIT", Decimal("4020"))]
    assert _lines(detail, "已实现损失") == [("DEBIT", Decimal("70"))]
    assert not _lines(detail, "已实现收益")

    pos = _positions(acc)
    assert len(pos) == 1
    assert pos[0]["quantity"] == "3000.000000"
    assert pos[0]["total_cost"] == "6030.000000"
    assert pos[0]["unit_cost"] == "2.010000"


def test_two_lots_full_liquidation_tail_to_zero() -> None:
    acc, inst = _fund_setup()
    buy_a = _subscribe(acc, inst, "10000", "10000", "0", "2", "5000", "2026-11-10")
    buy_b = _subscribe(acc, inst, "10000", "10000", "0", "2.5", "4000", "2026-11-11")
    _post(buy_a["id"])
    _post(buy_b["id"])

    pos = _positions(acc)
    assert pos[0]["quantity"] == "9000.000000"
    assert pos[0]["total_cost"] == "20000.000000"

    # 部分赎回 3000 份：出库成本 6666.666667，收益 333.333333，剩余成本 13333.333333
    partial = _redeem(acc, inst, "3000", "7000", "0", "2.333333", "2026-11-12")
    detail = _post(partial["id"])
    assert _lines(detail, "现金·") == [("DEBIT", Decimal("7000"))]
    assert _lines(detail, "证券") == [("CREDIT", Decimal("6666.666667"))]
    assert _lines(detail, "已实现收益") == [("CREDIT", Decimal("333.333333"))]
    assert _positions(acc)[0]["total_cost"] == "13333.333333"

    # 清仓 6000 份：出库成本取剩余总成本（尾差归零），收益 666.666667
    full = _redeem(acc, inst, "6000", "14000", "0", "2.333333", "2026-11-13")
    detail = _post(full["id"])
    assert _lines(detail, "现金·") == [("DEBIT", Decimal("14000"))]
    assert _lines(detail, "证券") == [("CREDIT", Decimal("13333.333333"))]
    assert _lines(detail, "已实现收益") == [("CREDIT", Decimal("666.666667"))]
    assert _positions(acc) == []


def test_cash_dividend() -> None:
    acc, inst = _fund_setup()
    order = _order("CASH_DIVIDEND", acc, inst, apply_amount="500")
    # 现金分红创建即已确认（平台到账为既成事实）
    assert order["status"] == "CONFIRMED"
    assert order["confirmation_status"] == "CONFIRMED"
    assert order["confirmation"] is None

    detail = _post(order["id"])
    assert _lines(detail, "现金·") == [("DEBIT", Decimal("500"))]
    assert _lines(detail, "现金分红收入") == [("CREDIT", Decimal("500"))]
    assert len(detail["entry"]["lines"]) == 2
    assert _positions(acc) == []  # 不增加份额

    resp = _confirm(order["id"], _confirmation_payload("2026-11-12", "2", "1", "1"))
    assert resp.status_code == 409
    assert "现金分红无需确认" in resp.json()["error"]["message"]


def test_dividend_reinvest() -> None:
    acc, inst = _fund_setup()
    order = _order("DIVIDEND_REINVEST", acc, inst)
    assert order["status"] == "DRAFT"
    assert order["confirmation_status"] == "PENDING"
    assert order["apply_amount"] is None  # 确认前无实际金额，不猜测
    assert order["total_amount"] is None

    resp = _confirm(order["id"], _confirmation_payload("2026-11-12", "2.5", "200", "500"))
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["total_amount"]) == Decimal("500")

    detail = _post(order["id"])
    # 红利再投资：借证券资产、贷分红收入，不重复记现金
    assert _lines(detail, "证券") == [("DEBIT", Decimal("500"))]
    assert _lines(detail, "现金分红收入") == [("CREDIT", Decimal("500"))]
    assert not _lines(detail, "现金·")
    assert len(detail["entry"]["lines"]) == 2

    pos = _positions(acc)
    assert len(pos) == 1
    assert pos[0]["quantity"] == "200.000000"
    assert pos[0]["total_cost"] == "500.000000"
    assert pos[0]["unit_cost"] == "2.500000"


def test_redeem_more_than_held_rejected() -> None:
    acc, inst = _fund_setup()
    buy = _subscribe(acc, inst, "10000", "10000", "0", "2", "5000")
    _post(buy["id"])

    sell = _redeem(acc, inst, "6000", "12000", "0", "2")
    resp = client.post(f"/api/v1/transactions/{sell['id']}/post")
    assert resp.status_code == 409
    assert "持仓不足" in resp.json()["error"]["message"]
    # 失败后持仓不受影响
    assert _positions(acc)[0]["quantity"] == "5000.000000"


def test_redeem_net_must_be_positive() -> None:
    acc, inst = _fund_setup()
    buy = _subscribe(acc, inst, "10000", "10000", "0", "2", "5000")
    _post(buy["id"])

    sell = _redeem(acc, inst, "100", "100", "200", "2")
    resp = client.post(f"/api/v1/transactions/{sell['id']}/post")
    assert resp.status_code == 409
    assert "赎回净到账金额必须大于 0" in resp.json()["error"]["message"]


def test_redeem_reversal_not_allowed() -> None:
    acc, inst = _fund_setup()
    buy = _subscribe(acc, inst, "10000", "10000", "0", "2", "5000")
    _post(buy["id"])
    sell = _redeem(acc, inst, "1000", "2000", "0", "2")
    _post(sell["id"])

    resp = client.post(f"/api/v1/transactions/{sell['id']}/reverse")
    assert resp.status_code == 409
    assert "暂不开放" in resp.json()["error"]["message"]


def test_subscribe_reversal_restores_position() -> None:
    acc, inst = _fund_setup()
    buy = _subscribe(acc, inst, "10000", "10000", "0", "2", "5000")
    _post(buy["id"])
    assert _positions(acc)[0]["quantity"] == "5000.000000"

    resp = client.post(f"/api/v1/transactions/{buy['id']}/reverse")
    assert resp.status_code == 200, resp.text
    assert _positions(acc) == []
    assert _detail(buy["id"])["status"] == "REVERSED"

    # 已消耗批次不能冲正
    buy2 = _subscribe(acc, inst, "10000", "10000", "0", "2", "5000", "2026-11-11")
    _post(buy2["id"])
    sell = _redeem(acc, inst, "1000", "2000", "0", "2")
    _post(sell["id"])
    resp = client.post(f"/api/v1/transactions/{buy2['id']}/reverse")
    assert resp.status_code == 409
    assert "已被卖出" in resp.json()["error"]["message"]


def test_cash_dividend_reversal_allowed() -> None:
    acc, inst = _fund_setup()
    order = _order("CASH_DIVIDEND", acc, inst, apply_amount="500")
    _post(order["id"])

    resp = client.post(f"/api/v1/transactions/{order['id']}/reverse")
    assert resp.status_code == 200, resp.text
    assert _detail(order["id"])["status"] == "REVERSED"
    assert _positions(acc) == []


def test_idempotency_key_and_double_post() -> None:
    acc, inst = _fund_setup()
    key = f"fund-{uuid.uuid4().hex}"
    first = _subscribe(acc, inst, "10000", "10000", "0", "2", "5000", idempotency_key=key)
    dup = _order_raw("FUND_SUBSCRIBE", acc, inst, apply_amount="10000", idempotency_key=key)
    assert dup.status_code == 409
    assert "重复请求" in dup.json()["error"]["message"]

    detail1 = _post(first["id"])
    detail2 = _post(first["id"])  # 重复过账幂等
    assert detail2["status"] == "POSTED"
    assert detail2["entry"]["id"] == detail1["entry"]["id"]
    assert _positions(acc)[0]["quantity"] == "5000.000000"


def test_fail_order_has_no_ledger_effect() -> None:
    acc, inst = _fund_setup()
    order = _order("FUND_SUBSCRIBE", acc, inst, apply_amount="10000")
    resp = client.post(f"/api/v1/funds/orders/{order['id']}/fail")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"
    assert resp.json()["confirmation_status"] == "FAILED"

    post = client.post(f"/api/v1/transactions/{order['id']}/post")
    assert post.status_code == 409
    assert _positions(acc) == []

    detail = _detail(order["id"])
    assert detail["entry"] is None
    assert detail["confirmation"] is None

    resp = client.post(f"/api/v1/funds/orders/{order['id']}/fail")
    assert resp.status_code == 409
    assert "只有待确认的申请可以标记失败" in resp.json()["error"]["message"]


def test_fund_validation() -> None:
    acc, inst = _fund_setup()

    # 申购 / 现金分红缺 apply_amount，赎回缺 apply_shares → 422
    assert _order_raw("FUND_SUBSCRIBE", acc, inst).status_code == 422
    assert _order_raw("CASH_DIVIDEND", acc, inst).status_code == 422
    assert _order_raw("FUND_REDEEM", acc, inst).status_code == 422

    # 基金类型不能走证券/现金通用创建端点 → 422
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "FUND_SUBSCRIBE",
            "account_id": acc,
            "instrument_id": inst,
            "business_date": "2026-11-12",
            "amount": "10000",
        },
    )
    assert resp.status_code == 422

    # 账户 / 标的不存在 → 404
    resp = _order_raw("FUND_SUBSCRIBE", str(uuid.uuid4()), inst, apply_amount="10000")
    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "投资账户不存在"
    resp = _order_raw("FUND_SUBSCRIBE", acc, str(uuid.uuid4()), apply_amount="10000")
    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "投资品种不存在"

    # 详情不存在 → 404
    resp = client.get(f"/api/v1/funds/orders/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "基金申请不存在"

    # 确认参数边界：nav / shares / amount 必须 > 0，fee 不能为负
    order = _order("FUND_SUBSCRIBE", acc, inst, apply_amount="10000")
    assert (
        _confirm(order["id"], _confirmation_payload("2026-11-12", "0", "5000", "10000")).status_code
        == 422
    )
    assert (
        _confirm(order["id"], _confirmation_payload("2026-11-12", "2", "0", "10000")).status_code
        == 422
    )
    assert (
        _confirm(order["id"], _confirmation_payload("2026-11-12", "2", "5000", "0")).status_code
        == 422
    )
    assert (
        _confirm(
            order["id"], _confirmation_payload("2026-11-12", "2", "5000", "10000", "-1")
        ).status_code
        == 422
    )


def test_list_and_detail() -> None:
    acc, inst = _fund_setup()
    subscribe = _order("FUND_SUBSCRIBE", acc, inst, apply_amount="10000")
    dividend = _order("CASH_DIVIDEND", acc, inst, apply_amount="500")

    all_orders = client.get("/api/v1/funds/orders", params={"account_id": acc})
    assert all_orders.status_code == 200
    ids = {o["id"] for o in all_orders.json()}
    assert subscribe["id"] in ids and dividend["id"] in ids

    only_sub = client.get(
        "/api/v1/funds/orders",
        params={"account_id": acc, "transaction_type": "FUND_SUBSCRIBE"},
    )
    assert [o["id"] for o in only_sub.json()] == [subscribe["id"]]

    only_draft = client.get(
        "/api/v1/funds/orders", params={"account_id": acc, "status_filter": "DRAFT"}
    )
    assert [o["id"] for o in only_draft.json()] == [subscribe["id"]]

    # 确认并过账后，详情带确认数据与分录
    _confirm(subscribe["id"], _confirmation_payload("2026-11-10", "2", "5000", "10000"))
    _post(subscribe["id"])
    detail = _detail(subscribe["id"])
    assert detail["platform"] == "default"
    assert detail["confirmation"]["confirmed_shares"] == "5000.000000"
    assert detail["entry"]["entry_type"] == "NORMAL"
    assert len(detail["entry"]["lines"]) == 2
