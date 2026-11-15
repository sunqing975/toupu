from decimal import Decimal

from app.performance import holdings_overview as mod


def test_projection_replaces_matching_snapshot_with_quote(monkeypatch):
    from datetime import date
    from types import SimpleNamespace as S

    account = "account"
    snapshot = {
        "items": [
            {
                "account_id": account,
                "code": "008585",
                "market_value": "120",
                "observed_on": "2026-11-14",
            },
            {
                "id": "combo",
                "account_id": account,
                "code": None,
                "kind": "ADVISORY",
                "name": "组合",
                "market_value": "50",
                "holding_pnl": "-2",
                "observed_on": "2026-11-14",
            },
        ]
    }
    monkeypatch.setattr(mod, "recorded_overview", lambda db: snapshot)
    p = S(
        account_id=account,
        instrument=S(id="fund", code="008585", name="基金", instrument_type="FUND"),
        market_value=Decimal("100"),
        quantity=Decimal("10"),
        book_cost=Decimal("110"),
        unrealized=Decimal("-10"),
        quote=S(quote_date=date(2026, 11, 13)),
    )
    monkeypatch.setattr(mod, "derive", lambda *args: S(positions=[p]))

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def __iter__(self):
            return iter(self.rows)

        def mappings(self):
            return self.rows

    class DB:
        def execute(self, q):
            return (
                Result([(account, "账户")])
                if "SELECT id,name" in str(q)
                else Result(
                    [
                        {
                            "account_id": account,
                            "observed_on": date(2026, 11, 14),
                            "payload": {"pending": [{"amount": "20"}]},
                        }
                    ]
                )
            )

    d = mod.holdings_overview(DB())
    assert len(d["rows"]) == 2
    assert d["holdings_value"] == "150"
    assert d["recorded_assets"] == "170"
    assert d["pending_total"] == "20"
