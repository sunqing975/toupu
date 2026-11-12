# PostingService：分录生成、借贷平衡校验、过账幂等、冲正。
# 规则依据 docs/ledger-rules.md；金额一律 Decimal，禁止 float。
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.errors import BusinessError
from app.executions.models import TradeExecution
from app.ledger.models import JournalEntry, JournalLine, LedgerAccount
from app.transactions.models import InvestmentTransaction

# 业务行：(科目, 方向, 金额)
Line = tuple[LedgerAccount, str, Decimal]

DEBIT, CREDIT = "DEBIT", "CREDIT"

M1_POSTABLE_TYPES = {"DEPOSIT", "WITHDRAW", "ACCOUNT_TRANSFER"}

SECURITY_BUY_TYPES = {"STOCK_BUY", "ETF_BUY"}
SECURITY_SELL_TYPES = {"STOCK_SELL", "ETF_SELL"}
SECURITY_TYPES = SECURITY_BUY_TYPES | SECURITY_SELL_TYPES


def get_or_create_cash(db: Session, account_id: uuid.UUID, currency: str = "CNY") -> LedgerAccount:
    acc = (
        db.query(LedgerAccount)
        .filter_by(
            account_type="CASH",
            investment_account_id=account_id,
            instrument_id=None,
            currency=currency,
        )
        .one_or_none()
    )
    if acc is None:
        name = f"现金·{account_id.hex[:8]}·{currency}"
        acc = LedgerAccount(
            account_type="CASH",
            investment_account_id=account_id,
            instrument_id=None,
            currency=currency,
            name=name,
        )
        db.add(acc)
        db.flush()
    return acc


def get_or_create_external(db: Session, currency: str = "CNY") -> LedgerAccount:
    acc = (
        db.query(LedgerAccount)
        .filter_by(
            account_type="OPENING_BALANCE",
            investment_account_id=None,
            instrument_id=None,
            currency=currency,
        )
        .one_or_none()
    )
    if acc is None:
        acc = LedgerAccount(
            account_type="OPENING_BALANCE",
            investment_account_id=None,
            instrument_id=None,
            currency=currency,
            name="外部资金平衡",
        )
        db.add(acc)
        db.flush()
    return acc


def get_or_create_security(
    db: Session, account_id: uuid.UUID, instrument_id: uuid.UUID, currency: str = "CNY"
) -> LedgerAccount:
    acc = (
        db.query(LedgerAccount)
        .filter_by(
            account_type="SECURITY",
            investment_account_id=account_id,
            instrument_id=instrument_id,
            currency=currency,
        )
        .one_or_none()
    )
    if acc is None:
        acc = LedgerAccount(
            account_type="SECURITY",
            investment_account_id=account_id,
            instrument_id=instrument_id,
            currency=currency,
            name=f"证券·{account_id.hex[:8]}·{instrument_id.hex[:8]}·{currency}",
        )
        db.add(acc)
        db.flush()
    return acc


def get_or_create_income(
    db: Session, account_type: str, name: str, currency: str = "CNY"
) -> LedgerAccount:
    acc = (
        db.query(LedgerAccount)
        .filter_by(
            account_type=account_type,
            investment_account_id=None,
            instrument_id=None,
            currency=currency,
        )
        .one_or_none()
    )
    if acc is None:
        acc = LedgerAccount(
            account_type=account_type,
            investment_account_id=None,
            instrument_id=None,
            currency=currency,
            name=name,
        )
        db.add(acc)
        db.flush()
    return acc


def check_balanced(lines: list[Line]) -> None:
    debits = sum((a for _, d, a in lines if d == DEBIT), Decimal(0))
    credits = sum((a for _, d, a in lines if d == CREDIT), Decimal(0))
    if debits != credits:
        raise BusinessError(f"借贷不平衡：借方合计 {debits}，贷方合计 {credits}")


def _executions(db: Session, txn: InvestmentTransaction) -> list[TradeExecution]:
    return (
        db.query(TradeExecution)
        .filter_by(transaction_id=txn.id)
        .order_by(TradeExecution.sequence_no)
        .all()
    )


