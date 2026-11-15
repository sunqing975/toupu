# Agent 实体 CRUD（M7 对齐 WeKnora 的 CustomAgent），含内置「投谱助手」种子。
# Agent 实体 = 一等配置实体：模型 + 系统提示词 + 启用的技能 + 挂载的外部 MCP。
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import skills as skills_mod
from app.agent.models import AgentDefinition, AgentMcpServer, AgentSkill
from app.agent.roles import OPERATOR_DESCRIPTION, OPERATOR_PROMPT, operator_tools
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent/definitions", tags=["agent-definitions"])


# 内置操作助手不挂载投资分析工具；投资 Agent 后续单独建立。
_BUILTIN_KEY = "toupu-assistant"
_BUILTIN_CREATED = False


def ensure_builtin(db: Session) -> None:
    """首次访问时确保内置 Agent + 内置技能目录已存在（幂等）。"""
    existing = db.execute(select(AgentSkill)).scalars().first()
    if existing is None:
        _seed_skills(db)
    builtin = (
        db.execute(select(AgentDefinition).where(AgentDefinition.key == _BUILTIN_KEY))
        .scalars()
        .first()
    )
    if builtin is None:
        db.add(
            AgentDefinition(
                key=_BUILTIN_KEY,
                name="投谱助手",
                description=OPERATOR_DESCRIPTION,
                icon="Bot",
                is_builtin=True,
                avatar_color="#1e40af",
                system_prompt=OPERATOR_PROMPT,
                enabled_skill_keys=operator_tools(skills_mod.SKILLS),
                mcp_server_ids=[],
            )
        )
        db.commit()


def _seed_skills(db: Session) -> None:
    now = datetime.now(UTC)
    rows = [
        AgentSkill(
            key=k,
            name=s.name,
            description=s.description,
            category=s.category,
            builtin=True,
            enabled=True,
            created_at=now,
        )
        for k, s in skills_mod.SKILLS.items()
    ]
    db.add_all(rows)
    db.commit()


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str
    icon: str | None = None
    category: str
    builtin: bool
    enabled: bool


class AgentDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str
    icon: str | None = None
    is_builtin: bool
    avatar_color: str | None = None
    system_prompt: str
    model_id: uuid.UUID | None = None
    enabled_skill_keys: list[str]
    skill_package_keys: list[str] = []
    mcp_server_ids: list[str]
    created_at: datetime
    updated_at: datetime


class SkillPatch(BaseModel):
    enabled: bool


class AgentDefinitionIn(BaseModel):
    key: str
    name: str
    description: str = ""
    icon: str | None = None
    avatar_color: str | None = None
    system_prompt: str = ""
    model_id: str | None = None
    enabled_skill_keys: list[str] = []
    skill_package_keys: list[str] = []
    mcp_server_ids: list[str] = []


class AgentDefinitionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    avatar_color: str | None = None
    system_prompt: str | None = None
    model_id: str | None = None
    enabled_skill_keys: list[str] | None = None
    skill_package_keys: list[str] | None = None
    mcp_server_ids: list[str] | None = None


def _out(agent: AgentDefinition) -> AgentDefinitionOut:
    return AgentDefinitionOut.model_validate(agent, from_attributes=True)


def _out_or_404(agent: AgentDefinition | None) -> AgentDefinitionOut:
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return _out(agent)


def _as_uuid(value: str | None):
    try:
        return uuid.UUID(value) if value else None
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=422, detail="model_id 不是合法的 UUID") from None


def _valid_skill_keys(keys: list[str]) -> list[str]:
    valid = set(skills_mod.SKILLS.keys())
    return [k for k in keys if k in valid]


@router.get("", response_model=list[AgentDefinitionOut])
def list_definitions(db: Session = Depends(get_db)) -> list[AgentDefinition]:
    ensure_builtin(db)
    return list(
        db.execute(select(AgentDefinition).order_by(AgentDefinition.created_at)).scalars().all()
    )


@router.get("/skills", response_model=list[SkillOut])
def list_skills(db: Session = Depends(get_db)) -> list[AgentSkill]:
    ensure_builtin(db)
    return list(
        db.execute(select(AgentSkill).order_by(AgentSkill.category, AgentSkill.name))
        .scalars()
        .all()
    )


