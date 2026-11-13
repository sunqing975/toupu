# M4 导入服务：解析 → 标准化 → 校验 → 重复检测 → 预览 → 确认过账。
#
# docs/ledger-rules.md §16 / agent.md §7：
#   - 上传只写 import_batches / import_records，绝不直接写正式账本；
#   - 原始数据（raw / raw_headers）以 JSONB 原样保留；
#   - 每条错误返回 {row_no, field, message}；
#   - 文件级 SHA-256 去重 + 业务级 dedup_key 去重；
#   - 只有人工确认才建 OPENING_BALANCE 并过账，整批单事务原子化。
import csv
import hashlib
import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.audit import record_audit
from app.core.errors import BusinessError
from app.imports.models import ImportBatch, ImportRecord, ImportTemplate
from app.instruments.models import Instrument
from app.ledger.service import post_transaction
from app.opening_balances.models import OpeningBalanceDetail
from app.transactions.models import InvestmentTransaction

Q6 = Decimal("0.000001")
TEMPLATE_CODE = "OPENING_BALANCE_V1"

# 必填列（其余为选填，随模板字段映射落库）
REQUIRED_COLUMNS = ("row_kind", "account_name", "business_date")
# 行类型别名：兼容中文 CSV
ROW_KIND_ALIASES = {"CASH": "CASH", "现金": "CASH", "POSITION": "POSITION", "持仓": "POSITION"}


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def idempotency_key(dedup_key: str) -> str:
    """idempotency_key 列仅 VARCHAR(100)，用摘要兜底（docs/ledger-rules.md §16.2）。"""
    return "import:" + hashlib.sha256(dedup_key.encode()).hexdigest()


def _cell_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    return str(value).strip()


