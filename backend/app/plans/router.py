# 投资计划（轻量 CRUD）与 Agent 提案的审批/拒绝/列表/详情（docs/risk-agent-rules.md §9/§10）。
# 审批只在用户命名空间，不读取 X-Agent-Token，因此 Agent 无法直接调用；
# 审批只生成 DRAFT 交易，绝不 confirm/post，绝不写正式账本。
# 路由顺序：/proposals 系列必须注册在 /{plan_id} 之前，否则 /plans/proposals 会被 /{plan_id} 拦截。
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.errors import BusinessError
from app.db.session import get_db
from app.plans.proposal_service import revalidate
from app.risk.models import InvestmentPlan, InvestmentPlanAction, OperationProposal
from app.transactions.router import TransactionIn, create_draft

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


# ---------- 模型 ----------


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    description: str | None = Field(default=None, max_length=200_000)
    target_amount: Decimal | None = Field(default=None, gt=0)


class PlanActionIn(BaseModel):
    title: str
    note: str | None = None
    target_amount: Decimal | None = Field(default=None, gt=0)
    sort_no: int = 0


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    status: str
    target_amount: Decimal | None
    created_at: datetime


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    title: str
    note: str | None
    target_amount: Decimal | None
    sort_no: int
    created_at: datetime


class PlanDetailOut(PlanOut):
    actions: list[ActionOut] = []


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    proposal_type: str
    status: str
    created_by: str
    payload: dict[str, Any]
    impact_preview: dict[str, Any]
    validation_snapshot: dict[str, Any]
    expires_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    resulting_transaction_id: uuid.UUID | None
    created_at: datetime
    is_expired: bool = False


class ResolveIn(BaseModel):
    note: str | None = None


# ---------- 投资计划 ----------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PlanOut)
def create_plan(payload: PlanIn, db: Session = Depends(get_db)) -> InvestmentPlan:
    plan = InvestmentPlan(
        name=payload.name,
        description=payload.description,
        status="ACTIVE",
        target_amount=payload.target_amount,
    )
    db.add(plan)
    db.flush()
    record_audit(db, "plan.create", "investment_plan", str(plan.id), {"name": payload.name})
    db.commit()
    return plan


@router.get("", response_model=list[PlanOut])
def list_plans(
    status_filter: Literal["ACTIVE", "ARCHIVED"] | None = None,
    db: Session = Depends(get_db),
) -> list[InvestmentPlan]:
    stmt = select(InvestmentPlan)
    if status_filter is not None:
        stmt = stmt.where(InvestmentPlan.status == status_filter)
    stmt = stmt.order_by(InvestmentPlan.created_at.desc())
    return list(db.execute(stmt).scalars().all())


# ---------- 提案审批 / 拒绝 / 列表 / 详情（必须在 /{plan_id} 之前注册） ----------


def _proposal_out(proposal: OperationProposal, now: datetime | None = None) -> ProposalOut:
    out = ProposalOut.model_validate(proposal, from_attributes=True)
    out.is_expired = (
        proposal.status == "PENDING" and (now or datetime.now(UTC)) > proposal.expires_at
    )
    return out


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    status_filter: Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED"] | None = None,
    db: Session = Depends(get_db),
) -> list[ProposalOut]:
    stmt = select(OperationProposal)
    if status_filter is not None:
        stmt = stmt.where(OperationProposal.status == status_filter)
    stmt = stmt.order_by(OperationProposal.created_at.desc())
    now = datetime.now(UTC)
    return [_proposal_out(p, now) for p in db.execute(stmt).scalars().all()]


def _get_proposal(db: Session, proposal_id: uuid.UUID) -> OperationProposal:
    proposal = db.scalar(
        select(OperationProposal).where(OperationProposal.id == proposal_id).with_for_update()
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail="提案不存在")
    return proposal


@router.get("/proposals/{proposal_id}", response_model=ProposalOut)
def get_proposal(proposal_id: uuid.UUID, db: Session = Depends(get_db)) -> ProposalOut:
    return _proposal_out(_get_proposal(db, proposal_id))


