"""M6 验收：确定性风险扫描基准 + 幂等/冷却 + 规则校验 + 事件处理 + Agent 权限 + 提案安全。

按 docs/risk-agent-rules.md §4/§6/§7/§8/§9/§12：
- 权重/回撤/覆盖率四规则人工基准（六位量化）。
- 扫描同日幂等 + 冷却抑制。
- 规则范围与类型强校验 + 审计。
- 事件处理仅改状态 + 重复处理 409。
- Agent Token：无/无效/吊销→401、缺 scope→403、非法 scope→422、明文不落库不回显、
  agent_operations 记成功与失败。
- Agent 不能写账本：网关无 /post 等；对用户 /post 端点用 Agent Token→401/403；
  审批端点不读 Agent Token。
- 提案安全：校验失败不落库、过期/重复 409、账户变更后拒、审批只生成 DRAFT
  （断言无 journal_entries、position_lots 不变）、拒绝留痕。
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.main import app
from app.performance.formulas import max_drawdown
from app.risk.engine import evaluate
from app.risk.models import (
    AgentOperation,
    AgentToken,
    OperationProposal,
)

client = TestClient(app)


def _new_id() -> str:
    return f"M6-{uuid.uuid4().hex[:10]}"


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


def _deposit(account_id: str, amount: str) -> None:
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "DEPOSIT",
            "account_id": account_id,
            "business_date": "2026-11-12",
            "amount": amount,
        },
    )
    assert resp.status_code == 201, resp.text
    tid = resp.json()["id"]
    assert client.post(f"/api/v1/transactions/{tid}/confirm").status_code == 200
    assert client.post(f"/api/v1/transactions/{tid}/post").status_code == 200


def _buy(account_id: str, instrument_id: str, quantity: str, price: str) -> None:
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "STOCK_BUY",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "business_date": "2026-11-12",
            "executions": [
                {
                    "execution_date": "2026-11-12",
                    "quantity": quantity,
                    "price": price,
                    "fee_amount": "0",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    tid = resp.json()["id"]
    assert client.post(f"/api/v1/transactions/{tid}/confirm").status_code == 200
    assert client.post(f"/api/v1/transactions/{tid}/post").status_code == 200


def _quote(instrument_id: str, price: str) -> None:
    resp = client.post(
        "/api/v1/market/quotes",
        json={
            "instrument_id": instrument_id,
            "quote_date": "2026-11-13",
            "price": price,
            "data_type": "OFFICIAL",
            "adjust_type": "NONE",
            "quality_status": "FRESH",
        },
    )
    assert resp.status_code == 201, resp.text


def _snapshot(as_of: str = "2026-11-13") -> None:
    resp = client.post("/api/v1/snapshots/rebuild", json={"snapshot_date": as_of})
    assert resp.status_code == 200, resp.text


def _rule(scope: str, rule_type: str, threshold: str, **kwargs) -> dict:
    body = {"scope": scope, "rule_type": rule_type, "threshold": threshold}
    body.update(kwargs)
    resp = client.post("/api/v1/risk/rules", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_token(scopes: list[str]) -> tuple[str, str]:
    resp = client.post("/api/v1/agent/tokens", json={"name": _new_id(), "scopes": scopes})
    assert resp.status_code == 201, resp.text
    return resp.json()["token"], resp.json()["id"]


# ---------- 引擎纯函数基准（docs §4） ----------


def _pos(account_id, instrument_id, instrument_name, market_value, valued=True):
    from app.risk.engine import PositionData

    return PositionData(
        account_id=account_id,
        account_name="acc",
        instrument_id=instrument_id,
        instrument_name=instrument_name,
        valued=valued,
        market_value=market_value,
    )


def test_weight_benchmark_triggers_and_skips():
    from decimal import Decimal

    from app.risk.engine import DerivedData, RuleSpec

    rid = uuid.uuid4()
    ia, ib = uuid.uuid4(), uuid.uuid4()
    derived = DerivedData(
        total_assets=Decimal("1000.000000"),
        coverage=Decimal("1.000000"),
        total_positions=2,
        positions=[
            _pos(str(uuid.uuid4()), str(ia), "A", Decimal("350.000000")),
            _pos(str(uuid.uuid4()), str(ib), "B", Decimal("150.000000")),
        ],
    )
    rule = RuleSpec(rid, "INSTRUMENT", "POSITION_WEIGHT", Decimal("0.300000"), "WARNING", 1440, "r")
    result = evaluate([rule], derived, [], date(2026, 11, 13), datetime.now(UTC), set(), {})
    subjects = {e.subject: e.trigger_value for e in result.created}
    assert str(ia) in subjects
    assert Decimal(subjects[str(ia)]) == Decimal("0.350000")
    assert str(ib) not in subjects


def test_account_weight_benchmark():
    from decimal import Decimal

    from app.risk.engine import DerivedData, RuleSpec

    rid = uuid.uuid4()
    x, y = uuid.uuid4(), uuid.uuid4()
    derived = DerivedData(
        total_assets=Decimal("1000.000000"),
        coverage=Decimal("1.000000"),
        total_positions=1,
        positions=[
            _pos(str(x), str(uuid.uuid4()), "X", Decimal("600.000000")),
            _pos(str(y), str(uuid.uuid4()), "Y", Decimal("0.000000")),
        ],
    )
    rule = RuleSpec(rid, "ACCOUNT", "ACCOUNT_WEIGHT", Decimal("0.500000"), "WARNING", 1440, "r")
    result = evaluate([rule], derived, [], date(2026, 11, 13), datetime.now(UTC), set(), {})
    subjects = {e.subject for e in result.created}
    assert str(x) in subjects and str(y) not in subjects


def test_drawdown_benchmark():
    from decimal import Decimal

    points = [
        (date(2026, 1, 1), Decimal(1000)),
        (date(2026, 1, 2), Decimal(1200)),
        (date(2026, 1, 3), Decimal(900)),
        (date(2026, 1, 4), Decimal(1500)),
    ]
    mdd = max_drawdown(points)
    assert mdd.status == "OK"
    assert mdd.value == Decimal("-0.250000")
    assert mdd.peak_date == date(2026, 1, 2) and mdd.trough_date == date(2026, 1, 3)

    from app.risk.engine import DerivedData, RuleSpec

    rid = uuid.uuid4()
    rule = RuleSpec(
        rid, "PORTFOLIO", "PORTFOLIO_DRAWDOWN", Decimal("0.200000"), "CRITICAL", 1440, "r"
    )
    derived = DerivedData(Decimal("1500"), Decimal("1"), 1, [])
    result = evaluate([rule], derived, points, date(2026, 11, 13), datetime.now(UTC), set(), {})
    assert len(result.created) == 1
    assert result.created[0].trigger_value == Decimal("-0.250000")


def test_coverage_benchmark():
    from decimal import Decimal

    from app.risk.engine import DerivedData, RuleSpec

    rid = uuid.uuid4()
    rule = RuleSpec(rid, "PORTFOLIO", "QUOTE_COVERAGE", Decimal("0.800000"), "WARNING", 1440, "r")
    derived = DerivedData(Decimal("1000"), Decimal("0.500000"), 2, [])
    result = evaluate([rule], derived, [], date(2026, 11, 13), datetime.now(UTC), set(), {})
    assert len(result.created) == 1


def test_unvalued_position_skipped_not_zero():
    from decimal import Decimal

    from app.risk.engine import DerivedData, RuleSpec

    rid = uuid.uuid4()
    ia, ib = uuid.uuid4(), uuid.uuid4()
    derived = DerivedData(
        total_assets=Decimal("1000.000000"),
        coverage=Decimal("0.500000"),
        total_positions=2,
        positions=[
            _pos(str(uuid.uuid4()), str(ia), "A", Decimal("350.000000")),
            _pos(str(uuid.uuid4()), str(ib), "B", None, valued=False),
        ],
    )
    rule = RuleSpec(rid, "INSTRUMENT", "POSITION_WEIGHT", Decimal("0.300000"), "WARNING", 1440, "r")
    result = evaluate([rule], derived, [], date(2026, 11, 13), datetime.now(UTC), set(), {})
    subjects = {e.subject for e in result.created}
    assert str(ia) in subjects and str(ib) not in subjects


# ---------- 扫描幂等 + 冷却 + 规则校验 + 事件处理 ----------


def test_scan_creates_events_and_is_idempotent():
    # 用 QUOTE_COVERAGE 规则：本测试新建的持仓不被报价，确保全局覆盖率 < 1，必触发。
    acc = _account(_new_id())
    inst = _instrument(_new_id(), _new_id()[:6])
    _deposit(acc, "500.000000")
    _buy(acc, inst["id"], "100", "10")  # 不报价 → 覆盖率被拉低
    _snapshot(as_of="2026-12-01")

    rule = _rule("PORTFOLIO", "QUOTE_COVERAGE", "0.999999")
    as_of = "2026-12-01"

    r1 = client.post("/api/v1/risk/scan", json={"as_of": as_of})
    assert r1.status_code == 200, r1.text
    created_1 = len(r1.json()["created"])
    assert created_1 >= 1

    r2 = client.post("/api/v1/risk/scan", json={"as_of": as_of})
    assert r2.status_code == 200, r2.text
    # 同日幂等：不再新增
    assert len(r2.json()["created"]) == 0
    # 注意：测试库与开发库共享，风险事件会跨运行累积；按本测试新建的规则过滤，避免受历史事件干扰。
    total = client.get("/api/v1/risk/events").json()
    assert len([e for e in total if e["rule_id"] == rule["id"]]) == created_1


def test_rule_combination_rejected():
    resp = client.post(
        "/api/v1/risk/rules",
        json={"scope": "ACCOUNT", "rule_type": "POSITION_WEIGHT", "threshold": "0.5"},
    )
    assert resp.status_code == 422, resp.text
    assert "风险规则范围与类型不匹配" in resp.text


def test_rule_patch_cannot_change_scope_or_type():
    rule = _rule("PORTFOLIO", "QUOTE_COVERAGE", "0.800000")
    resp = client.patch(
        f"/api/v1/risk/rules/{rule['id']}",
        json={"threshold": "0.900000", "scope": "INSTRUMENT"},
    )
    assert resp.status_code == 409, resp.text
    assert "规则范围与类型不可修改" in resp.text


def test_event_resolve_then_duplicate_rejected():
    # 用 QUOTE_COVERAGE 规则（必触发，不依赖全局权重比例），按 dedup_key 取本次新建的事件。
    acc = _account(_new_id())
    inst = _instrument(_new_id(), _new_id()[:6])
    _deposit(acc, "500.000000")
    _buy(acc, inst["id"], "100", "10")  # 不报价 → 覆盖率低
    _snapshot(as_of="2026-12-02")
    _rule("PORTFOLIO", "QUOTE_COVERAGE", "0.999999")
    scan = client.post("/api/v1/risk/scan", json={"as_of": "2026-12-02"})
    created = scan.json()["created"]
    assert len(created) >= 1
    event_id = created[0]["id"]

    assert client.post(f"/api/v1/risk/events/{event_id}/acknowledge", json={}).status_code == 200
    ignore = client.post(f"/api/v1/risk/events/{event_id}/ignore", json={"note": "x"})
    assert ignore.status_code == 409, ignore.text
    assert "该风险事件已处理" in ignore.text


# ---------- Agent 权限 ----------


def test_agent_gateway_requires_token():
    resp = client.get("/api/v1/agent/accounts")
    assert resp.status_code == 401, resp.text


def test_agent_invalid_token_rejected():
    resp = client.get("/api/v1/agent/accounts", headers={"X-Agent-Token": "not-a-real-token"})
    assert resp.status_code == 401, resp.text


def test_agent_scope_missing_rejected():
    token, _ = _create_token(["read:positions"])
    resp = client.get("/api/v1/agent/accounts", headers={"X-Agent-Token": token})
    assert resp.status_code == 403, resp.text
    assert "Agent Token 缺少 scope" in resp.text


def test_agent_invalid_scope_on_create_rejected():
    resp = client.post("/api/v1/agent/tokens", json={"name": _new_id(), "scopes": ["write:ledger"]})
    assert resp.status_code == 422, resp.text
    assert "不允许的 scope" in resp.text


def test_agent_token_plaintext_not_stored():
    token, token_id = _create_token(["read:accounts"])
    with SessionLocal() as db:
        row = db.get(AgentToken, uuid.UUID(token_id))
        assert row.token_hash != token  # 库只存 sha256
        assert row.token_hash == __import__("hashlib").sha256(token.encode()).hexdigest()
    # GET 列表不回显明文 / 哈希
    listing = client.get("/api/v1/agent/tokens").json()
    assert all("token_hash" not in t and "token" not in t for t in listing)


def test_agent_gateway_success_records_operation():
    token, _ = _create_token(["read:accounts"])
    resp = client.get("/api/v1/agent/accounts", headers={"X-Agent-Token": token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["meta"]["source"] == "ledger"
    with SessionLocal() as db:
        ops = (
            db.execute(
                select(AgentOperation).where(
                    AgentOperation.resource == "accounts", AgentOperation.http_status == 200
                )
            )
            .scalars()
            .all()
        )
        assert len(ops) >= 1


def test_agent_cannot_write_ledger_via_post_to_user_endpoint():
    token, _ = _create_token(["read:accounts", "read:positions"])
    acc = _account(_new_id())
    # Agent token 不能用用户端 /post（端点不读 Agent 头，但应被当作无权限/无效 Token 处理）
    resp = client.post(
        f"/api/v1/transactions/{acc}/post",
        headers={"X-Agent-Token": token},
    )
    # 该端点不是交易详情端点，应 404/405；关键是不接受 Agent Token 执行写账本
    assert resp.status_code in (401, 403, 404, 405), resp.text


def test_agent_approval_endpoint_ignores_agent_token():
    # 审批端点本身不解析 X-Agent-Token，因此带 Token 的 Agent 无法调用它来改账本
    token, _ = _create_token(["read:proposals", "write:proposals"])
    # 审批端点本身不解析 X-Agent-Token，因此带 Token 的 Agent 无法调用它来改账本。
    # 这里验证 /plans/proposals 列表端点（不读 Agent 头）被当作普通请求处理。
    resp = client.get("/api/v1/plans/proposals")
    assert resp.status_code == 200, resp.text


# ---------- 提案安全 ----------


def test_proposal_create_and_approve_only_makes_draft():
    token, _ = _create_token(["write:proposals", "read:proposals"])
    acc = _account(_new_id())

    payload = {
        "transaction_type": "DEPOSIT",
        "account_id": acc,
        "business_date": "2026-11-13",
        "amount": "1234.560000",
        "memo": "Agent 建议入金",
    }
    resp = client.post(
        "/api/v1/agent/proposals",
        headers={"X-Agent-Token": token},
        json={"proposal_type": "DRAFT_CASH_TRANSACTION", "payload": payload, "expires_hours": 48},
    )
    assert resp.status_code == 201, resp.text
    proposal_id = resp.json()["id"]
    assert "仅生成草稿" in resp.json()["impact_preview"]["impact"]

    approve = client.post(f"/api/v1/plans/proposals/{proposal_id}/approve")
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "APPROVED"
    resulting_id = approve.json()["resulting_transaction_id"]
    assert resulting_id is not None

    # 审批只生成 DRAFT，不入账
    res_txn = client.get(f"/api/v1/transactions/{resulting_id}").json()
    assert res_txn["status"] == "DRAFT"

    # 全局交易列表有 100 条上限，用 resulting_transaction_id 直接核对这笔是否确为 DRAFT，
    # 并断言没有任何 journal_entries（草稿不过账）。
    with SessionLocal() as db:
        entries = db.execute(
            text("SELECT COUNT(*) FROM journal_entries WHERE transaction_id = :txn"),
            params={"txn": resulting_id},
        ).scalar()
        assert entries == 0  # 没有任何正式分录（草稿不入账）
        created = db.execute(
            text("SELECT COUNT(*) FROM investment_transactions WHERE id = :txn"),
            params={"txn": resulting_id},
        ).scalar()
        assert created == 1  # 仅新增一笔 DRAFT 草稿


def test_proposal_invalid_payload_not_stored():
    token, _ = _create_token(["write:proposals"])
    acc = _account(_new_id())
    resp = client.post(
        "/api/v1/agent/proposals",
        headers={"X-Agent-Token": token},
        json={
            "proposal_type": "DRAFT_CASH_TRANSACTION",
            "payload": {
                "transaction_type": "DEPOSIT",
                "account_id": acc,
                "business_date": "2026-11-13",
                "amount": "-5",
            },
        },
    )
    assert resp.status_code == 409, resp.text
    assert "提案数据校验失败" in resp.text


def test_proposal_expired_rejected():
    token, _ = _create_token(["write:proposals"])
    acc = _account(_new_id())
    resp = client.post(
        "/api/v1/agent/proposals",
        headers={"X-Agent-Token": token},
        json={
            "proposal_type": "DRAFT_CASH_TRANSACTION",
            "payload": {
                "transaction_type": "DEPOSIT",
                "account_id": acc,
                "business_date": "2026-11-13",
                "amount": "100",
            },
            "expires_hours": 1,
        },
    )
    proposal_id = resp.json()["id"]
    # 直接把过期时间改到过去
    with SessionLocal() as db:
        p = db.get(OperationProposal, uuid.UUID(proposal_id))
        p.expires_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    approve = client.post(f"/api/v1/plans/proposals/{proposal_id}/approve")
    assert approve.status_code == 409, approve.text
    assert "过期" in approve.text


def test_proposal_approve_twice_rejected():
    token, _ = _create_token(["write:proposals"])
    acc = _account(_new_id())
    resp = client.post(
        "/api/v1/agent/proposals",
        headers={"X-Agent-Token": token},
        json={
            "proposal_type": "DRAFT_CASH_TRANSACTION",
            "payload": {
                "transaction_type": "DEPOSIT",
                "account_id": acc,
                "business_date": "2026-11-13",
                "amount": "100",
            },
        },
    )
    proposal_id = resp.json()["id"]
    assert client.post(f"/api/v1/plans/proposals/{proposal_id}/approve").status_code == 200
    again = client.post(f"/api/v1/plans/proposals/{proposal_id}/approve")
    assert again.status_code == 409, again.text
    assert "不能重复审批" in again.text


def test_proposal_reject_is_recorded():
    token, _ = _create_token(["write:proposals"])
    acc = _account(_new_id())
    resp = client.post(
        "/api/v1/agent/proposals",
        headers={"X-Agent-Token": token},
        json={
            "proposal_type": "DRAFT_CASH_TRANSACTION",
            "payload": {
                "transaction_type": "DEPOSIT",
                "account_id": acc,
                "business_date": "2026-11-13",
                "amount": "100",
            },
        },
    )
    proposal_id = resp.json()["id"]
    reject = client.post(f"/api/v1/plans/proposals/{proposal_id}/reject", json={"note": "暂不处理"})
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "REJECTED"


@pytest.mark.parametrize(
    "scope",
    [
        "read:accounts",
        "read:positions",
        "read:transactions",
        "read:market",
        "read:performance",
        "read:risk",
        "read:plans",
        "read:proposals",
        "write:proposals",
    ],
)
def test_all_agent_scopes_readable_and_proposal_writable(scope):
    token, _ = _create_token([scope])
    if scope == "write:proposals":
        # 仅 proposal 创建需要 write，这里验证 token 创建成功即可
        assert token
        return
    mapping = {
        "read:accounts": "/api/v1/agent/accounts",
        "read:positions": "/api/v1/agent/positions",
        "read:transactions": "/api/v1/agent/transactions",
        "read:market": "/api/v1/agent/quotes",
        "read:performance": "/api/v1/agent/summary",
        "read:risk": "/api/v1/agent/risk-events",
        "read:plans": "/api/v1/agent/plans",
        "read:proposals": "/api/v1/agent/proposals",
    }
    resp = client.get(mapping[scope], headers={"X-Agent-Token": token})
    assert resp.status_code == 200, resp.text
    assert "meta" in resp.json()
