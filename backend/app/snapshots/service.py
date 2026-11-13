# 快照重建服务：从账本 + 持仓批次 + 行情派生，单事务先删后建保证同日幂等。
# 规则依据 docs/ledger-rules.md §17.7 / database-design.md §3（快照可删除重建）。
# v1 仅按当前实时余额生成快照；snapshot_date 是保存标签，不是历史回放参数（§17.2）。
from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.errors import BusinessError
from app.market_data.models import PortfolioSnapshot, PositionSnapshot
from app.performance.service import derive


def rebuild_snapshots(
    db: Session,
    snapshot_date: date,
    stale_days: int = 7,
    provider_name: str = "MANUAL",
) -> tuple[PortfolioSnapshot, int]:
    """删除该日快照后重建；任一步失败整批回滚，不留半套快照。"""
    try:
        derived = derive(db, snapshot_date, stale_days, provider_name)
    except ValueError as exc:
        raise BusinessError(str(exc)) from None

    try:
        db.execute(delete(PositionSnapshot).where(PositionSnapshot.snapshot_date == snapshot_date))
        db.execute(
            delete(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date == snapshot_date)
        )
        db.flush()

        for position in derived.positions:
            db.add(
                PositionSnapshot(
                    snapshot_date=snapshot_date,
                    account_id=position.account_id,
                    instrument_id=position.instrument.id,
                    quantity=position.quantity,
                    book_cost=position.book_cost,
                    quote_price=position.quote.price,
                    quote_status=position.quote.status,
                    quote_date=position.quote.quote_date,
                    quote_provider=position.quote.provider,
                    market_value=position.market_value,
                    unrealized=position.unrealized,
                )
            )

        portfolio = PortfolioSnapshot(
            snapshot_date=snapshot_date,
            cash_total=derived.cash_total,
            market_value=derived.market_value,
            total_assets=derived.total_assets,
            realized_total=derived.realized_total,
            dividend_income=derived.dividend_income,
            unrealized_total=derived.unrealized_total,
            coverage=derived.coverage,
            valued_positions=derived.valued_positions,
            total_positions=derived.total_positions,
            data_quality=derived.data_quality,
        )
        db.add(portfolio)
        db.flush()
        record_audit(
            db,
            "snapshot.rebuild",
            "portfolio_snapshot",
            str(portfolio.id),
            {
                "snapshot_date": snapshot_date.isoformat(),
                "positions": derived.total_positions,
                "coverage": str(derived.coverage),
            },
        )
        db.commit()
        return portfolio, derived.total_positions
    except Exception:
        db.rollback()
        raise


def list_snapshots(db: Session, limit: int = 100) -> list[PortfolioSnapshot]:
    return list(
        db.execute(
            select(PortfolioSnapshot).order_by(PortfolioSnapshot.snapshot_date.desc()).limit(limit)
        )
        .scalars()
        .all()
    )


def positions_on(db: Session, snapshot_date: date) -> list[PositionSnapshot]:
    return list(
        db.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.snapshot_date == snapshot_date)
            .order_by(PositionSnapshot.account_id, PositionSnapshot.instrument_id)
        )
        .scalars()
        .all()
    )