def _security_buy_lines(db: Session, txn: InvestmentTransaction) -> list[Line]:
    # ledger-rules §3：费用计入持仓成本，借证券资产 贷现金；成交金额与费用保留在明细
    from app.positions.service import apply_buy

    executions = _executions(db, txn)
    net = sum((ex.net_amount for ex in executions), Decimal(0))
    apply_buy(db, txn, executions)
    security = get_or_create_security(db, txn.account_id, txn.instrument_id, txn.currency)  # type: ignore[arg-type]
    cash = get_or_create_cash(db, txn.account_id, txn.currency)
    return [(security, DEBIT, net), (cash, CREDIT, net)]


def _security_sell_lines(db: Session, txn: InvestmentTransaction) -> list[Line]:
    # ledger-rules §4：借现金（净额），贷证券资产（出库成本），差额记已实现损益
    from app.positions.service import apply_sell

    executions = _executions(db, txn)
    net = sum((ex.net_amount for ex in executions), Decimal(0))
    cost_out = apply_sell(db, txn, executions)
    security = get_or_create_security(db, txn.account_id, txn.instrument_id, txn.currency)  # type: ignore[arg-type]
    cash = get_or_create_cash(db, txn.account_id, txn.currency)
    lines: list[Line] = [(cash, DEBIT, net), (security, CREDIT, cost_out)]
    realized = net - cost_out
    if realized > 0:
        gain = get_or_create_income(db, "REALIZED_GAIN", "已实现收益", txn.currency)
        lines.append((gain, CREDIT, realized))
    elif realized < 0:
        loss = get_or_create_income(db, "REALIZED_LOSS", "已实现损失", txn.currency)
        lines.append((loss, DEBIT, -realized))
    return lines


def _cash_lines(db: Session, txn: InvestmentTransaction) -> list[Line]:
    amount = txn.total_amount
    if amount is None:
        raise BusinessError("交易缺少金额")
    if txn.transaction_type == "DEPOSIT":
        return [
            (get_or_create_cash(db, txn.account_id), DEBIT, amount),
            (get_or_create_external(db), CREDIT, amount),
        ]
    if txn.transaction_type == "WITHDRAW":
        return [
            (get_or_create_external(db), DEBIT, amount),
            (get_or_create_cash(db, txn.account_id), CREDIT, amount),
        ]
    if txn.transaction_type == "ACCOUNT_TRANSFER":
        if txn.counter_account_id is None:
            raise BusinessError("转账缺少转入账户")
        return [
            (get_or_create_cash(db, txn.counter_account_id), DEBIT, amount),
            (get_or_create_cash(db, txn.account_id), CREDIT, amount),
        ]
    raise BusinessError(
        f"过账类型 {txn.transaction_type} 暂不支持（证券成交随 M2、基金随 M3 开放）"
    )


HANDLERS = {
    "DEPOSIT": _cash_lines,
    "WITHDRAW": _cash_lines,
    "ACCOUNT_TRANSFER": _cash_lines,
    "STOCK_BUY": _security_buy_lines,
    "ETF_BUY": _security_buy_lines,
    "STOCK_SELL": _security_sell_lines,
    "ETF_SELL": _security_sell_lines,
}


def get_entry(db: Session, transaction_id: uuid.UUID) -> JournalEntry | None:
    return db.query(JournalEntry).filter_by(transaction_id=transaction_id).one_or_none()


