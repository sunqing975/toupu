"""M5 收益指标验收：XIRR / TWR / 最大回撤的人工基准与边界（docs/ledger-rules.md §17.4-§17.6）。

纯函数测试不依赖数据库，便于人工复核；金额一律 Decimal，禁止 float。
人工基准：XIRR A/B = 0.100000、C 无解；TWR 连乘 = 0.210000、无现金流 = 0.150000；
MDD 序列 = −0.250000。
"""

from datetime import date
from decimal import Decimal

from app.performance.formulas import (
    max_drawdown,
    merge_cashflows,
    npv,
    twr,
    xirr,
)

D0 = date(2026, 1, 1)
D1 = date(2027, 1, 1)
D2 = date(2028, 1, 1)


def test_xirr_benchmark_a_single_period() -> None:
    """−100000@2026-01-01 / +110000@2027-01-01 → 10%。"""
    flows = [(D0, Decimal("-100000")), (D1, Decimal("110000"))]
    assert xirr(flows) == Decimal("0.100000")


def test_xirr_benchmark_b_multi_period() -> None:
    """−100000 + 50000/1.1 + 66000/1.21 = 0 → 10%。"""
    flows = [
        (D0, Decimal("-100000")),
        (D1, Decimal("50000")),
        (D2, Decimal("66000")),
    ]
    assert xirr(flows) == Decimal("0.100000")


def test_npv_benchmark_b_at_solution_is_zero() -> None:
    flows = [
        (D0, Decimal("-100000")),
        (D1, Decimal("50000")),
        (D2, Decimal("66000")),
    ]
    assert abs(npv(Decimal("0.1"), flows, D0)) < Decimal("1e-25")


def test_xirr_no_solution_same_sign() -> None:
    """两端同号（全为投入）→ None，由调用方标注 NO_SOLUTION，不猜测。"""
    assert xirr([(D0, Decimal("-100000")), (D1, Decimal("-10000"))]) is None


def test_xirr_insufficient_flows() -> None:
    assert xirr([]) is None
    assert xirr([(D0, Decimal("-100000"))]) is None


def test_merge_cashflows_same_day() -> None:
    merged = merge_cashflows(
        [
            (D1, Decimal("50000")),
            (D0, Decimal("-100000")),
            (D1, Decimal("16000")),
        ]
    )
    assert merged == [(D0, Decimal("-100000")), (D1, Decimal("66000"))]


def test_twr_benchmark_chained() -> None:
    """points=[(01-01,100000),(06-30,110000),(12-31,143000)]，flow 06-30 +20000 → 21%。"""
    points = [
        (date(2026, 1, 1), Decimal("100000")),
        (date(2026, 6, 30), Decimal("110000")),
        (date(2026, 12, 31), Decimal("143000")),
    ]
    flows = [(date(2026, 6, 30), Decimal("20000"))]
    result = twr(points, flows, date(2026, 12, 31))
    assert result.status == "OK"
    assert result.value == Decimal("0.210000")
    assert result.missing == ()


def test_twr_benchmark_no_flows() -> None:
    points = [
        (date(2026, 1, 1), Decimal("100000")),
        (date(2026, 12, 31), Decimal("115000")),
    ]
    result = twr(points, [], date(2026, 12, 31))
    assert result.status == "OK"
    assert result.value == Decimal("0.150000")


def test_twr_insufficient_data_few_points() -> None:
    result = twr([(D0, Decimal("100000"))], [], D1)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.value is None
    assert result.missing == (D1,)


def test_twr_insufficient_data_missing_terminal() -> None:
    points = [(D0, Decimal("100000")), (date(2026, 6, 30), Decimal("110000"))]
    result = twr(points, [], D1)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.reason == "估值日缺少组合快照"


def test_twr_insufficient_data_flow_before_first_snapshot() -> None:
    """现金流发生在首个快照之前 → 缺 V_i^-，不插值不猜测。"""
    points = [
        (date(2026, 6, 30), Decimal("110000")),
        (date(2026, 12, 31), Decimal("143000")),
    ]
    flows = [(date(2026, 1, 1), Decimal("100000"))]
    result = twr(points, flows, date(2026, 12, 31))
    assert result.status == "INSUFFICIENT_DATA"
    assert date(2026, 1, 1) in result.missing


def test_max_drawdown_benchmark() -> None:
    points = [
        (date(2026, 1, 1), Decimal("100")),
        (date(2026, 1, 2), Decimal("120")),
        (date(2026, 1, 3), Decimal("90")),
        (date(2026, 1, 4), Decimal("150")),
        (date(2026, 1, 5), Decimal("120")),
    ]
    result = max_drawdown(points)
    assert result.status == "OK"
    assert result.value == Decimal("-0.250000")
    assert result.peak_date == date(2026, 1, 2)
    assert result.trough_date == date(2026, 1, 3)


def test_max_drawdown_insufficient_data() -> None:
    result = max_drawdown([(D0, Decimal("100"))])
    assert result.status == "INSUFFICIENT_DATA"
    assert result.value is None


def test_max_drawdown_no_drawdown_is_zero() -> None:
    points = [(D0, Decimal("100")), (D1, Decimal("120"))]
    result = max_drawdown(points)
    assert result.status == "OK"
    assert result.value == Decimal("0.000000")


def test_six_decimal_precision_of_metrics() -> None:
    """收益率统一六位小数输出（§14 / §17.9）。"""
    rate = xirr([(D0, Decimal("-100000")), (D2, Decimal("121000"))])
    assert rate is not None
    assert -rate.as_tuple().exponent == 6
    twr_value = twr([(D0, Decimal("100000")), (D1, Decimal("111111"))], [], D1).value
    assert twr_value is not None
    assert -twr_value.as_tuple().exponent == 6
