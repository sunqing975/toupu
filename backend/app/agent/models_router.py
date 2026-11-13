# Agent 模型配置 CRUD（docs/agent-framework.md §模型配置）。
# 密钥 api_key 只写不读：列表/详情响应一律不回显明文或哈希。
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.models import AgentModel
from app.audit import record_audit
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent/models", tags=["agent-models"])


class AgentModelIn(BaseModel):
    name: str
    display_name: str | None = None
    provider: str = "openai-compatible"
    base_url: str
    model: str
    api_key: str | None = None
    is_default: bool = False


class AgentModelPatch(BaseModel):
    name: str | None = None
    display_name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    is_default: bool | None = None


class AgentModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_name: str | None = None
    provider: str
    base_url: str
    model: str
    is_default: bool
    created_at: str  # 序列化便于前端展示


def _out(row: AgentModel) -> AgentModelOut:
    return AgentModelOut(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        is_default=row.is_default,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def _clear_other_defaults(db: Session, *, except_id: uuid.UUID | None = None) -> None:
    stmt = select(AgentModel).where(AgentModel.is_default.is_(True))
    if except_id is not None:
        stmt = stmt.where(AgentModel.id != except_id)
    for other in db.execute(stmt).scalars().all():
        other.is_default = False


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentModelOut)
def create_model(payload: AgentModelIn, db: Session = Depends(get_db)) -> AgentModelOut:
    if payload.is_default:
        _clear_other_defaults(db)
    model = AgentModel(
        name=payload.name,
        display_name=payload.display_name,
        provider=payload.provider,
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
        is_default=payload.is_default,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    record_audit(db, "agent.model.create", "agent_model", str(model.id), {"name": payload.name})
    db.commit()
    return _out(model)


@router.get("", response_model=list[AgentModelOut])
def list_models(db: Session = Depends(get_db)) -> list[AgentModelOut]:
    rows = db.execute(select(AgentModel).order_by(AgentModel.created_at.desc())).scalars().all()
    return [_out(m) for m in rows]


@router.get("/{model_id}", response_model=AgentModelOut)
def get_model(model_id: uuid.UUID, db: Session = Depends(get_db)) -> AgentModelOut:
    model = db.get(AgentModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return _out(model)


@router.patch("/{model_id}", response_model=AgentModelOut)
def update_model(
    model_id: uuid.UUID, payload: AgentModelPatch, db: Session = Depends(get_db)
) -> AgentModelOut:
    model = db.get(AgentModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    data = payload.model_dump(exclude_unset=True)
    if "is_default" in data and data["is_default"] is True:
        _clear_other_defaults(db, except_id=model_id)
    for field, value in data.items():
        if value is None and field == "api_key":
            continue  # 不把密钥清空为 None，除非显式传空串
        setattr(model, field, value)
    db.commit()
    db.refresh(model)
    record_audit(db, "agent.model.update", "agent_model", str(model_id))
    db.commit()
    return _out(model)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    model = db.get(AgentModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    db.delete(model)
    db.commit()
    record_audit(db, "agent.model.delete", "agent_model", str(model_id))
    db.commit()
