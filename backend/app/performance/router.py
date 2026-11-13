# 收益指标 API：summary（账面派生汇总）与 returns（XIRR/TWR/MDD + status/missing）。
# 公式与口径见 docs/ledger-rules.md §17.2-§17.6/§17.8；估值缺失返回状态，不静默用 0 或旧值。
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.db.session import get_db
from app.performance.formulas import MddResult, TwrResult, max_drawdown, twr, xirr
from app.performance.service import (
    Derived,
    derive,
    external_cashflows,
    portfolio_points,
)

router = APIRouter(prefix="/api/v1/performance", tags=["performance"])

Status = Literal["OK", "INSUFFICIENT_DATA", "NO_SOLUTION"]


class SummaryOut(BaseModel):
    as_of: date
    cash_total: Decimal
    market_value: Decimal
    total_assets: Decimal
    realized_total: Decimal
    dividend_income: Decimal
    unrealized_total: Decimal
    book_cost_total: Decimal
    coverage: Decimal
    valued_positions: int
    total_positions: int
    data_quality: str


class MetricOut(BaseModel):
    status: Status
    value: Decimal | None
    missing: list[date] = []
    reason: str | None = None
    peak_date: date | None = None
    trough_date: date | None = None


class ReturnsOut(BaseModel):
    as_of: date
    xirr: MetricOut
    twr: MetricOut
    max_drawdown: MetricOut


def _summary_out(derived: Derived) -> SummaryOut:
    return SummaryOut(
        as_of=derived.as_of,
        cash_total=derived.cash_total,
        market_value=derived.market_value,
        total_assets=derived.total_assets,
        realized_total=derived.realized_total,
        dividend_income=derived.dividend_income,
        unrealized_total=derived.unrealized_total,
        book_cost_total=derived.book_cost_total,
        coverage=derived.coverage,
        valued_positions=derived.valued_positions,
        total_positions=derived.total_positions,
        data_quality=derived.data_quality,
    )


@router.get("/summary", response_model=SummaryOut)
def summary(
    as_of: date | None = None,
    stale_days: int = Query(default=7, ge=0),
    db: Session = Depends(get_db),
) -> SummaryOut:
    as_of = as_of or date.today()
    try:
        derived = derive(db, as_of, stale_days)
    except ValueError as exc:
        raise BusinessError(str(exc)) from None
    return _summary_out(derived)


def _metric_from_twr(result: TwrResult) -> MetricOut:
    return MetricOut(
        status=result.status,
        value=result.value,
        missing=list(result.missing),
        reason=result.reason,
    )


def _metric_from_mdd(result: MddResult) -> MetricOut:
    return MetricOut(
        status=result.status,
        value=result.value,
        peak_date=result.peak_date,
        trough_date=result.trough_date,
    )


@router.get("/returns", response_model=ReturnsOut)
def returns(
    as_of: date | None = None,
    stale_days: int = Query(default=7, ge=0),
    db: Session = Depends(get_db),
) -> ReturnsOut:
    as_of = as_of or date.today()
    try:
        derived = derive(db, as_of, stale_days)
    except ValueError as exc:
        raise BusinessError(str(exc)) from None

    # XIRR（§17.4）：外部现金流 + 期末估值；覆盖率不足或无期初资本 → INSUFFICIENT_DATA。
    flows, has_capital = external_cashflows(db, as_of)
    if derived.coverage < Decimal(1) or not has_capital:
        xirr_metric = MetricOut(
            status="INSUFFICIENT_DATA",
            value=None,
            reason="行情覆盖不全或缺少期初资本/入金，无法给出可信 XIRR",
        )
    else:
        cashflows = [*flows, (as_of, derived.total_assets)]
        rate = xirr(cashflows)
        if rate is None:
            xirr_metric = MetricOut(
                status="NO_SOLUTION", value=None, reason="现金流两端同号，XIRR 无解"
            )
        else:
            xirr_metric = MetricOut(status="OK", value=rate)

    # TWR（§17.5）：基于组合快照序列 + 不可变外部现金流（F_i = −CF_i）。
    points = portfolio_points(db)
    f_flows = [(day, -amount) for day, amount in flows]
    twr_metric = _metric_from_twr(twr(points, f_flows, as_of))

    # 最大回撤（§17.6）：统一口径的组合净值序列。
    mdd_metric = _metric_from_mdd(max_drawdown(points))

    return ReturnsOut(as_of=as_of, xirr=xirr_metric, twr=twr_metric, max_drawdown=mdd_metric)
