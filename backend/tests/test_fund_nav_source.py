import uuid
from decimal import Decimal

import pytest

from app.instruments.models import Instrument
from app.market_data.fund_nav_source import parse_navs


def test_published_nav_exact_and_invalid_values():
    i = Instrument(
        id=uuid.uuid4(),
        code="008585",
        instrument_type="FUND",
        currency="CNY",
        market="CN",
        name="test",
    )
    d = {
        "ErrCode": 0,
        "Data": {"LSJZList": [{"FSRQ": "2026-11-13", "DWJZ": "1.3037", "LJJZ": "1.3037"}]},
    }
    r = parse_navs(d, i)
    assert r[0]["nav"] == Decimal("1.3037")
    assert r[0]["data_type"] == "OFFICIAL" and r[0]["provider"] == "EASTMONEY_NAV"
    for value in ["NaN", "-1", "0", "1.1234567"]:
        d["Data"]["LSJZList"][0]["DWJZ"] = value
        with pytest.raises((ValueError, ArithmeticError)):
            parse_navs(d, i)