def post_transaction(db: Session, txn: InvestmentTransaction) -> JournalEntry:
    """过账。已过账时幂等返回既有分录，不重复影响余额。"""
    existing = get_entry(db, txn.id)
    if existing is not None:
        return existing  # 幂等：重复过账无副作用
    if txn.status != "CONFIRMED":
        raise BusinessError("交易未确认，不能过账")
    if txn.reversal_of_id is not None and txn.transaction_type not in HANDLERS:
        raise BusinessError("过账类型暂不支持")

    lines = HANDLERS[txn.transaction_type](db, txn)
    check_balanced(lines)

    entry = JournalEntry(transaction_id=txn.id, memo=txn.memo)
    db.add(entry)
    db.flush()
    for idx, (account, direction, amount) in enumerate(lines, start=1):
        db.add(
            JournalLine(
                entry_id=entry.id,
                ledger_account_id=account.id,
                direction=direction,
                amount=amount,
                line_no=idx,
            )
        )
    txn.status = "POSTED"
    record_audit(
        db,
        "transaction.post",
        "investment_transaction",
        str(txn.id),
        {"type": txn.transaction_type, "amount": str(txn.total_amount)},
    )
    return entry


def reverse_transaction(db: Session, txn: InvestmentTransaction) -> InvestmentTransaction:
    """冲正：生成反向分录的冲正交易，原交易状态置 REVERSED，记录保留。"""
    if txn.status != "POSTED":
        raise BusinessError("只有已入账的交易可以冲正")
    original_entry = get_entry(db, txn.id)
    if original_entry is None:
        raise BusinessError("原交易缺少分录，无法冲正")
    if original_entry.entry_type == "REVERSAL":
        raise BusinessError("冲正交易不能再次冲正")
    if (
        db.query(JournalEntry)
        .join(InvestmentTransaction, InvestmentTransaction.id == JournalEntry.transaction_id)
        .filter(InvestmentTransaction.reversal_of_id == txn.id)
        .first()
        is not None
    ):
        raise BusinessError("该交易已冲正")

    # 持仓一致性保护（docs/ledger-rules.md §11：批次是成本分摊轨迹）
    if txn.transaction_type in SECURITY_BUY_TYPES:
        from app.positions.service import PositionLot

        lots = db.query(PositionLot).filter_by(origin_transaction_id=txn.id).all()
        if not lots:
            raise BusinessError("原交易缺少持仓批次，无法冲正")
        if any(lot.remaining_quantity != lot.quantity for lot in lots):
            raise BusinessError("该买入形成的批次已被卖出，不能冲正，请录入反向卖出交易更正")
    elif txn.transaction_type in SECURITY_SELL_TYPES:
        # shortcut: 卖出冲正需还原批次消耗轨迹，暂未开放，升级时机：出现真实冲正需求
        raise BusinessError("卖出交易的冲正暂不开放，请录入反向买入交易更正持仓与成本")

    reversal = InvestmentTransaction(
        account_id=txn.account_id,
        counter_account_id=txn.counter_account_id,
        instrument_id=txn.instrument_id,
        transaction_type=txn.transaction_type,
        status="POSTED",
        business_date=txn.business_date,
        currency=txn.currency,
        total_amount=txn.total_amount,
        memo=f"冲正 {txn.memo or ''}".strip(),
        reversal_of_id=txn.id,
    )
    db.add(reversal)
    db.flush()

    reversal_entry = JournalEntry(
        transaction_id=reversal.id,
        entry_type="REVERSAL",
        reversal_of_entry_id=original_entry.id,
        memo=f"冲正 {txn.id}",
    )
    db.add(reversal_entry)
    db.flush()
    for line in (
        db.query(JournalLine)
        .filter_by(entry_id=original_entry.id)
        .order_by(JournalLine.line_no, JournalLine.id)
    ):
        direction = CREDIT if line.direction == DEBIT else DEBIT
        db.add(
            JournalLine(
                entry_id=reversal_entry.id,
                ledger_account_id=line.ledger_account_id,
                direction=direction,
                amount=line.amount,
                line_no=line.line_no,
            )
        )

    txn.status = "REVERSED"
    # 买入冲正：删除其形成的批次（已校验未被消耗），保持批次与分录一致
    if txn.transaction_type in SECURITY_BUY_TYPES:
        from app.positions.service import PositionLot

        for lot in db.query(PositionLot).filter_by(origin_transaction_id=txn.id):
            db.delete(lot)
    record_audit(
        db,
        "transaction.reverse",
        "investment_transaction",
        str(txn.id),
        {"reversal_id": str(reversal.id)},
    )
    return reversal
