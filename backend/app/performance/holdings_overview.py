"""Unified display projection; quote valuations and platform evidence stay distinct."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.performance.overview import recorded_overview
from app.performance.service import derive

router = APIRouter(prefix="/api/v1/performance", tags=["performance"])


def holdings_overview(db: Session) -> dict:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    snapshot = recorded_overview(db)
    derived = derive(db, today, 7)
    accounts: dict = {
        r[0]: r[1] for r in db.execute(text("SELECT id,name FROM investment_accounts"))
    }
    observed = {(str(i["account_id"]), i["code"]): i for i in snapshot["items"] if i["code"]}
    used = set()
    rows = []
    for p in derived.positions:
        key = (str(p.account_id), p.instrument.code)
        used.add(key)
        source = observed.get(key)
        value = p.market_value
        basis = "已公布净值" if value is not None else "平台记录（缺净值）"
        if value is None and source:
            value = Decimal(source["market_value"])
        rows.append(
            dict(
                id=str(p.account_id) + ":" + str(p.instrument.id),
                name=p.instrument.name,
                account=accounts.get(p.account_id, "未知账户"),
                kind=p.instrument.instrument_type,
                value=value,
                quantity=str(p.quantity),
                cost=str(p.book_cost),
                pnl=str(p.unrealized) if p.unrealized is not None else None,
                date=str(p.quote.quote_date)
                if p.quote.quote_date
                else str(source["observed_on"])
                if source
                else None,
                basis=basis if value is not None else "缺少报价",
                code=p.instrument.code,
            )
        )
    for item in snapshot["items"]:
        if item["code"] and (str(item["account_id"]), item["code"]) in used:
            continue
        rows.append(
            dict(
                id=str(item["id"]),
                name=item["name"],
                account=accounts.get(item["account_id"], "未知账户"),
                kind=item["kind"],
                value=Decimal(item["market_value"]),
                quantity=None,
                cost=None,
                pnl=item["holding_pnl"],
                date=str(item["observed_on"]),
                basis="平台记录",
                code=item["code"],
            )
        )
    pending = []
    batches = db.execute(
        text("""SELECT DISTINCT ON(account_id) account_id,payload,observed_on
        FROM platform_asset_batches ORDER BY account_id,observed_on DESC,created_at DESC""")
    ).mappings()
    for batch in batches:
        for p in batch["payload"].get("pending", []):
            pending.append(
                {
                    **p,
                    "account": accounts.get(batch["account_id"], "未知账户"),
                    "recorded_on": str(batch["observed_on"]),
                }
            )
    total = sum((r["value"] for r in rows if r["value"] is not None), Decimal(0))
    pending_total = sum((Decimal(p["amount"]) for p in pending), Decimal(0))
    return dict(
        rows=[
            {
                **r,
                "value": str(r["value"]) if r["value"] is not None else None,
                "weight": str(r["value"] / total) if r["value"] is not None and total > 0 else None,
            }
            for r in rows
        ],
        holdings_value=str(total),
        pending_total=str(pending_total),
        pending=pending,
        recorded_assets=str(total + pending_total),
        missing_values=sum(r["value"] is None for r in rows),
        warning="按各项最新已录日期汇总，不是同一时点实时估值；待确认资金来自平台记录，确认后需核对更新，不自动增加份额。",
    )


@router.get("/holdings-overview")
def overview(db: Session = Depends(get_db)) -> dict:
    return holdings_overview(db)