def globally_enabled_keys(db: Session) -> set[str]:
    """技能总开关：被停用的技能对所有 Agent 都不注入（用户反馈「技能管理界面」）。"""
    ensure_builtin(db)
    return set(
        db.execute(select(AgentSkill.key).where(AgentSkill.enabled.is_(True))).scalars().all()
    )


@router.patch("/skills/{skill_key}", response_model=SkillOut)
def toggle_skill(skill_key: str, payload: SkillPatch, db: Session = Depends(get_db)) -> SkillOut:
    """静态 /skills/{skill_key} 必须排在 /{agent_id} 之前注册，否则会被当成 agent_id。"""
    ensure_builtin(db)
    if skill_key not in skills_mod.SKILLS:
        raise HTTPException(status_code=404, detail="技能不存在")
    row = db.execute(select(AgentSkill).where(AgentSkill.key == skill_key)).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    row.enabled = payload.enabled
    db.commit()
    db.refresh(row)
    return SkillOut.model_validate(row, from_attributes=True)


@router.get("/{agent_id}", response_model=AgentDefinitionOut)
def get_definition(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> AgentDefinition:
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return agent


def _validate_bindings(db: Session, packages: list[str], servers: list[str]) -> None:
    known = set(db.scalars(select(AgentSkill.key).where(AgentSkill.category == "instruction")))
    if any(key not in known for key in packages):
        raise HTTPException(422, "技能目录不存在，请刷新后重新选择")
    known_servers = {str(value) for value in db.scalars(select(AgentMcpServer.id))}
    if any(value not in known_servers for value in servers):
        raise HTTPException(422, "MCP 服务不存在，请刷新后重新选择")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentDefinitionOut)
def create_definition(
    payload: AgentDefinitionIn, db: Session = Depends(get_db)
) -> AgentDefinitionOut:
    ensure_builtin(db)
    existing = (
        db.execute(select(AgentDefinition).where(AgentDefinition.key == payload.key))
        .scalars()
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Agent key 已存在")
    if not payload.key.strip() or not payload.name.strip():
        raise HTTPException(status_code=422, detail="key 与 name 不能为空")
    _validate_bindings(db, payload.skill_package_keys, payload.mcp_server_ids)
    agent = AgentDefinition(
        key=payload.key.strip(),
        name=payload.name.strip(),
        description=payload.description,
        icon=payload.icon,
        avatar_color=payload.avatar_color,
        system_prompt=payload.system_prompt,
        model_id=_as_uuid(payload.model_id),
        enabled_skill_keys=_valid_skill_keys(payload.enabled_skill_keys),
        mcp_server_ids=list(payload.mcp_server_ids),
        skill_package_keys=list(payload.skill_package_keys),
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _out_or_404(agent)


@router.patch("/{agent_id}", response_model=AgentDefinitionOut)
def update_definition(
    agent_id: uuid.UUID, payload: AgentDefinitionPatch, db: Session = Depends(get_db)
) -> AgentDefinitionOut:
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    _validate_bindings(
        db,
        payload.skill_package_keys if payload.skill_package_keys is not None else [],
        payload.mcp_server_ids if payload.mcp_server_ids is not None else [],
    )
    if payload.name is not None:
        agent.name = payload.name.strip()
    if payload.description is not None:
        agent.description = payload.description
    if payload.icon is not None:
        agent.icon = payload.icon
    if payload.avatar_color is not None:
        agent.avatar_color = payload.avatar_color
    if payload.system_prompt is not None:
        agent.system_prompt = payload.system_prompt
    if payload.model_id is not None:
        agent.model_id = _as_uuid(payload.model_id)
    if payload.enabled_skill_keys is not None:
        agent.enabled_skill_keys = _valid_skill_keys(payload.enabled_skill_keys)
    if payload.skill_package_keys is not None:
        agent.skill_package_keys = list(payload.skill_package_keys)
    if payload.mcp_server_ids is not None:
        agent.mcp_server_ids = list(payload.mcp_server_ids)
    agent.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(agent)
    return _out_or_404(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_definition(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if agent.is_builtin:
        raise HTTPException(status_code=409, detail="内置 Agent 不可删除")
    db.delete(agent)
    db.commit()
