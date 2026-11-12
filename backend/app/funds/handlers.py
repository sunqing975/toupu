# 场外基金分录处理器（M3）。
#
# 与证券成交处理器完全分离：证券从 trade_executions 读成交明细，基金从
# fund_order_details / fund_confirmations 读申请与确认结果（agent.md §3）。
# 两者共用 ledger 科目与 positions 移动加权平均成本底层，不混用业务逻辑。
# 规则依据 docs/ledger-rules.md §15：金额一律 Decimal，禁止 float。
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.funds.models import FundConfirmation, FundOrderDetail
from app.ledger.service import (
    CREDIT,
    DEBIT,
    Line,
    get_or_create_cash,
    get_or_create_income,
    get_or_create_security,
)
from app.positions.service import open_position_lot, reduce_position
from app.transactions.models import InvestmentTransaction


def _confirmation(db: Session, txn: InvestmentTransaction) -> FundConfirmation:
    conf = db.query(FundConfirmation).filter_by(transaction_id=txn.id).one_or_none()
    if conf is None:
        raise BusinessError("基金交易缺少确认数据，不能过账")
    return conf


def _security_account(db: Session, txn: InvestmentTransaction):  # type: ignore[no-untyped-def]
    # 基金申请必有标的（check_shape 已校验）
    return get_or_create_security(
        db,
        txn.account_id,
        txn.instrument_id,  # type: ignore[arg-type]
        txn.currency,  # type: ignore[arg-type]
    )


def fund_subscribe_lines(db: Session, txn: InvestmentTransaction) -> list[Line]:
    """申购：成本基础 = 实际现金流出（含申购费），借证券资产、贷现金。

    不单独借记费用，避免同一费用既资本化又费用化（ledger-rules §5 / §15.3）。
    """
    order = db.query(FundOrderDetail).filter_by(transaction_id=txn.id).one_or_none()
    if order is None or order.apply_amount is None:
        raise BusinessError("基金申购缺少实际扣款金额，不能过账")
    conf = _confirmation(db, txn)
    cost = order.apply_amount
    open_position_lot(db, txn, conf.confirmed_shares, cost, "FUND", conf.confirmation_date)
    security = _security_account(db, txn)
    cash = get_or_create_cash(db, txn.account_id, txn.currency)
    return [(security, DEBIT, cost), (cash, CREDIT, cost)]


def fund_redeem_lines(db: Session, txn: InvestmentTransaction) -> list[Line]:
    """赎回：借现金（净到账），贷证券资产（出库成本），差额记已实现损益。"""
    conf = _confirmation(db, txn)
    net = conf.confirmed_amount - conf.fee_amount
    if net <= 0:
        raise BusinessError("赎回净到账金额必须大于 0")
    cost_out = reduce_position(db, txn, [(conf.confirmed_shares, conf.confirmation_date)])
    cash = get_or_create_cash(db, txn.account_id, txn.currency)
    security = _security_account(db, txn)
    lines: list[Line] = [(cash, DEBIT, net)]
    if cost_out > 0:
        lines.append((security, CREDIT, cost_out))
    realized = net - cost_out
    if realized > 0:
        gain = get_or_create_income(db, "REALIZED_GAIN", "已实现收益", txn.currency)
        lines.append((gain, CREDIT, realized))
    elif realized < 0:
        loss = get_or_create_income(db, "REALIZED_LOSS", "已实现损失", txn.currency)
        lines.append((loss, DEBIT, -realized))
    return lines


def cash_dividend_lines(db: Session, txn: InvestmentTransaction) -> list[Line]:
    """现金分红：借现金、贷分红收入；不增加份额、不产生第二条现金流。"""
    order = db.query(FundOrderDetail).filter_by(transaction_id=txn.id).one_or_none()
    if order is None or order.apply_amount is None:
        raise BusinessError("现金分红缺少到账金额，不能过账")
    amount = order.apply_amount
    cash = get_or_create_cash(db, txn.account_id, txn.currency)
    income = get_or_create_income(db, "DIVIDEND_INCOME", "现金分红收入", txn.currency)
    return [(cash, DEBIT, amount), (income, CREDIT, amount)]


def dividend_reinvest_lines(db: Session, txn: InvestmentTransaction) -> list[Line]:
    """红利再投资：借证券资产、贷分红收入；不重复把同一笔分红记作现金。"""
    conf = _confirmation(db, txn)
    amount = conf.confirmed_amount
    if amount <= 0:
        raise BusinessError("红利再投资金额必须大于 0")
    open_position_lot(
        db, txn, conf.confirmed_shares, amount, "DIVIDEND_REINVEST", conf.confirmation_date
    )
    security = _security_account(db, txn)
    income = get_or_create_income(db, "DIVIDEND_INCOME", "现金分红收入", txn.currency)
    return [(security, DEBIT, amount), (income, CREDIT, amount)]