@router.post("/proposals/{proposal_id}/create-draft", response_model=ProposalOut)
@router.post("/proposals/{proposal_id}/approve", response_model=ProposalOut, deprecated=True)
def approve_proposal(
    proposal_id: uuid.UUID, payload: ResolveIn | None = None, db: Session = Depends(get_db)
) -> ProposalOut:
    now = datetime.now(UTC)
    proposal = _get_proposal(db, proposal_id)
    if proposal.status != "PENDING":
        raise BusinessError("该建议已经处理，不能重复生成记账草稿")
    if now > proposal.expires_at:
        proposal.status = "EXPIRED"
        proposal.resolved_at = now
        proposal.resolved_by = "user"
        proposal.resolution_note = "提案已过期，请重新生成" if payload is None else payload.note
        db.commit()
        raise BusinessError("提案已过期，请重新生成")

    # 审批前重新校验数据，防止账户/金额在创建后被改动
    revalidate(db, proposal)

    # 只生成 DRAFT 交易，绝不 confirm/post，绝不写正式账本
    p = proposal.payload
    amount = Decimal(str(p["amount"]))
    txn_in = TransactionIn(
        transaction_type=p["transaction_type"],
        account_id=uuid.UUID(str(p["account_id"])),
        counter_account_id=(
            uuid.UUID(str(p["counter_account_id"])) if p.get("counter_account_id") else None
        ),
        business_date=date.fromisoformat(str(p["business_date"])),
        amount=amount,
        memo=(p.get("memo") or "Agent 提案审批通过生成的草稿"),
    )
    detail = create_draft(txn_in, db)

    proposal.status = "APPROVED"
    proposal.resolved_at = now
    proposal.resolved_by = "user"
    proposal.resolution_note = None if payload is None else payload.note
    proposal.resulting_transaction_id = detail.id
    record_audit(
        db,
        "proposal.approve",
        "operation_proposal",
        str(proposal.id),
        {"transaction_id": str(detail.id)},
    )
    db.commit()
    return _proposal_out(proposal, now)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(
    proposal_id: uuid.UUID, payload: ResolveIn | None = None, db: Session = Depends(get_db)
) -> ProposalOut:
    now = datetime.now(UTC)
    proposal = _get_proposal(db, proposal_id)
    if proposal.status != "PENDING":
        raise BusinessError("该提案不能重复处理")
    proposal.status = "REJECTED"
    proposal.resolved_at = now
    proposal.resolved_by = "user"
    proposal.resolution_note = None if payload is None else payload.note
    record_audit(
        db,
        "proposal.reject",
        "operation_proposal",
        str(proposal.id),
        {"note": proposal.resolution_note},
    )
    db.commit()
    return _proposal_out(proposal, now)


# ---------- 投资计划详情 / 动作 / 归档（/ {plan_id}，放在 /proposals 之后） ----------


def _get_plan(db: Session, plan_id: uuid.UUID) -> InvestmentPlan:
    plan = db.get(InvestmentPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="投资计划不存在")
    return plan


@router.get("/{plan_id}", response_model=PlanDetailOut)
def get_plan(plan_id: uuid.UUID, db: Session = Depends(get_db)) -> PlanDetailOut:
    plan = _get_plan(db, plan_id)
    actions = list(
        db.execute(
            select(InvestmentPlanAction)
            .where(InvestmentPlanAction.plan_id == plan_id)
            .order_by(InvestmentPlanAction.sort_no, InvestmentPlanAction.created_at)
        )
        .scalars()
        .all()
    )
    out = PlanDetailOut.model_validate(plan, from_attributes=True)
    out.actions = [ActionOut.model_validate(a, from_attributes=True) for a in actions]
    return out


@router.post("/{plan_id}/actions", status_code=status.HTTP_201_CREATED, response_model=ActionOut)
def add_plan_action(
    plan_id: uuid.UUID, payload: PlanActionIn, db: Session = Depends(get_db)
) -> InvestmentPlanAction:
    _get_plan(db, plan_id)
    action = InvestmentPlanAction(
        plan_id=plan_id,
        title=payload.title,
        note=payload.note,
        target_amount=payload.target_amount,
        sort_no=payload.sort_no,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    record_audit(
        db,
        "plan.action.create",
        "investment_plan_action",
        str(action.id),
        {"plan_id": str(plan_id)},
    )
    db.commit()
    return action


@router.post("/{plan_id}/archive", response_model=PlanOut)
def archive_plan(plan_id: uuid.UUID, db: Session = Depends(get_db)) -> InvestmentPlan:
    plan = _get_plan(db, plan_id)
    if plan.status == "ARCHIVED":
        raise BusinessError("该投资计划已归档")
    plan.status = "ARCHIVED"
    db.commit()
    db.refresh(plan)
    record_audit(db, "plan.archive", "investment_plan", str(plan_id))
    db.commit()
    return plan
