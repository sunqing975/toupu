# 收益指标纯函数：XIRR / TWR / 最大回撤。
# 公式、正负号约定、求解区间与人工基准全部来自 docs/ledger-rules.md §17.4/§17.5/§17.6。
# 这里不依赖数据库/HTTP，便于人工基准测试复核（agent.md §6/§9、§12）。
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

Q6 = Decimal("0.000001")
DAY_BASE = Decimal(365)
RATE_LO = Decimal("-0.9999")
RATE_HI = Decimal("10")
NPV_TOL = Decimal("1e-10")
_CALC_PREC = 50

CashFlow = tuple[date, Decimal]
Valuation = tuple[date, Decimal]

Status = Literal["OK", "INSUFFICIENT_DATA", "NO_SOLUTION"]


@dataclass(frozen=True)
class TwrResult:
    status: Status
    value: Decimal | None
    missing: tuple[date, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class MddResult:
    status: Status
    value: Decimal | None
    peak_date: date | None = None
    trough_date: date | None = None


def merge_cashflows(cashflows: list[CashFlow]) -> list[CashFlow]:
    """同日多笔先合并，再按日期升序（§17.4）。"""
    by_date: dict[date, Decimal] = {}
    for day, amount in cashflows:
        by_date[day] = by_date.get(day, Decimal(0)) + amount
    return [(day, by_date[day]) for day in sorted(by_date)]


def npv(rate: Decimal, cashflows: list[CashFlow], d0: date) -> Decimal:
    """NPV(r) = Σ CF_i / (1+r)^((d_i-d0)/365)，Decimal 分数指数，不引入 float。"""
    with localcontext() as ctx:
        ctx.prec = _CALC_PREC
        base = Decimal(1) + rate
        total = Decimal(0)
        for day, amount in cashflows:
            exponent = Decimal((day - d0).days) / DAY_BASE
            total += amount / (base**exponent)
        return total


def xirr(cashflows: list[CashFlow]) -> Decimal | None:
    """投资者视角 XIRR；cashflows 需已包含期末估值项（正）。

    r ∈ (−0.9999, 10] 二分 200 次、|NPV| < 1e-10 收敛；
    两端 NPV 同号（无解/多解歧义）返回 None，由调用方标注 NO_SOLUTION，不猜测。
    """
    flows = merge_cashflows(cashflows)
    if len(flows) < 2:
        return None
    d0 = flows[0][0]
    lo, hi = RATE_LO, RATE_HI
    flo, fhi = npv(lo, flows, d0), npv(hi, flows, d0)
    if flo == 0:
        return lo.quantize(Q6)
    if fhi == 0:
        return hi.quantize(Q6)
    if (flo > 0) == (fhi > 0):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if mid in (lo, hi):
            break
        fm = npv(mid, flows, d0)
        if abs(fm) < NPV_TOL:
            return mid.quantize(Q6)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi, fhi = mid, fm
    return ((lo + hi) / 2).quantize(Q6)


def twr(points: list[Valuation], flows: list[CashFlow], as_of: date) -> TwrResult:
    """TWR = Π(1+r_i) − 1，按外部现金流发生点切分子期间。

    points 为已保存组合快照 (日期, 估值)；flows 为 (日期, F_i)，F_i 为净外部流入
    （与 XIRR 的 CF 正负号相反，§17.5）。每个现金流日期取 snapshot_date <= d_i
    的最近快照作 V_i^-；V_0 取首个快照；as_of 当天必须有快照作 V_T^-。
    缺估值或 V_{i-1} <= 0 → INSUFFICIENT_DATA 并列出缺失日期，不插值不猜测。
    """
    ordered = sorted(points, key=lambda item: item[0])
    if len(ordered) < 2:
        return TwrResult("INSUFFICIENT_DATA", None, (as_of,), "组合快照少于两个估值点")
    if ordered[0][1] <= 0:
        return TwrResult("INSUFFICIENT_DATA", None, (ordered[0][0],), "期初估值必须大于 0")
    terminal = next((value for day, value in ordered if day == as_of), None)
    if terminal is None:
        return TwrResult("INSUFFICIENT_DATA", None, (as_of,), "估值日缺少组合快照")

    v_prev = ordered[0][1]
    growth = Decimal(1)
    missing: list[date] = []
    # 与期末同日或之后的现金流不参与子期间切分（期末估值单独处理）。
    relevant = merge_cashflows([(day, amount) for day, amount in flows if day < as_of])
    for day, flow in relevant:
        pre: Decimal | None = None
        for snap_day, snap_value in ordered:
            if snap_day <= day:
                pre = snap_value
            else:
                break
        if pre is None:
            missing.append(day)
            continue
        if v_prev <= 0:
            return TwrResult("INSUFFICIENT_DATA", None, tuple(missing), "子期间起点估值必须大于 0")
        growth *= pre / v_prev
        v_prev = pre + flow
    if missing:
        return TwrResult("INSUFFICIENT_DATA", None, tuple(missing), "现金流日期前缺少组合快照")
    if v_prev <= 0:
        return TwrResult("INSUFFICIENT_DATA", None, (as_of,), "子期间起点估值必须大于 0")
    growth *= terminal / v_prev
    return TwrResult("OK", (growth - 1).quantize(Q6))


def max_drawdown(points: list[Valuation]) -> MddResult:
    """MDD = min_t(V_t / max_{s<=t} V_s − 1)，基于统一口径的组合净值序列。"""
    ordered = sorted(points, key=lambda item: item[0])
    if len(ordered) < 2:
        return MddResult("INSUFFICIENT_DATA", None)
    peak, peak_date = ordered[0][1], ordered[0][0]
    worst = Decimal(0)
    worst_peak, worst_trough = ordered[0][0], ordered[0][0]
    for day, value in ordered:
        if value > peak:
            peak, peak_date = value, day
        if peak <= 0:
            continue
        drawdown = value / peak - 1
        if drawdown < worst:
            worst, worst_peak, worst_trough = drawdown, peak_date, day
    return MddResult("OK", worst.quantize(Q6), worst_peak, worst_trough)
