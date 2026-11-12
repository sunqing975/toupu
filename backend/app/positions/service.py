# 持仓批次模型与移动加权平均成本服务，对应迁移 0001 的 position_lots/position_lot_disposals。
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.errors import BusinessError
from app.db.session import Base
from app.executions.models import TradeExecution
from app.transactions.models import InvestmentTransaction

Q6 = Decimal("0.000001")


class PositionLot(Base):
    __tablename__ = "position_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    investment_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investment_accounts.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"))
    origin_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_transactions.id")
    )
    lot_origin: Mapped[str] = mapped_column(String(20))
    open_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PositionLotDisposal(Base):
    __tablename__ = "position_lot_disposals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("position_lots.id"))
    disposal_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investment_transactions.id")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    disposal_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def open_lots(db: Session, account_id: uuid.UUID, instrument_id: uuid.UUID) -> list[PositionLot]:
    """按开仓日期序的未清零批次（FIFO 消耗顺序；成本口径仍是移动加权平均）。"""
    return list(
        db.execute(
            select(PositionLot)
            .where(
                PositionLot.investment_account_id == account_id,
                PositionLot.instrument_id == instrument_id,
                PositionLot.remaining_quantity > 0,
            )
            .order_by(PositionLot.open_date, PositionLot.created_at)
        ).scalars()
    )


def aggregate(lots: list[PositionLot]) -> tuple[Decimal, Decimal]:
    qty = sum((lot.remaining_quantity for lot in lots), Decimal(0))
    cost = sum((lot.total_cost for lot in lots), Decimal(0))
    return qty, cost


def apply_buy(db: Session, txn: InvestmentTransaction, executions: list[TradeExecution]) -> None:
    """买入：每笔成交形成一个批次，成本含费用（实际现金流出）。"""
    for ex in executions:
        db.add(
            PositionLot(
                investment_account_id=txn.account_id,
                instrument_id=txn.instrument_id,  # type: ignore[arg-type]
                origin_transaction_id=txn.id,
                lot_origin="TRADE",
                open_date=ex.execution_date,
                quantity=ex.quantity,
                remaining_quantity=ex.quantity,
                unit_cost=(ex.net_amount / ex.quantity),
                total_cost=ex.net_amount,
            )
        )
    db.flush()


def apply_sell(
    db: Session, txn: InvestmentTransaction, executions: list[TradeExecution]
) -> Decimal:
    """卖出：移动加权平均计算出库成本；清仓时尾差归零；批次按开仓顺序消耗并留处置记录。

    成本口径为移动加权平均（ledger-rules §11）：出库成本 = 当前单位成本 × 卖出数量，
    单位成本 = 剩余总成本 / 剩余总数量。清仓（卖出数量 = 持有数量）时出库成本直接取
    剩余总成本，尾差归零，不产生残留批次，剩余批次成本按新单位成本重算保持 Σ 精确。
    """
    assert txn.instrument_id is not None
    lots = open_lots(db, txn.account_id, txn.instrument_id)
    total_qty, total_cost = aggregate(lots)
    sell_qty = sum((ex.quantity for ex in executions), Decimal(0))
    if sell_qty > total_qty:
        raise BusinessError(f"持仓不足：持有 {total_qty}，试图卖出 {sell_qty}")

    # 清仓：出库成本 = 剩余总成本，尾差归零（ledger-rules §11）。
    # 不删除批次，仅清零数量与成本，保留处置明细与可追溯轨迹。
    if sell_qty == total_qty:
        for lot in lots:
            lot.remaining_quantity = Decimal(0)
            lot.total_cost = Decimal(0)
        db.flush()
        return total_cost

    unit_cost = total_cost / total_qty
    cost_out_total = (unit_cost * sell_qty).quantize(Q6)

    # FIFO 消耗批次并记录处置明细（用于批次轨迹与可追溯）
    for ex in executions:
        qty_left = ex.quantity
        while qty_left > 0 and lots:
            lot = lots[0]
            take = min(qty_left, lot.remaining_quantity)
            lot.remaining_quantity -= take
            qty_left -= take
            db.add(
                PositionLotDisposal(
                    lot_id=lot.id,
                    disposal_transaction_id=txn.id,
                    quantity=take,
                    cost_amount=(unit_cost * take).quantize(Q6),
                    disposal_date=ex.execution_date,
                )
            )
            if lot.remaining_quantity == 0:
                db.delete(lot)
                lots.pop(0)

    # 剩余批次按「新单位成本 = 剩余总成本 / 剩余总数量」重算成本，Σ 保持精确（尾差归最后批次）
    remaining_total = total_cost - cost_out_total
    remaining_qty = total_qty - sell_qty
    new_unit = remaining_total / remaining_qty if remaining_qty > 0 else Decimal(0)
    allocated = Decimal(0)
    for lot in lots:
        lot_cost = (new_unit * lot.remaining_quantity).quantize(Q6)
        lot.total_cost = lot_cost
        allocated += lot_cost
    residual = remaining_total - allocated
    if residual != 0 and lots:
        lots[-1].total_cost += residual
    db.flush()
    return cost_out_total
