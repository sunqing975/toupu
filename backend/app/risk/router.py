# 风险 API：规则管理、确定性扫描、事件处理（docs/risk-agent-rules.md §5/§6/§11）。
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.errors import BusinessError
from app.db.session import get_db
from app.risk.engine import VALID_COMBINATIONS
from app.risk.models import RiskEvent, RiskRule
from app.risk.service import list_events, resolve_event, scan

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])

Scope = Literal["PORTFOLIO", "ACCOUNT", "INSTRUMENT"]
RuleType = Literal["POSITION_WEIGHT", "ACCOUNT_WEIGHT", "PORTFOLIO_DRAWDOWN", "QUOTE_COVERAGE"]
Severity = Literal["INFO", "WARNING", "CRITICAL"]
EventStatus = Literal["OPEN", "ACKNOWLEDGED", "IGNORED"]


class RuleIn(BaseModel):
    scope: Scope
    rule_type: RuleType
    threshold: Decimal = Field(gt=0, le=1)
    severity: Severity = "WARNING"
    enabled: bool = True
    cooldown_minutes: int = Field(default=1440, ge=0)
    memo: str | None = None

    @model_validator(mode="after")
    def check_combination(self) -> "RuleIn":
        if (self.scope, self.rule_type) not in VALID_COMBINATIONS:
            raise ValueError("风险规则范围与类型不匹配")
        return self


class RulePatch(BaseModel):
    threshold: Decimal | None = Field(default=None, gt=0, le=1)
    severity: Severity | None = None
    enabled: bool | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0)
    memo: str | None = None
    scope: Scope | None = None
    rule_type: RuleType | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    rule_type: str
    threshold: Decimal
    severity: str
    enabled: bool
    cooldown_minutes: int
    memo: str | None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    as_of: date
    scope: str
    subject: str
    rule_type: str
    severity: str
    trigger_value: Decimal | None
    threshold: Decimal
    message: str
    status: str
    dedup_key: str
    triggered_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


class SkipOut(BaseModel):
    rule_id: uuid.UUID
    rule_type: str
    subject: str
    reason: str


class ScanOut(BaseModel):
    as_of: date
    evaluated_rules: int
    created: list[EventOut]
    skipped: list[SkipOut]


class ScanIn(BaseModel):
    as_of: date


class ResolveIn(BaseModel):
    note: str | None = None


@router.post("/rules", status_code=status.HTTP_201_CREATED, response_model=RuleOut)
def create_rule(payload: RuleIn, db: Session = Depends(get_db)) -> RiskRule:
    rule = RiskRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    record_audit(db, "risk.rule.create", "risk_rule", str(rule.id), payload.model_dump(mode="json"))
    db.commit()
    return rule


@router.get("/rules", response_model=list[RuleOut])
def get_rules(db: Session = Depends(get_db)) -> list[RiskRule]:
    return list(db.query(RiskRule).order_by(RiskRule.created_at))


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, payload: RulePatch, db: Session = Depends(get_db)) -> RiskRule:
    rule = db.get(RiskRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="风险规则不存在")
    changes = payload.model_dump(exclude_unset=True)
    if "scope" in changes or "rule_type" in changes:
        raise BusinessError("规则范围与类型不可修改")
    for field, value in changes.items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    record_audit(db, "risk.rule.update", "risk_rule", str(rule_id), changes)
    db.commit()
    return rule


@router.post("/scan", response_model=ScanOut)
def run_scan(payload: ScanIn, db: Session = Depends(get_db)) -> ScanOut:
    result = scan(db, payload.as_of, datetime.now(UTC))
    created = list_events(db, None, None, None, 1000)
    created_by_key = {event.dedup_key: event for event in created}
    return ScanOut(
        as_of=payload.as_of,
        evaluated_rules=result.evaluated_rules,
        created=[
            EventOut.model_validate(created_by_key[spec.dedup_key])
            for spec in result.created
            if spec.dedup_key in created_by_key
        ],
        skipped=[
            SkipOut(
                rule_id=spec.rule_id,
                rule_type=spec.rule_type,
                subject=spec.subject,
                reason=spec.reason,
            )
            for spec in result.skipped
        ],
    )


@router.get("/events", response_model=list[EventOut])
def get_events(
    status: EventStatus | None = None,
    severity: Severity | None = None,
    rule_id: uuid.UUID | None = None,
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
) -> list[RiskEvent]:
    return list_events(db, status, severity, rule_id, limit)


@router.post("/events/{event_id}/acknowledge", response_model=EventOut)
def acknowledge_event(
    event_id: uuid.UUID, payload: ResolveIn, db: Session = Depends(get_db)
) -> RiskEvent:
    return resolve_event(db, event_id, "acknowledge", payload.note, datetime.now(UTC))


@router.post("/events/{event_id}/ignore", response_model=EventOut)
def ignore_event(
    event_id: uuid.UUID, payload: ResolveIn, db: Session = Depends(get_db)
) -> RiskEvent:
    return resolve_event(db, event_id, "ignore", payload.note, datetime.now(UTC))
