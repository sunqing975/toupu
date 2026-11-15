import uuid
from decimal import Decimal

import pytest

from app.accounts.service import AccountCreate, create_account_record
from app.db.session import SessionLocal
from app.funds.history import HistoryIn, import_history
from app.instruments.models import Instrument


def test_history_atomic_replay_and_redemption(monkeypatch):
    with SessionLocal() as db:
        a = create_account_record(
            db, AccountCreate(name=uuid.uuid4().hex, account_type="FUND_PLATFORM"), source="test"
        )
        i = Instrument(instrument_type="FUND", market="CN", code=uuid.uuid4().hex[:12], name="test")
        db.add(i)
        db.flush()
        p = HistoryIn.model_validate(
            {
                "account_id": str(a.id),
                "instrument_id": str(i.id),
                "request_key": uuid.uuid4().hex,
                "user_confirmed": True,
                "expected_shares": "15",
                "rows": [
                    {
                        "order_id": "one",
                        "kind": "SUBSCRIBE",
                        "posting_date": "2026-01-01",
                        "amount": "100",
                        "shares": "10",
                        "nav": "9.9",
                        "fee": "1",
                        "evidence": {"source_image": "test"},
                    },
                    {
                        "order_id": "two",
                        "kind": "CONVERSION_BOUNDARY",
                        "posting_date": "2026-01-02",
                        "amount": "100",
                        "shares": "10",
                        "nav": "10",
                        "fee": "0",
                        "evidence": {"source_image": "test", "source_cost_unknown": True},
                    },
                    {
                        "order_id": "three",
                        "kind": "REDEEM",
                        "posting_date": "2026-01-03",
                        "amount": "60",
                        "shares": "5",
                        "nav": "12",
                        "fee": "0",
                        "evidence": {"source_image": "test"},
                    },
                ],
            }
        )
        from app.funds import history

        def fail(*a, **k):
            raise RuntimeError("audit failure")

        with monkeypatch.context() as m:
            m.setattr(history, "record_audit", fail)
            with pytest.raises(RuntimeError, match="audit failure"):
                import_history(db, p)
            db.rollback()
        # Metadata rolled back too: recreate it using the same IDs.
        a = create_account_record(
            db, AccountCreate(name=uuid.uuid4().hex, account_type="FUND_PLATFORM"), source="test"
        )
        i = Instrument(instrument_type="FUND", market="CN", code=uuid.uuid4().hex[:12], name="test")
        db.add(i)
        db.flush()
        p.account_id = a.id
        p.instrument_id = i.id
        r = import_history(db, p)
        assert Decimal(r["quantity"]) == 15
        assert Decimal(r["book_cost"]) == 150
        assert import_history(db, p) == r
        db.rollback()
