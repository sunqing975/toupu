import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.accounts.service import AccountCreate, create_account_record
from app.db.session import SessionLocal
from app.funds.advisory import BatchIn, portfolio_summary, save_flows
from app.imports.platform_assets import BatchIn as SnapshotIn
from app.imports.platform_assets import save_batch


def test_advisory_flows_no_fake_shares_or_double_fees():
    with SessionLocal() as db:
        a = create_account_record(
            db, AccountCreate(name=uuid.uuid4().hex, account_type="FUND_PLATFORM"), source="test"
        )
        save_batch(
            db,
            SnapshotIn.model_validate(
                {
                    "account_id": str(a.id),
                    "observed_on": "2026-11-14",
                    "source": "test",
                    "request_key": uuid.uuid4().hex,
                    "items": [
                        {
                            "name": "组合",
                            "kind": "ADVISORY",
                            "market_value": "900",
                            "holding_pnl": "-100",
                        }
                    ],
                }
            ),
        )
        p = BatchIn.model_validate(
            {
                "account_id": str(a.id),
                "portfolio_name": "组合",
                "flows": [
                    {
                        "external_id": "a",
                        "kind": "CONTRIBUTION",
                        "occurred_on": "2026-01-01",
                        "amount": "1000",
                        "subsidy": "1",
                        "evidence": {"source": "test"},
                    },
                    {
                        "external_id": "b",
                        "kind": "FEE",
                        "occurred_on": "2026-01-02",
                        "amount": "2",
                        "fee_scope": "UNKNOWN",
                        "evidence": {"source": "user"},
                    },
                ],
            }
        )
        counts = [
            db.scalar(text("select count(*) from " + t))
            for t in ["investment_transactions", "position_lots"]
        ]
        assert save_flows(db, p)["inserted"] == 2
        assert save_flows(db, p)["inserted"] == 0
        result = portfolio_summary(db, a.id, "组合", date(2026, 11, 14), Decimal("900"))
        assert result["nominal_pnl"] == "-100.00"
        assert result["personal_pnl"] == "-99.00"
        assert result["unknown_fees"] == "2.00"
        assert counts == [
            db.scalar(text("select count(*) from " + t))
            for t in ["investment_transactions", "position_lots"]
        ]
        p.flows[0].amount = Decimal("2000")
        with pytest.raises(HTTPException):
            save_flows(db, p)
        db.rollback()
