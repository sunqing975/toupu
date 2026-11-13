# 风险应用服务：把账本派生数据喂给确定性引擎，落事件、处理状态（只写 risk_events + audit_logs）。
# 依据 docs/risk-agent-rules.md §4/§5：扫描幂等、冷却、只改状态不删除、写审计。
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import InvestmentAccount
from app.audit import record_audit
from app.core.errors import BusinessError
from app.performance.formulas import Valuation
from app.performance.service import derive, portfolio_points
from app.risk.engine import (
    DerivedData,
    PositionData,
    RuleSpec,
    ScanResult,
    evaluate,
)
from app.risk.models import RiskEvent, RiskRule


def _rule_specs(db: Session) -> list[RuleSpec]:
    rules = (
        db.execute(select(RiskRule).where(RiskRule.enabled.is_(True)).order_by(RiskRule.created_at))
        .scalars()
        .all()
    )
    return [
        RuleSpec(
            id=rule.id,
            scope=rule.scope,
            rule_type=rule.rule_type,
            threshold=rule.threshold,
            severity=rule.severity,
            cooldown_minutes=rule.cooldown_minutes,
            name=rule.memo or rule.rule_type,
        )
        for rule in rules
    ]


def _account_names(db: Session) -> dict[uuid.UUID, str]:
    return {
        account.id: account.name
        for account in db.execute(select(InvestmentAccount)).scalars().all()
    }


def _derived_data(db: Session, as_of: date) -> DerivedData:
    derived = derive(db, as_of)
    names = _account_names(db)
    positions = [
        PositionData(
            account_id=str(position.account_id),
            account_name=names.get(position.account_id, str(position.account_id)),
            instrument_id=str(position.instrument.id),
            instrument_name=position.instrument.name,
            valued=position.valued,
            market_value=position.market_value,
        )
        for position in derived.positions
    ]
    return DerivedData(
        total_assets=derived.total_assets,
        coverage=derived.coverage,
        total_positions=derived.total_positions,
        positions=positions,
    )


def _points(db: Session) -> list[Valuation]:
    return portfolio_points(db)


def _existing_keys(db: Session, as_of: date) -> set[str]:
    return set(
        db.execute(select(RiskEvent.dedup_key).where(RiskEvent.as_of == as_of)).scalars().all()
    )


def _last_event_times(db: Session) -> dict[tuple[uuid.UUID, str], datetime]:
    result: dict[tuple[uuid.UUID, str], datetime] = {}
    events = db.execute(select(RiskEvent.rule_id, RiskEvent.subject, RiskEvent.triggered_at))
    for rule_id, subject, triggered_at in events:
        if triggered_at is None:
            continue
        key = (rule_id, subject)
        current = result.get(key)
        if current is None or triggered_at > current:
            result[key] = triggered_at
    return result


def scan(db: Session, as_of: date, now: datetime) -> ScanResult:
    """确定性扫描并落事件；同日幂等、冷却抑制；不写任何账本表。"""
    rules = _rule_specs(db)
    result = evaluate(
        rules=rules,
        derived=_derived_data(db, as_of),
        points=_points(db),
        as_of=as_of,
        now=now,
        existing_dedup_keys=_existing_keys(db, as_of),
        last_event_times=_last_event_times(db),
    )
    for spec in result.created:
        db.add(
            RiskEvent(
                rule_id=spec.rule_id,
                as_of=spec.as_of,
                scope=spec.scope,
                subject=spec.subject,
                rule_type=spec.rule_type,
                severity=spec.severity,
                trigger_value=spec.trigger_value,
                threshold=spec.threshold,
                message=spec.message,
                status="OPEN",
                dedup_key=spec.dedup_key,
                triggered_at=now,
            )
        )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    record_audit(
        db,
        "risk.scan",
        "risk_scan",
        str(as_of),
        {"created": len(result.created), "skipped": len(result.skipped)},
    )
    db.commit()
    return result


def list_events(
    db: Session,
    status: str | None,
    severity: str | None,
    rule_id: uuid.UUID | None,
    limit: int,
) -> list[RiskEvent]:
    query = select(RiskEvent).order_by(RiskEvent.triggered_at.desc())
    if status:
        query = query.where(RiskEvent.status == status)
    if severity:
        query = query.where(RiskEvent.severity == severity)
    if rule_id:
        query = query.where(RiskEvent.rule_id == rule_id)
    return list(db.execute(query.limit(limit)).scalars().all())


def resolve_event(
    db: Session, event_id: uuid.UUID, action: str, note: str | None, now: datetime
) -> RiskEvent:
    event = db.get(RiskEvent, event_id)
    if event is None:
        raise BusinessError("风险事件不存在", status_code=404)
    if event.status != "OPEN":
        raise BusinessError("该风险事件已处理")
    event.status = "ACKNOWLEDGED" if action == "acknowledge" else "IGNORED"
    event.resolved_at = now
    event.resolution_note = note
    db.commit()
    db.refresh(event)
    record_audit(
        db,
        f"risk.event.{action}",
        "risk_event",
        str(event_id),
        {"status": event.status, "note": note},
    )
    db.commit()
    return event
