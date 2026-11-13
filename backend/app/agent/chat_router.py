# Agent 分析/对话会话（docs/agent-framework.md §专用会话）。
# 安全边界：会话里模型只能看到只读数据快照（委托 resources）+ 用户问题；
# 不直接写账本。若用户想执行操作，模型应给出建议，由用户走网页端/提案流程。
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent import llm
from app.agent.models import AgentModel
from app.agent.resources import (
    positions,
    proposals,
    returns,
    risk_events,
    summary,
    valuation,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent", tags=["agent-chat"])


class ChatIn(BaseModel):
    question: str
    as_of: str | None = None  # YYYY-MM-DD，缺省视为今天
    model_id: str | None = None


class ChatOut(BaseModel):
    answer: str
    model_id: str | None = None
    model_name: str | None = None
    as_of: str


_SYSTEM = (
    "你是投谱 Toupu 的个人投资分析助手。你只能基于下面提供的「只读数据快照」回答用户问题，"
    "不要编造快照之外的持仓、交易或账户信息。你可以做定性分析、风险提示和计划建议，"
    "但任何会改变账本的操作（入账、买卖、赎回等）都必须由用户在网页端执行，"
    "你只能给出建议与理由。使用中文、简洁、带数字时保留原始精度。"
)


def _snapshot(db: Session, as_of: date) -> str:
    parts: list[str] = []
    data, meta = summary(db, as_of)
    parts.append(f"[组合概览 {meta.queried_at}] {data}")
    data, meta = valuation(db, as_of)
    parts.append(f"[估值明细 {meta.queried_at}] {data}")
    data, meta = returns(db, as_of)
    parts.append(f"[收益指标 {meta.queried_at}] {data}")
    data, meta = positions(db)
    parts.append(f"[持仓 {meta.queried_at}] {data}")
    data, meta = risk_events(db)
    parts.append(f"[风险事件 {meta.queried_at}] {data}")
    data, meta = proposals(db)
    parts.append(f"[待审批提案 {meta.queried_at}] {data}")
    return "\n".join(parts)


@router.post("/chat", response_model=ChatOut)
def agent_chat(payload: ChatIn, db: Session = Depends(get_db)) -> ChatOut:
    try:
        as_of = date.fromisoformat(payload.as_of) if payload.as_of else date.today()
    except ValueError:
        raise HTTPException(status_code=422, detail="as_of 日期格式应为 YYYY-MM-DD") from None

    snapshot = _snapshot(db, as_of)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"以下是当前只读数据快照：\n{snapshot}"},
        {"role": "user", "content": payload.question},
    ]

    cfg: AgentModel | None = None
    if payload.model_id:
        cfg = db.get(AgentModel, _as_uuid(payload.model_id))
    else:
        from sqlalchemy import select

        cfg = (
            db.execute(select(AgentModel).where(AgentModel.is_default.is_(True))).scalars().first()
        )
        if cfg is None:
            cfg = (
                db.execute(select(AgentModel).order_by(AgentModel.created_at.desc()))
                .scalars()
                .first()
            )

    try:
        answer = llm.chat(db, messages, model_id=str(cfg.id) if cfg else None)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatOut(
        answer=answer,
        model_id=str(cfg.id) if cfg else None,
        model_name=(cfg.display_name or cfg.name) if cfg else None,
        as_of=as_of.isoformat(),
    )


def _as_uuid(value: str):
    import uuid

    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return None
