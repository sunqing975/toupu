# 提案校验与审批（docs/risk-agent-rules.md §9）：创建即冻结快照，审批前重新校验。
# 审批只调用既有 transactions.create_transaction 生成 DRAFT，绝不 confirm/post。
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.core.errors import BusinessError
from app.risk.models import OperationProposal

CASH_TYPES = ("DEPOSIT", "WITHDRAW", "ACCOUNT_TRANSFER")


def _account(db: Session, account_id: str) -> InvestmentAccount | None:
    try:
        return db.get(InvestmentAccount, uuid.UUID(account_id))
    except (ValueError, TypeError):
        return None


def validate_payload(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """创建时校验并冻结 validation_snapshot；失败抛 BusinessError，不落库。"""
    txn_type = payload.get("transaction_type")
    if txn_type not in CASH_TYPES:
        raise BusinessError(f"提案数据校验失败：不支持的交易类型 {txn_type}")
    account_id = str(payload.get("account_id", ""))
    account = _account(db, account_id)
    if account is None:
        raise BusinessError("提案数据校验失败：转出账户不存在")
    counter_id = payload.get("counter_account_id")
    if txn_type == "ACCOUNT_TRANSFER":
        if not counter_id:
            raise BusinessError("提案数据校验失败：转账必须指定 counter_account_id")
        if str(counter_id) == account_id:
            raise BusinessError("提案数据校验失败：转入账户与转出账户不能相同")
        counter = _account(db, str(counter_id))
        if counter is None:
            raise BusinessError("提案数据校验失败：转入账户不存在")
    else:
        counter = None
    try:
        amount = Decimal(str(payload.get("amount")))
    except (TypeError, ValueError, ArithmeticError):
        raise BusinessError("提案数据校验失败：金额不是有效数字") from None
    if amount <= 0:
        raise BusinessError("提案数据校验失败：金额必须大于 0")
    try:
        business_date = date.fromisoformat(str(payload.get("business_date")))
    except (TypeError, ValueError):
        raise BusinessError("提案数据校验失败：业务日期格式错误") from None

    snapshot: dict[str, Any] = {
        "account_id": account_id,
        "account_name": account.name,
        "account_type": account.account_type,
        "account_currency": account.currency,
        "counter_account_id": str(counter.id) if counter else None,
        "counter_account_name": counter.name if counter else None,
        "amount": str(amount.quantize(Decimal("0.000001"))),
        "business_date": business_date.isoformat(),
        "transaction_type": txn_type,
    }
    impact: dict[str, Any] = {
        "asset": account.name,
        "quantity": None,
        "price_or_nav": None,
        "fee": None,
        "amount": snapshot["amount"],
        "currency": account.currency,
        "impact": "仅生成草稿，不入账，不改变余额/持仓",
    }
    return {"snapshot": snapshot, "impact": impact, "amount": amount}


def revalidate(db: Session, proposal: OperationProposal) -> None:
    """审批前重新校验：账户仍存在且名称/类型未变、counter 仍存在、金额仍 >0。"""
    payload = proposal.payload
    snapshot = proposal.validation_snapshot
    account = _account(db, snapshot["account_id"])
    if account is None or account.name != snapshot["account_name"]:
        raise BusinessError("提案数据已变更，拒绝审批，请重新生成")
    if account.account_type != snapshot["account_type"]:
        raise BusinessError("提案数据已变更，拒绝审批，请重新生成")
    counter_id = snapshot.get("counter_account_id")
    if counter_id:
        counter = _account(db, counter_id)
        if counter is None or counter.name != snapshot.get("counter_account_name"):
            raise BusinessError("提案数据已变更，拒绝审批，请重新生成")
        if str(counter.id) == snapshot["account_id"]:
            raise BusinessError("提案数据已变更，拒绝审批，请重新生成")
    try:
        amount = Decimal(str(payload.get("amount")))
    except (TypeError, ValueError, ArithmeticError):
        raise BusinessError("提案数据已变更，拒绝审批，请重新生成") from None
    if amount <= 0:
        raise BusinessError("提案数据已变更，拒绝审批，请重新生成")


def _now() -> datetime:
    return datetime.now(UTC)
