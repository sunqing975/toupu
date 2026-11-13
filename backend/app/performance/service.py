# 账本派生服务：现金/数量/成本/已实现/未实现/分红 + 外部现金流边界。
# 口径全部来自 docs/ledger-rules.md §17.2/§17.3：账本是事实来源，快照与收益只读取、不写账本。
# 关键约束：金额一律 Decimal；借=+ / 贷=−；成本双口径交叉校验；行情缺失不静默用 0。
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.instruments.models import Instrument
from app.ledger.models import JournalLine, LedgerAccount
from app.market_data.provider import QuoteView, resolve_quote
from app.performance.formulas import CashFlow, Valuation
from app.positions.service import PositionLot
from app.transactions.models import InvestmentTransaction

Q6 = Decimal("0.000001")


@dataclass(frozen=True)
class PositionValuation:
    account_id: uuid.UUID
    instrument: Instrument
    quantity: Decimal
    book_cost: Decimal
    quote: QuoteView

    @property
    def valued(self) -> bool:
        """FRESH/STALE 是正式报价（STALE 仍可用于估值但要标状态）；ESTIMATED/UNKNOWN 不估值。"""
        return self.quote.price is not None and self.quote.status in ("FRESH", "STALE")

    @property
    def market_value(self) -> Decimal | None:
        if not self.valued or self.quote.price is None:
            return None
        return (self.quantity * self.quote.price).quantize(Q6)

    @property
    def unrealized(self) -> Decimal | None:
        mv = self.market_value
        return None if mv is None else (mv - self.book_cost).quantize(Q6)


@dataclass(frozen=True)
class Derived:
    as_of: date
    positions: list[PositionValuation]
    cash_total: Decimal
    realized_total: Decimal
    dividend_income: Decimal
    book_cost_total: Decimal

    @property
    def total_positions(self) -> int:
        return len(self.positions)

    @property
    def valued_positions(self) -> int:
        return sum(1 for position in self.positions if position.valued)

    @property
    def market_value(self) -> Decimal:
        return sum((position.market_value or Decimal(0) for position in self.positions), Decimal(0))

    @property
    def unrealized_total(self) -> Decimal:
        return sum((position.unrealized or Decimal(0) for position in self.positions), Decimal(0))

    @property
    def total_assets(self) -> Decimal:
        return self.cash_total + self.market_value

    @property
    def coverage(self) -> Decimal:
        if self.total_positions == 0:
            return Decimal(1)
        return (Decimal(self.valued_positions) / Decimal(self.total_positions)).quantize(Q6)

    @property
    def data_quality(self) -> str:
        if self.total_positions == 0 or self.valued_positions == self.total_positions:
            return "COMPLETE"
        if self.valued_positions == 0:
            return "NO_QUOTES"
        return "PARTIAL"


def _account_total(db: Session, account_type: str) -> Decimal:
    """Σ 分录行（DEBIT 为正 / CREDIT 为负），冲正分录方向翻转故自动抵消。"""
    rows = db.execute(
        select(JournalLine.direction, func.sum(JournalLine.amount))
        .join(LedgerAccount, LedgerAccount.id == JournalLine.ledger_account_id)
        .where(LedgerAccount.account_type == account_type)
        .group_by(JournalLine.direction)
    ).all()
    total = Decimal(0)
    for direction, amount in rows:
        total += amount if direction == "DEBIT" else -amount
    return total


def _income_credit(db: Session, account_type: str) -> Decimal:
    """收入类取 CREDIT 合计（已实现损失为 DEBIT，单独扣除）。"""
    rows = db.execute(
        select(JournalLine.direction, func.sum(JournalLine.amount))
        .join(LedgerAccount, LedgerAccount.id == JournalLine.ledger_account_id)
        .where(LedgerAccount.account_type == account_type)
        .group_by(JournalLine.direction)
    ).all()
    total = Decimal(0)
    for direction, amount in rows:
        total += amount if direction == "CREDIT" else -amount
    return total


