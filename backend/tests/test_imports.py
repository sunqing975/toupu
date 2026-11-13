"""M4 验收：导入八步状态机、期初资产分录、去重、错误定位、幂等、整批回滚、冲正、精度。

依据 docs/ledger-rules.md §16 / docs/implementation-plan.md M4 / agent.md §7/§9/§12：
  - 上传只写 import_batches/import_records，绝不直接写正式账本；
  - 重复导入不会重复记账；错误可定位到行和字段；期初持仓不伪造历史成交。
"""

import io
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.executions.models import TradeExecution
from app.imports.models import ImportRecord
from app.main import app
from app.positions.service import PositionLot
from app.transactions.models import InvestmentTransaction

client = TestClient(app)

COLS = [
    "row_kind",
    "account_name",
    "business_date",
    "amount",
    "market",
    "code",
    "quantity",
    "total_cost",
    "currency",
    "cost_source",
    "valuation_date",
    "external_id",
    "memo",
]
HEADER = ",".join(COLS)


def _account(name: str) -> dict:
    resp = client.post("/api/v1/accounts", json={"name": name, "account_type": "BROKER"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _instrument(name: str, code: str, itype: str = "STOCK", market: str = "CN") -> dict:
    resp = client.post(
        "/api/v1/instruments",
        json={"instrument_type": itype, "market": market, "code": code, "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _row(**kwargs: object) -> str:
    return ",".join(str(kwargs.get(c, "")) for c in COLS)


def _csv(rows: list[str], header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8-sig")


def _upload(content: bytes, name: str = "ob.csv", memo: str | None = None) -> dict:
    params = {"memo": memo} if memo else None
    resp = client.post(
        "/api/v1/imports/batches",
        files={"file": (name, content)},
        params=params,
    )
    return resp


def _cash_row(acc_name: str, amount: str = "100000", **kwargs: object) -> str:
    values: dict[str, object] = {
        "row_kind": "CASH",
        "account_name": acc_name,
        "business_date": "2026-01-01",
        "amount": amount,
        "currency": "CNY",
    }
    values.update(kwargs)
    return _row(**values)


def _position_row(acc_name: str, market: str, code: str, **kwargs: object) -> str:
    values: dict[str, object] = {
        "row_kind": "POSITION",
        "account_name": acc_name,
        "business_date": "2026-01-01",
        "market": market,
        "code": code,
        "quantity": "1000",
        "total_cost": "25000",
        "currency": "CNY",
    }
    values.update(kwargs)
    return _row(**values)


def _opening_txns(acc: str) -> list[dict]:
    """按 account_id 查询期初交易（列表端点 limit 100 不可靠，直接查本账户关联批次行）。"""
    with SessionLocal() as db:
        rows = (
            db.query(InvestmentTransaction)
            .filter(
                InvestmentTransaction.account_id == uuid.UUID(acc),
                InvestmentTransaction.transaction_type == "OPENING_BALANCE",
                InvestmentTransaction.reversal_of_id.is_(None),
            )
            .all()
        )
        return [
            {
                "id": str(r.id),
                "total_amount": f"{r.total_amount:.6f}" if r.total_amount is not None else None,
                "transaction_type": r.transaction_type,
                "status": r.status,
                "reversal_of_id": str(r.reversal_of_id) if r.reversal_of_id else None,
            }
            for r in rows
        ]


def _positions(acc: str) -> list[dict]:
    resp = client.get("/api/v1/positions", params={"account_id": acc})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry(txn_id: str) -> dict:
    resp = client.get(f"/api/v1/transactions/{txn_id}")
    assert resp.status_code == 200, resp.text
    entry = resp.json()["entry"]
    assert entry is not None
    return entry


# ---------------------------------------------------------------- 正常 / 八步状态机


def test_template_and_upload_preview_has_no_ledger_effect() -> None:
    tpl = client.get("/api/v1/imports/template")
    assert tpl.status_code == 200
    assert tpl.json()["code"] == "OPENING_BALANCE_V1"
    assert "row_kind" in tpl.json()["columns"]
    assert "account_name" in tpl.json()["columns"]

    acc = _account(f"导入预览-{uuid.uuid4().hex[:6]}")
    content = _csv([_cash_row(acc["name"], memo="预览阶段")])
    upload = _upload(content)
    assert upload.status_code == 201, upload.text
    batch = upload.json()
    assert batch["status"] == "DRAFT"
    assert batch["row_count"] == 1
    assert batch["error_count"] == 0
    assert batch["duplicate_count"] == 0
    assert batch["raw_headers"] == COLS
    rec = batch["records"][0]
    assert rec["row_no"] == 2
    assert rec["status"] == "VALID"
    assert rec["raw"]["account_name"] == acc["name"]
    assert rec["normalized"]["row_kind"] == "CASH"
    assert rec["normalized"]["currency"] == "CNY"

    # 预览阶段绝不写正式账本（agent.md §7）
    assert _opening_txns(acc["id"]) == []
    assert _positions(acc["id"]) == []


def test_cash_and_position_opening_balance_posting() -> None:
    acc = _account(f"期初过账-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"期初股票{uuid.uuid4().hex[:4]}", f"8{uuid.uuid4().int % 100000:05d}")
    content = _csv(
        [
            _cash_row(acc["name"], amount="100000", memo="期初现金"),
            _position_row(
                acc["name"],
                inst["market"],
                inst["code"],
                cost_source="券商对账单",
                valuation_date="2025-12-31",
                memo="期初持仓",
            ),
        ]
    )
    upload = _upload(content)
    assert upload.status_code == 201, upload.text
    assert [r["status"] for r in upload.json()["records"]] == ["VALID", "VALID"]

    conf = client.post(f"/api/v1/imports/batches/{upload.json()['id']}/confirm")
    assert conf.status_code == 200, conf.text
    assert conf.json()["status"] == "CONFIRMED"
    assert all(r["status"] == "IMPORTED" for r in conf.json()["records"])
    assert conf.json()["confirmed_at"] is not None

    txns = _opening_txns(acc["id"])
    assert len(txns) == 2
    by_amount = {t["total_amount"]: t for t in txns}
    assert set(by_amount) == {"100000.000000", "25000.000000"}

    cash_entry = _entry(by_amount["100000.000000"]["id"])
    cash_names = {ln["ledger_account_name"]: ln for ln in cash_entry["lines"]}
    cash_line = next(v for k, v in cash_names.items() if k.startswith("现金·"))
    ext_line = cash_names["外部资金平衡"]
    assert cash_line["direction"] == "DEBIT" and cash_line["amount"] == "100000.000000"
    assert ext_line["direction"] == "CREDIT" and ext_line["amount"] == "100000.000000"
    assert cash_entry["entry_type"] == "NORMAL"

    pos_entry = _entry(by_amount["25000.000000"]["id"])
    pos_lines = {ln["ledger_account_name"]: ln for ln in pos_entry["lines"]}
    sec_line = next(v for k, v in pos_lines.items() if k.startswith("证券·"))
    assert sec_line["direction"] == "DEBIT" and sec_line["amount"] == "25000.000000"
    assert pos_lines["外部资金平衡"]["direction"] == "CREDIT"

    pos = _positions(acc["id"])
    assert len(pos) == 1
    assert pos[0]["quantity"] == "1000.000000"
    assert pos[0]["total_cost"] == "25000.000000"
    assert pos[0]["unit_cost"] == "25.000000"

    # 期初汇总批次：lot_origin=OPENING_BALANCE，不伪造历史买入（domain-model §4）
    with SessionLocal() as db:
        lots = (
            db.query(PositionLot)
            .filter_by(origin_transaction_id=uuid.UUID(by_amount["25000.000000"]["id"]))
            .all()
        )
        assert len(lots) == 1
        assert lots[0].lot_origin == "OPENING_BALANCE"
        assert lots[0].open_date.isoformat() == "2026-01-01"
        assert (
            db.query(TradeExecution)
            .filter_by(transaction_id=uuid.UUID(by_amount["25000.000000"]["id"]))
            .count()
            == 0
        )
    assert not any(t["transaction_type"] == "STOCK_BUY" for t in _opening_txns(acc["id"]))


def test_six_decimal_precision_and_unit_cost_derived() -> None:
    acc = _account(f"期初精度-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"精度股票{uuid.uuid4().hex[:4]}", f"9{uuid.uuid4().int % 100000:05d}")
    # 金额超出 6 位小数 → quantize(0.000001)；unit_cost 由总额/数量推导，不接受用户传入
    content = _csv(
        [
            _cash_row(acc["name"], amount="100000.12345678"),
            _position_row(
                acc["name"],
                inst["market"],
                inst["code"],
                quantity="1000",
                total_cost="25000.98765432",
            ),
        ],
        header=HEADER + ",unit_cost",
    )
    # 追加一个用户传入的 unit_cost 列值（应被忽略）
    lines = content.decode("utf-8-sig").strip().split("\n")
    lines[1] += ",999"
    lines[2] += ",999"
    content = ("\n".join(lines) + "\n").encode("utf-8-sig")

    upload = _upload(content)
    assert upload.status_code == 201, upload.text
    assert [r["status"] for r in upload.json()["records"]] == ["VALID", "VALID"]
    assert upload.json()["records"][0]["normalized"]["amount"] == "100000.123457"
    assert upload.json()["records"][1]["normalized"]["total_cost"] == "25000.987654"

    conf = client.post(f"/api/v1/imports/batches/{upload.json()['id']}/confirm")
    assert conf.status_code == 200, conf.text
    amounts = {t["total_amount"] for t in _opening_txns(acc["id"])}
    assert "100000.123457" in amounts
    assert "25000.987654" in amounts

    pos = _positions(acc["id"])[0]
    expected_unit = (Decimal("25000.987654") / Decimal("1000.000000")).quantize(Decimal("0.000001"))
    assert pos["unit_cost"] == f"{expected_unit:.6f}"
    assert pos["unit_cost"] != "999.000000"
    for value in (pos["quantity"], pos["total_cost"], pos["unit_cost"]):
        assert len(value.split(".")[1]) == 6


def test_chinese_aliases_and_optional_fields() -> None:
    acc = _account(f"中文别名-{uuid.uuid4().hex[:6]}")
    inst = _instrument(
        f"别名股票{uuid.uuid4().hex[:4]}", f"7{uuid.uuid4().int % 100000:05d}", itype="FUND"
    )
    content = _csv(
        [
            _row(
                row_kind="现金",
                account_name=acc["name"],
                business_date="2026-01-01",
                amount="5000",
                external_id="EXT-001",
                memo="中文现金",
            ),
            _row(
                row_kind="持仓",
                account_name=acc["name"],
                business_date="2026-01-01",
                market=inst["market"],
                code=inst["code"],
                quantity="200",
                total_cost="3000",
                cost_source="基金对账单",
                valuation_date="2025-12-31",
                external_id="EXT-002",
            ),
        ]
    )
    upload = _upload(content)
    assert upload.status_code == 201, upload.text
    recs = upload.json()["records"]
    assert recs[0]["normalized"]["row_kind"] == "CASH"
    assert recs[1]["normalized"]["row_kind"] == "POSITION"
    assert recs[0]["dedup_key"] == f"OB|EXT|{acc['id']}|EXT-001"
    assert recs[1]["dedup_key"] == f"OB|EXT|{acc['id']}|EXT-002"
    # 未填 currency 默认 CNY
    assert recs[0]["normalized"]["currency"] == "CNY"
    assert recs[1]["normalized"]["cost_source"] == "基金对账单"
    assert recs[1]["normalized"]["valuation_date"] == "2025-12-31"

    conf = client.post(f"/api/v1/imports/batches/{upload.json()['id']}/confirm")
    assert conf.status_code == 200, conf.text
    assert len(_opening_txns(acc["id"])) == 2
    assert _positions(acc["id"])[0]["unit_cost"] == "15.000000"


def test_xlsx_upload_and_preview() -> None:
    from openpyxl import Workbook

    acc = _account(f"Excel导入-{uuid.uuid4().hex[:6]}")
    wb = Workbook()
    ws = wb.active
    ws.append(COLS)
    ws.append(
        [
            "CASH",
            acc["name"],
            "2026-01-01",
            100000,
            "",
            "",
            "",
            "",
            "CNY",
            "",
            "",
            "",
            "Excel 期初现金",
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)
    upload = _upload(buf.getvalue(), name="ob.xlsx")
    assert upload.status_code == 201, upload.text
    assert upload.json()["status"] == "DRAFT"
    rec = upload.json()["records"][0]
    assert rec["status"] == "VALID"
    assert rec["normalized"]["amount"] == "100000.000000"
    assert rec["normalized"]["currency"] == "CNY"

    conf = client.post(f"/api/v1/imports/batches/{upload.json()['id']}/confirm")
    assert conf.status_code == 200, conf.text
    assert len(_opening_txns(acc["id"])) == 1


# ---------------------------------------------------------------- 错误定位 / 边界


def test_error_rows_are_located_to_row_and_field() -> None:
    acc = _account(f"错误定位-{uuid.uuid4().hex[:6]}")
    content = _csv(
        [
            # 行类型非法时金额字段不再校验（短路），验证 row_kind/account_name/business_date
            _row(
                row_kind="BAD",
                account_name="不存在的账户",
                business_date="2026/01/01",
                amount="-5",
            ),
            # 合法 CASH 行 + 非正金额 → amount「必须大于 0」
            _row(
                row_kind="CASH",
                account_name=acc["name"],
                business_date="2026-01-01",
                amount="-5",
            ),
            _row(
                row_kind="POSITION",
                account_name=acc["name"],
                business_date="2026-01-01",
                market="CN",
                code="NO_SUCH_CODE",
                quantity="0",
                total_cost="-1",
            ),
        ]
    )
    upload = _upload(content)
    assert upload.status_code == 201, upload.text
    batch = upload.json()
    assert batch["status"] == "DRAFT"
    assert batch["error_count"] == 3
    assert [r["row_no"] for r in batch["records"]] == [2, 3, 4]

    fields = {(e["row_no"], e["field"]) for r in batch["records"] for e in r["errors"]}
    assert (2, "row_kind") in fields
    assert (2, "account_name") in fields
    assert (2, "business_date") in fields
    assert (3, "amount") in fields
    assert (4, "quantity") in fields
    assert (4, "total_cost") in fields
    assert (4, "code") in fields
    for rec in batch["records"]:
        for err in rec["errors"]:
            assert set(err) == {"row_no", "field", "message"}
            assert err["message"]

    # 有 ERROR 行整批拒绝确认（agent.md §7）
    conf = client.post(f"/api/v1/imports/batches/{batch['id']}/confirm")
    assert conf.status_code == 409
    assert "存在错误行" in conf.json()["error"]["message"]
    assert _opening_txns(acc["id"]) == []


def test_error_batch_then_corrected_file_imports_cleanly() -> None:
    acc = _account(f"修正重传-{uuid.uuid4().hex[:6]}")
    bad = _upload(
        _csv(
            [
                _row(
                    row_kind="CASH",
                    account_name="无",
                    business_date="x",
                    amount="-1",
                    memo=f"bad-{uuid.uuid4().hex[:8]}",
                )
            ]
        )
    )
    assert bad.status_code == 201
    assert bad.json()["error_count"] == 1

    good = _upload(
        _csv([_cash_row(acc["name"], amount="8000", memo=f"修正后-{uuid.uuid4().hex[:8]}")])
    )
    assert good.status_code == 201, good.text
    assert good.json()["error_count"] == 0
    conf = client.post(f"/api/v1/imports/batches/{good.json()['id']}/confirm")
    assert conf.status_code == 200, conf.text
    assert _opening_txns(acc["id"])[0]["total_amount"] == "8000.000000"


def test_missing_required_column_reports_field() -> None:
    header = "row_kind,business_date,amount"
    # 金额里带随机数字，避免多次运行撞上持久库的文件哈希去重
    unique_amount = f"1000{uuid.uuid4().int % 100000}"
    content = _csv([f"CASH,2026-01-01,{unique_amount}"], header=header)
    upload = _upload(content)
    assert upload.status_code == 201, upload.text
    rec = upload.json()["records"][0]
    assert rec["status"] == "ERROR"
    assert any(e["field"] == "account_name" and "缺少必填列" in e["message"] for e in rec["errors"])


def test_empty_and_unsupported_files_rejected() -> None:
    empty = _upload(b"", name="ob.csv")
    assert empty.status_code == 409
    assert empty.json()["error"]["message"] == "导入文件为空"

    bad_ext = _upload(b"row_kind,account_name,business_date\n", name="ob.pdf")
    assert bad_ext.status_code == 409
    assert "仅支持" in bad_ext.json()["error"]["message"]


def test_generic_transaction_endpoint_rejects_opening_balance() -> None:
    acc = _account(f"通用端点护栏-{uuid.uuid4().hex[:6]}")
    resp = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "OPENING_BALANCE",
            "account_id": acc["id"],
            "business_date": "2026-01-01",
            "amount": "1000",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- 去重 / 幂等


def test_duplicate_business_key_within_one_file() -> None:
    acc = _account(f"批内去重-{uuid.uuid4().hex[:6]}")
    row = _cash_row(acc["name"], amount="100000", memo="同一行")
    upload = _upload(_csv([row, row]))
    assert upload.status_code == 201, upload.text
    assert upload.json()["duplicate_count"] == 1
    assert [r["status"] for r in upload.json()["records"]] == ["VALID", "DUPLICATE"]

    conf = client.post(f"/api/v1/imports/batches/{upload.json()['id']}/confirm")
    assert conf.status_code == 200, conf.text
    assert len(_opening_txns(acc["id"])) == 1
    statuses = [r["status"] for r in conf.json()["records"]]
    assert statuses == ["IMPORTED", "DUPLICATE"]


def test_duplicate_file_hash_rejected() -> None:
    acc = _account(f"文件去重-{uuid.uuid4().hex[:6]}")
    content = _csv([_cash_row(acc["name"], amount="100000")])
    first = _upload(content, name="a.csv")
    assert first.status_code == 201, first.text
    second = _upload(content, name="b.csv")  # 内容相同、文件名不同
    assert second.status_code == 409
    assert "该文件已导入过" in second.json()["error"]["message"]


def test_duplicate_across_batches_does_not_double_post() -> None:
    acc = _account(f"跨批去重-{uuid.uuid4().hex[:6]}")
    row_a = _cash_row(acc["name"], amount="100000", business_date="2026-01-01")
    first = _upload(_csv([row_a]))
    assert first.status_code == 201, first.text
    assert client.post(f"/api/v1/imports/batches/{first.json()['id']}/confirm").status_code == 200

    # 不同文件字节（多了 memo 列值），业务字段完全相同 → 业务级去重命中
    row_a_again = _cash_row(acc["name"], amount="100000", business_date="2026-01-01", memo="重传")
    row_b = _cash_row(acc["name"], amount="200000", business_date="2026-01-02")
    second = _upload(_csv([row_a_again, row_b]))
    assert second.status_code == 201, second.text
    assert second.json()["duplicate_count"] == 1
    assert [r["status"] for r in second.json()["records"]] == ["DUPLICATE", "VALID"]

    conf = client.post(f"/api/v1/imports/batches/{second.json()['id']}/confirm")
    assert conf.status_code == 200, conf.text
    # 只有新行入账，重复行不重复记账
    amounts = {t["total_amount"] for t in _opening_txns(acc["id"])}
    assert amounts == {"100000.000000", "200000.000000"}


def test_confirm_is_idempotent_and_no_valid_rows_rejected() -> None:
    acc = _account(f"确认幂等-{uuid.uuid4().hex[:6]}")
    upload = _upload(_csv([_cash_row(acc["name"], amount="100000")]))
    assert upload.status_code == 201, upload.text
    bid = upload.json()["id"]
    first = client.post(f"/api/v1/imports/batches/{bid}/confirm")
    assert first.status_code == 200, first.text
    second = client.post(f"/api/v1/imports/batches/{bid}/confirm")
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "CONFIRMED"
    assert len(_opening_txns(acc["id"])) == 1

    # 全部重复 → 没有可导入的有效行
    row = _cash_row(acc["name"], amount="100000", memo="全重复")
    dup = _upload(_csv([row]))
    assert dup.status_code == 201, dup.text
    assert dup.json()["duplicate_count"] == 1
    conf = client.post(f"/api/v1/imports/batches/{dup.json()['id']}/confirm")
    assert conf.status_code == 409
    assert "没有可导入的有效行" in conf.json()["error"]["message"]


def test_confirm_rolls_back_whole_batch_on_posting_failure() -> None:
    acc = _account(f"整批回滚-{uuid.uuid4().hex[:6]}")
    upload = _upload(
        _csv(
            [
                _cash_row(acc["name"], amount="100000", business_date="2026-01-01"),
                _cash_row(acc["name"], amount="200000", business_date="2026-01-02"),
            ]
        )
    )
    assert upload.status_code == 201, upload.text
    bid = upload.json()["id"]

    # 人为破坏第 2 行的明细类型，使过账处理器抛错：验证确认是单事务、整批回滚
    with SessionLocal() as db:
        rec = (
            db.query(ImportRecord)
            .filter_by(batch_id=uuid.UUID(bid))
            .order_by(ImportRecord.row_no)
            .all()[-1]
        )
        normalized = dict(rec.normalized or {})
        normalized["row_kind"] = "UNKNOWN"
        rec.normalized = normalized
        db.commit()

    conf = client.post(f"/api/v1/imports/batches/{bid}/confirm")
    assert conf.status_code == 409
    assert "整批已回滚" in conf.json()["error"]["message"]
    assert _opening_txns(acc["id"]) == []
    detail = client.get(f"/api/v1/imports/batches/{bid}")
    assert detail.json()["status"] == "DRAFT"
    assert all(r["status"] == "VALID" for r in detail.json()["records"])


# ---------------------------------------------------------------- 取消 / 冲正


def test_cancel_batch_and_reupload_same_file() -> None:
    acc = _account(f"取消批次-{uuid.uuid4().hex[:6]}")
    content = _csv([_cash_row(acc["name"], amount="100000")])
    upload = _upload(content)
    assert upload.status_code == 201, upload.text
    bid = upload.json()["id"]

    cancel = client.post(f"/api/v1/imports/batches/{bid}/cancel")
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "CANCELLED"
    assert all(r["status"] == "SKIPPED" for r in cancel.json()["records"])
    assert _opening_txns(acc["id"]) == []

    conf = client.post(f"/api/v1/imports/batches/{bid}/confirm")
    assert conf.status_code == 409
    assert "只有草稿状态" in conf.json()["error"]["message"]

    # 部分唯一索引排除 CANCELLED，同内容可重新上传
    again = _upload(content, name="again.csv")
    assert again.status_code == 201, again.text
    assert again.json()["status"] == "DRAFT"


def test_reverse_opening_balance_cash_and_position() -> None:
    acc = _account(f"期初冲正-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"冲正股票{uuid.uuid4().hex[:4]}", f"6{uuid.uuid4().int % 100000:05d}")
    upload = _upload(
        _csv(
            [
                _cash_row(acc["name"], amount="100000"),
                _position_row(acc["name"], inst["market"], inst["code"]),
            ]
        )
    )
    assert upload.status_code == 201, upload.text
    assert client.post(f"/api/v1/imports/batches/{upload.json()['id']}/confirm").status_code == 200
    txns = {t["total_amount"]: t for t in _opening_txns(acc["id"])}

    # 期初现金行没有批次，冲正不应误报「缺少持仓批次」（_needs_lot_check 分支）
    cash_rev = client.post(f"/api/v1/transactions/{txns['100000.000000']['id']}/reverse")
    assert cash_rev.status_code == 200, cash_rev.text
    assert cash_rev.json()["status"] == "REVERSED"

    # 期初持仓行冲正：批次未被消耗，删除批次
    pos_rev = client.post(f"/api/v1/transactions/{txns['25000.000000']['id']}/reverse")
    assert pos_rev.status_code == 200, pos_rev.text
    assert _positions(acc["id"]) == []

    with SessionLocal() as db:
        assert (
            db.query(PositionLot)
            .filter_by(origin_transaction_id=uuid.UUID(txns["25000.000000"]["id"]))
            .count()
            == 0
        )


def test_reverse_consumed_opening_lot_rejected() -> None:
    acc = _account(f"消耗后冲正-{uuid.uuid4().hex[:6]}")
    inst = _instrument(f"消耗股票{uuid.uuid4().hex[:4]}", f"5{uuid.uuid4().int % 100000:05d}")
    upload = _upload(_csv([_position_row(acc["name"], inst["market"], inst["code"])]))
    assert upload.status_code == 201, upload.text
    assert client.post(f"/api/v1/imports/batches/{upload.json()['id']}/confirm").status_code == 200
    opening = _opening_txns(acc["id"])[0]

    # 卖掉 100 股，消耗期初批次
    sell = client.post(
        "/api/v1/transactions",
        json={
            "transaction_type": "STOCK_SELL",
            "account_id": acc["id"],
            "instrument_id": inst["id"],
            "business_date": "2026-02-01",
            "executions": [{"execution_date": "2026-02-01", "quantity": "100", "price": "30"}],
        },
    )
    assert sell.status_code == 201, sell.text
    assert client.post(f"/api/v1/transactions/{sell.json()['id']}/confirm").status_code == 200
    assert client.post(f"/api/v1/transactions/{sell.json()['id']}/post").status_code == 200

    rev = client.post(f"/api/v1/transactions/{opening['id']}/reverse")
    assert rev.status_code == 409
    assert "批次已被卖出" in rev.json()["error"]["message"]


# ---------------------------------------------------------------- 列表 / 详情


def test_list_and_detail_and_not_found() -> None:
    acc = _account(f"列表详情-{uuid.uuid4().hex[:6]}")
    upload = _upload(_csv([_cash_row(acc["name"], amount="100000")]))
    assert upload.status_code == 201, upload.text
    bid = upload.json()["id"]

    listed = client.get("/api/v1/imports/batches", params={"status": "DRAFT"})
    assert listed.status_code == 200
    assert bid in [b["id"] for b in listed.json()]

    detail = client.get(f"/api/v1/imports/batches/{bid}")
    assert detail.status_code == 200
    assert detail.json()["id"] == bid
    assert detail.json()["template_code"] == "OPENING_BALANCE_V1"
    assert len(detail.json()["records"]) == 1

    missing = client.get(f"/api/v1/imports/batches/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert missing.json()["error"]["message"] == "导入批次不存在"
