"""Recorded platform overview, explicitly separate from ledger valuation."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/api/v1/performance", tags=["performance"])


def recorded_overview(db: Session) -> dict:
    batches = (
        db.execute(
            text("""SELECT DISTINCT ON (account_id) id,account_id,observed_on
        FROM platform_asset_batches ORDER BY account_id,observed_on DESC,created_at DESC""")
        )
        .mappings()
        .all()
    )
    items = []
    for batch in batches:
        rows = (
            db.execute(
                text("SELECT * FROM platform_asset_items WHERE batch_id=:id"), {"id": batch["id"]}
            )
            .mappings()
            .all()
        )
        for row in rows:
            items.append(
                {
                    **dict(row),
                    "account_id": batch["account_id"],
                    "observed_on": batch["observed_on"],
                }
            )

    def total(key):
        return str(sum((r[key] for r in items if r[key] is not None), Decimal(0)))

    accounts = (
        db.execute(text("SELECT id,name FROM investment_accounts WHERE status='ACTIVE'"))
        .mappings()
        .all()
    )
    observed = {b["account_id"] for b in batches}
    dates = sorted({str(b["observed_on"]) for b in batches})
    return {
        "recorded_assets": total("market_value") if items else None,
        "platform_holding_pnl": total("holding_pnl") if items else None,
        "platform_cumulative_pnl": total("cumulative_pnl")
        if items and all(r["cumulative_pnl"] is not None for r in items)
        else None,
        "item_count": len(items),
        "advisory_count": sum(r["kind"] == "ADVISORY" for r in items),
        "observation_dates": dates,
        "unrecorded_accounts": [a["name"] for a in accounts if a["id"] not in observed],
        "items": [
            {k: str(v) if isinstance(v, Decimal) else v for k, v in r.items()} for r in items
        ],
        "basis": "PLATFORM_OBSERVATION_ONLY",
        "warning": (
            "最近平台截图金额，仅汇总已录资产，不叠加同名账本持仓；"
            "不是实时估值或全部账户净资产。平台累计收益仅含当前列表项目，"
            "不能还原全部历史收益。"
        ),
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    return recorded_overview(db)
