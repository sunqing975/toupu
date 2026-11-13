# 期初资产分录处理器（M4）。
# docs/ledger-rules.md §10 / §16.3：
#   - 期初现金：借 CASH 贷 OPENING_BALANCE（外部资金平衡科目）同额，不记为 DEPOSIT。
#   - 期初持仓：借 SECURITY 贷 OPENING_BALANCE 同额，同时建立 lot_origin=OPENING_BALANCE 的
#     「期初汇总批次」，单位成本 = 账面成本 / 数量（由总额推导，不接受用户传入）。
#   - 期初余额不是历史买入，不产生现金流出，不伪造历史成交日期。
# 与证券/基金处理器保持分离（agent.md §3），仅复用 ledger 科目与 positions 底层。
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.ledger.service import (
    CREDIT,
    DEBIT,
    Line,
    get_or_create_cash,
    get_or_create_external,
    get_or_create_security,
)
from app.opening_balances.models import OpeningBalanceDetail
from app.positions.service import open_position_lot
from app.transactions.models import InvestmentTransaction


def opening_balance_lines(db: Session, txn: InvestmentTransaction) -> list[Line]:
    detail = db.query(OpeningBalanceDetail).filter_by(transaction_id=txn.id).one_or_none()
    if detail is None:
        raise BusinessError("期初交易缺少明细，不能过账")
    amount = txn.total_amount
    if amount is None or amount <= 0:
        raise BusinessError("期初交易缺少有效金额，不能过账")

    external = get_or_create_external(db, txn.currency)
    if detail.row_kind == "CASH":
        cash = get_or_create_cash(db, txn.account_id, txn.currency)
        return [(cash, DEBIT, amount), (external, CREDIT, amount)]

    if detail.row_kind == "POSITION":
        if txn.instrument_id is None:
            raise BusinessError("期初持仓缺少投资品种，不能过账")
        quantity = detail.quantity
        if quantity is None or quantity <= 0:
            raise BusinessError("期初持仓缺少有效数量，不能过账")
        security = get_or_create_security(
            db,
            txn.account_id,
            txn.instrument_id,
            txn.currency,  # type: ignore[arg-type]
        )
        open_position_lot(db, txn, quantity, amount, "OPENING_BALANCE", txn.business_date)
        return [(security, DEBIT, amount), (external, CREDIT, amount)]

    raise BusinessError(f"未知的期初行类型：{detail.row_kind}")
