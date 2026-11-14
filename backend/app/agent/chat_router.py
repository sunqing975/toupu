# Agent 分析/对话会话（对齐 WeKnora 的 Agent 实体 + 技能运行时 + 工具循环）。
# 安全边界：会话里模型只能使用本系统为 Agent 配置的「技能」（只读/分析 + 受控写草稿），
# 不直接写账本；create_draft_proposal 只生成 PENDING，审批在网页端人工确认。
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import llm
from app.agent import skills as skills_mod
from app.agent.definitions_router import ensure_builtin
from app.agent.models import AgentDefinition, AgentModel
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent", tags=["agent-chat"])


class ChatIn(BaseModel):
    question: str
    agent_id: str | None = None  # 指定 Agent 实体；缺省用内置「投谱助手」


class ChatOut(BaseModel):
    answer: str
    agent_id: str | None = None
    agent_name: str | None = None
    model_id: str | None = None
    model_name: str | None = None


def _as_uuid(value: str | None):
    import uuid

    try:
        return uuid.UUID(value) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def _resolve_agent(db: Session, agent_id: str | None) -> AgentDefinition:
    ensure_builtin(db)
    if agent_id:
        agent = db.get(AgentDefinition, _as_uuid(agent_id))
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        return agent
    agent = (
        db.execute(select(AgentDefinition).where(AgentDefinition.key == "toupu-assistant"))
        .scalars()
        .first()
    )
    if agent is None:  # 理论上 ensure_builtin 已建
        raise HTTPException(status_code=500, detail="内置 Agent 未就绪")
    return agent


def _resolve_model(db: Session, agent: AgentDefinition) -> AgentModel | None:
    if agent.model_id:
        return db.get(AgentModel, agent.model_id)
    row = db.execute(select(AgentModel).where(AgentModel.is_default.is_(True))).scalars().first()
    if row is None:
        row = (
            db.execute(select(AgentModel).order_by(AgentModel.created_at.desc())).scalars().first()
        )
    return row


def _tool_schemas(agent: AgentDefinition) -> list[dict]:
    schemas = []
    for key in agent.enabled_skill_keys or []:
        skill = skills_mod.get_skill(key)
        if skill is not None:
            schemas.append(skill.tool_schema())
    return schemas


def _tool_executor(db: Session):
    def _exec(name: str, arguments: str) -> str:
        return skills_mod.execute_skill(db, name, arguments)

    return _exec


@router.post("/chat", response_model=ChatOut)
def agent_chat(payload: ChatIn, db: Session = Depends(get_db)) -> ChatOut:
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="问题不能为空")

    agent = _resolve_agent(db, payload.agent_id)
    cfg = _resolve_model(db, agent)

    system_prompt = agent.system_prompt or (
        "你是投谱 Toupu 的投资分析助手。你只能使用提供的工具回答，不要编造工具之外的信息。"
    )
    tool_schemas = _tool_schemas(agent)
    external_hint = (
        "你可以使用 read_external_knowledge 检索已挂载的外部知识库（如 weknora）。"
        if tool_schemas
        else ""
    )
    messages = [
        {"role": "system", "content": system_prompt + external_hint},
        {"role": "user", "content": payload.question},
    ]

    if not cfg:
        raise HTTPException(status_code=400, detail="尚未配置可用的模型（设置 → Agent 模型配置）")

    try:
        answer = llm.chat_with_tools(
            db,
            messages,
            tool_schemas,
            _tool_executor(db),
            model_id=str(cfg.id),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatOut(
        answer=answer,
        agent_id=str(agent.id),
        agent_name=agent.name,
        model_id=str(cfg.id),
        model_name=(cfg.display_name or cfg.name),
    )