def parse_file(file_name: str, content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """解析 CSV / Excel(.xlsx)，返回 (表头, 原始数据行列表)。表头第 1 行，首数据第 2 行。"""
    if not content:
        raise BusinessError("导入文件为空")
    lower = file_name.lower()
    if lower.endswith(".csv") or lower.endswith(".txt"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("gbk")
            except UnicodeDecodeError as exc:
                raise BusinessError("CSV 编码无法识别，请使用 UTF-8 或 GBK") from exc
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    elif lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:  # pragma: no cover - 依赖由 pyproject 保证
            raise BusinessError("缺少 openpyxl，无法解析 Excel 文件") from exc
        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:
            raise BusinessError(f"Excel 文件解析失败：{exc}") from exc
        ws = wb.active
        rows = [[_cell_to_str(c) for c in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        raise BusinessError("仅支持 CSV(.csv) 或 Excel(.xlsx) 文件")

    if not rows:
        raise BusinessError("导入文件没有表头行")
    headers = [str(h).strip() for h in rows[0]]
    if not any(headers):
        raise BusinessError("导入文件表头为空")
    data: list[dict[str, str]] = []
    for row in rows[1:]:
        if not any(str(c).strip() for c in row):
            continue  # 跳过全空行
        padded = list(row) + [""] * (len(headers) - len(row))
        data.append({h: _cell_to_str(padded[i]) for i, h in enumerate(headers)})
    return headers, data


@dataclass
class NormalizedRow:
    row_no: int
    raw: dict[str, str]
    normalized: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    dedup_key: str | None = None
    status: str = "VALID"

    def error(self, field_name: str, message: str) -> None:
        self.errors.append({"row_no": self.row_no, "field": field_name, "message": message})


def _parse_decimal(
    row: NormalizedRow, field_name: str, value: str, *, positive: bool
) -> Decimal | None:
    if not value:
        return None
    try:
        d = Decimal(value)
    except (InvalidOperation, ValueError):
        row.error(field_name, f"不是有效数字：{value}")
        return None
    if positive and d <= 0:
        row.error(field_name, "必须大于 0")
        return None
    return d.quantize(Q6)


def _parse_date(row: NormalizedRow, field_name: str, value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        row.error(field_name, f"日期格式错误，应为 YYYY-MM-DD：{value}")
        return None


def normalize_rows(
    db: Session, headers: list[str], data: list[dict[str, str]]
) -> list[NormalizedRow]:
    """标准化 + 校验 + 业务去重。返回每行的状态与错误定位信息。"""
    accounts = {a.name: a for a in db.query(InvestmentAccount).all()}
    instruments = {(i.market, i.code): i for i in db.query(Instrument).all()}
    existing_columns = set(headers)

    results: list[NormalizedRow] = []
    seen_keys: set[str] = set()
    for idx, raw in enumerate(data):
        row = NormalizedRow(row_no=idx + 2, raw=raw)

        for col in REQUIRED_COLUMNS:
            if col not in existing_columns:
                row.error(col, f"文件缺少必填列：{col}")

        kind_raw = raw.get("row_kind", "").upper()
        kind = ROW_KIND_ALIASES.get(kind_raw)
        if kind is None:
            hint = "CASH/现金 或 POSITION/持仓"
            row.error("row_kind", f"行类型非法：{raw.get('row_kind', '')}（应为 {hint}）")

        account_name = raw.get("account_name", "")
        account = accounts.get(account_name)
        if not account_name:
            row.error("account_name", "账户名不能为空")
        elif account is None:
            row.error("account_name", f"账户不存在：{account_name}")

        business_date = _parse_date(row, "business_date", raw.get("business_date", ""))
        if not raw.get("business_date", ""):
            row.error("business_date", "业务日期不能为空")

        currency = raw.get("currency", "") or "CNY"
        valuation_date = _parse_date(row, "valuation_date", raw.get("valuation_date", ""))
        cost_source = raw.get("cost_source", "") or None
        external_id = raw.get("external_id", "") or None
        memo = raw.get("memo", "") or None

        amount: Decimal | None = None
        quantity: Decimal | None = None
        total_cost: Decimal | None = None
        instrument_id: uuid.UUID | None = None
        market = raw.get("market", "") or None
        code = raw.get("code", "") or None

        if kind == "CASH":
            amount = _parse_decimal(row, "amount", raw.get("amount", ""), positive=True)
            if amount is None and not raw.get("amount", ""):
                row.error("amount", "期初现金必须指定金额 amount")
        elif kind == "POSITION":
            quantity = _parse_decimal(row, "quantity", raw.get("quantity", ""), positive=True)
            if quantity is None and not raw.get("quantity", ""):
                row.error("quantity", "期初持仓必须指定数量 quantity")
            total_cost = _parse_decimal(row, "total_cost", raw.get("total_cost", ""), positive=True)
            if total_cost is None and not raw.get("total_cost", ""):
                row.error("total_cost", "期初持仓必须指定账面成本 total_cost")
            if not market:
                row.error("market", "期初持仓必须指定市场 market")
            if not code:
                row.error("code", "期初持仓必须指定代码 code")
            if market and code:
                instrument = instruments.get((market, code))
                if instrument is None:
                    row.error("code", f"投资品种不存在：{market}/{code}")
                else:
                    instrument_id = instrument.id
            amount = total_cost  # 分录金额 = 账面成本

        normalized: dict[str, Any] = {
            "row_kind": kind,
            "account_name": account_name,
            "account_id": str(account.id) if account else None,
            "instrument_id": str(instrument_id) if instrument_id else None,
            "market": market,
            "code": code,
            "business_date": business_date.isoformat() if business_date else None,
            "valuation_date": valuation_date.isoformat() if valuation_date else None,
            "currency": currency,
            "amount": str(amount) if amount is not None else None,
            "quantity": str(quantity) if quantity is not None else None,
            "total_cost": str(total_cost) if total_cost is not None else None,
            "cost_source": cost_source,
            "external_id": external_id,
            "memo": memo,
        }
        row.normalized = normalized

        if row.errors:
            row.status = "ERROR"
            results.append(row)
            continue

        # 业务级去重键（docs/ledger-rules.md §16.2）
        if external_id:
            key = f"OB|EXT|{account.id}|{external_id}"  # type: ignore[union-attr]
        elif kind == "CASH":
            key = f"OB|CASH|{account.id}|{business_date}|{amount}|{currency}"  # type: ignore[union-attr]
        else:
            key = (
                f"OB|POS|{account.id}|{instrument_id}|{business_date}"  # type: ignore[union-attr]
                f"|{quantity}|{total_cost}|{currency}"
            )
        row.dedup_key = key
        results.append(row)

    # 批次内重复 + 已确认批次重复 + 已有交易幂等键兜底
    valid_keys = [r.dedup_key for r in results if r.dedup_key]
    if valid_keys:
        imported_keys = {
            r[0]
            for r in db.query(ImportRecord.dedup_key)
            .join(ImportBatch, ImportBatch.id == ImportRecord.batch_id)
            .filter(
                ImportBatch.status == "CONFIRMED",
                ImportRecord.status == "IMPORTED",
                ImportRecord.dedup_key.in_(valid_keys),
            )
            .all()
        }
        hashed_keys = [idempotency_key(k) for k in valid_keys]
        txn_keys = {
            t[0]
            for t in db.query(InvestmentTransaction.idempotency_key)
            .filter(InvestmentTransaction.idempotency_key.in_(hashed_keys))
            .all()
        }
    else:
        imported_keys, txn_keys = set(), set()

    for row in results:
        if row.status == "ERROR" or row.dedup_key is None:
            continue
        if (
            row.dedup_key in seen_keys
            or row.dedup_key in imported_keys
            or idempotency_key(row.dedup_key) in txn_keys
        ):
            row.status = "DUPLICATE"
        else:
            seen_keys.add(row.dedup_key)
    return results


def create_batch(
    db: Session, template: ImportTemplate, file_name: str, content: bytes, memo: str | None
) -> ImportBatch:
    """上传：仅写导入批次与原始行，不写正式账本。"""
    digest = file_hash(content)
    duplicate = (
        db.query(ImportBatch)
        .filter(
            ImportBatch.template_id == template.id,
            ImportBatch.file_hash == digest,
            ImportBatch.status != "CANCELLED",
        )
        .first()
    )
    if duplicate is not None:
        raise BusinessError("该文件已导入过（相同文件内容不可重复导入）")

    headers, data = parse_file(file_name, content)
    rows = normalize_rows(db, headers, data)
    batch = ImportBatch(
        template_id=template.id,
        file_name=file_name,
        file_hash=digest,
        status="DRAFT",
        raw_headers=headers,
        row_count=len(rows),
        error_count=sum(1 for r in rows if r.status == "ERROR"),
        duplicate_count=sum(1 for r in rows if r.status == "DUPLICATE"),
        memo=memo,
    )
    db.add(batch)
    db.flush()
    for row in rows:
        db.add(
            ImportRecord(
                batch_id=batch.id,
                row_no=row.row_no,
                status=row.status,
                dedup_key=row.dedup_key,
                normalized=row.normalized,
                raw=row.raw,
                errors=row.errors or None,
            )
        )
    record_audit(
        db,
        "import.batch.upload",
        "import_batch",
        str(batch.id),
        {"file_name": file_name, "row_count": len(rows)},
    )
    db.commit()
    db.refresh(batch)
    return batch


def confirm_batch(db: Session, batch: ImportBatch) -> ImportBatch:
    """人工确认：整批单事务建 OPENING_BALANCE 并过账，任一行失败整批回滚。"""
    if batch.status == "CONFIRMED":
        return batch  # 幂等：重复确认无副作用
    if batch.status != "DRAFT":
        raise BusinessError("只有草稿状态的导入批次可以确认")
    records = (
        db.query(ImportRecord).filter_by(batch_id=batch.id).order_by(ImportRecord.row_no).all()
    )
    if any(r.status == "ERROR" for r in records):
        raise BusinessError("导入批次存在错误行，请先修正文件后重新上传（错误已定位到行与字段）")
    valid = [r for r in records if r.status == "VALID"]
    if not valid:
        raise BusinessError("没有可导入的有效行（全部重复或错误）")

    try:
        for rec in valid:
            n = rec.normalized or {}
            txn = InvestmentTransaction(
                account_id=uuid.UUID(n["account_id"]),
                instrument_id=uuid.UUID(n["instrument_id"]) if n.get("instrument_id") else None,
                transaction_type="OPENING_BALANCE",
                status="CONFIRMED",
                business_date=date.fromisoformat(n["business_date"]),
                currency=n["currency"],
                total_amount=Decimal(n["amount"]),
                memo=n.get("memo"),
                idempotency_key=idempotency_key(rec.dedup_key),  # type: ignore[arg-type]
            )
            db.add(txn)
            db.flush()
            db.add(
                OpeningBalanceDetail(
                    transaction_id=txn.id,
                    row_kind=n["row_kind"],
                    quantity=Decimal(n["quantity"]) if n.get("quantity") else None,
                    total_cost=Decimal(n["total_cost"]) if n.get("total_cost") else None,
                    cost_source=n.get("cost_source"),
                    valuation_date=(
                        date.fromisoformat(n["valuation_date"]) if n.get("valuation_date") else None
                    ),
                )
            )
            # autoflush=False，明细须先落库，过账处理器才能按 transaction_id 查到它
            db.flush()
            # 通过 PostingService 过账（借贷平衡、审计留痕、幂等），不绕过它直接写分录
            post_transaction(db, txn)
            rec.status = "IMPORTED"
            rec.transaction_id = txn.id
        batch.status = "CONFIRMED"
        batch.confirmed_at = datetime.now(UTC)
        record_audit(
            db,
            "import.batch.confirm",
            "import_batch",
            str(batch.id),
            {"imported": len(valid)},
        )
        db.commit()
        db.refresh(batch)
    except BusinessError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise BusinessError(f"导入确认失败，整批已回滚：{exc}") from None
    return batch


def cancel_batch(db: Session, batch: ImportBatch) -> ImportBatch:
    if batch.status != "DRAFT":
        raise BusinessError("只有草稿状态的导入批次可以取消")
    records = db.query(ImportRecord).filter_by(batch_id=batch.id).all()
    for rec in records:
        if rec.status in ("VALID", "DUPLICATE"):
            rec.status = "SKIPPED"
    batch.status = "CANCELLED"
    record_audit(db, "import.batch.cancel", "import_batch", str(batch.id))
    db.commit()
    db.refresh(batch)
    return batch