def derive(
    db: Session,
    as_of: date,
    stale_days: int = 7,
    provider_name: str = "MANUAL",
) -> Derived:
    """从账本与持仓批次派生当前估值（v1 仅支持当前实时余额，不支持历史回放，§17.2）。"""
    lots = db.execute(select(PositionLot).where(PositionLot.remaining_quantity > 0)).scalars().all()
    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[PositionLot]] = {}
    for lot in lots:
        grouped.setdefault((lot.investment_account_id, lot.instrument_id), []).append(lot)

    instrument_ids = {instrument_id for _, instrument_id in grouped}
    instruments: dict[uuid.UUID, Instrument] = {}
    if instrument_ids:
        instruments = {
            instrument.id: instrument
            for instrument in db.execute(
                select(Instrument).where(Instrument.id.in_(instrument_ids))
            )
            .scalars()
            .all()
        }

    positions: list[PositionValuation] = []
    for (account_id, instrument_id), group in sorted(
        grouped.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))
    ):
        instrument = instruments.get(instrument_id)
        if instrument is None:
            continue
        quantity = sum((lot.remaining_quantity for lot in group), Decimal(0))
        book_cost = sum((lot.total_cost for lot in group), Decimal(0))
        quote = resolve_quote(db, instrument, as_of, stale_days, provider_name)
        positions.append(PositionValuation(account_id, instrument, quantity, book_cost, quote))

    book_cost_total = sum((position.book_cost for position in positions), Decimal(0))
    security_balance = _account_total(db, "SECURITY")
    if security_balance != book_cost_total:
        raise ValueError(
            "持仓成本与证券科目余额不一致："
            f"批次合计 {book_cost_total}，科目余额 {security_balance}；拒绝生成快照"
        )

    realized_total = _income_credit(db, "REALIZED_GAIN") - _income_credit(db, "REALIZED_LOSS")
    dividend_income = _income_credit(db, "DIVIDEND_INCOME")
    return Derived(
        as_of=as_of,
        positions=positions,
        cash_total=_account_total(db, "CASH"),
        realized_total=realized_total,
        dividend_income=dividend_income,
        book_cost_total=book_cost_total,
    )


# 外部现金流边界（§17.3）：账户间转账不属于组合外部现金流。
_EXTERNAL_TYPES = ("DEPOSIT", "WITHDRAW", "OPENING_BALANCE")


def external_cashflows(db: Session, as_of: date) -> tuple[list[CashFlow], bool]:
    """返回 (现金流, 是否有期初资本/入金)。投资者视角：投入为负、收回为正（§17.4）。"""
    txns = (
        db.execute(
            select(InvestmentTransaction).where(
                InvestmentTransaction.transaction_type.in_(_EXTERNAL_TYPES),
                InvestmentTransaction.status == "POSTED",
                InvestmentTransaction.reversal_of_id.is_(None),
                InvestmentTransaction.business_date <= as_of,
                InvestmentTransaction.total_amount.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    flows: list[CashFlow] = []
    has_capital = False
    for txn in txns:
        amount = txn.total_amount
        if amount is None:
            continue
        if txn.transaction_type == "DEPOSIT":
            flows.append((txn.business_date, -amount))
            has_capital = True
        elif txn.transaction_type == "WITHDRAW":
            flows.append((txn.business_date, amount))
        else:  # OPENING_BALANCE：期初账面净值作为期初资本基数
            flows.append((txn.business_date, -amount))
            has_capital = True
    return flows, has_capital


def portfolio_points(db: Session) -> list[Valuation]:
    """TWR/MDD 的统一口径净值序列（§17.5/§17.6），来自已保存的组合快照。"""
    from app.market_data.models import PortfolioSnapshot

    rows = db.execute(
        select(PortfolioSnapshot.snapshot_date, PortfolioSnapshot.total_assets).order_by(
            PortfolioSnapshot.snapshot_date
        )
    ).all()
    return [(row[0], row[1]) for row in rows]
