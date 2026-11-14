# Agent 分析/对话会话（对齐 WeKnora 的 Agent 实体 + 技能运行时 + 工具循环）。
# 安全边界：会话里模型只能使用本系统为 Agent 配置的「技能」（只读/分析 + 受控写草稿），
# 不直接写账本；create_draft_proposal 只生成 PENDING，审批在网页端人工确认。
# 用户反馈 (m05823)：历史会话持久化 + 对话框可直接换模型 + 技能总开关生效。
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import llm
from app.agent import skills as skills_mod
from app.agent.conversations import (
    append_message,
    create_conversation,
    history_for_llm,
)
from app.agent.definitions_router import ensure_builtin, globally_enabled_keys
from app.agent.models import AgentConversation, AgentDefinition, AgentModel
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent", tags=["agent-chat"])


class ChatIn(BaseModel):
    question: str
    agent_id: str | None = None  # 指定 Agent 实体；缺省用内置「投谱助手」
    conversation_id: str | None = None  # 续聊已有会话；缺省新建
    model_id: str | None = None  # 对话框顶部临时换模型（覆盖 Agent 绑定与默认）


class ChatOut(BaseModel):
    answer: str
    agent_id: str | None = None
    agent_name: str | None = None
    model_id: str | None = None
    model_name: str | None = None
    conversation_id: str
    title: str


def _as_uuid(value: str | None):
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


def _resolve_model(db: Session, agent: AgentDefinition, override: str | None) -> AgentModel | None:
    # 优先级：对话框临时选择 > Agent 绑定 > 默认 > 最新
    for candidate in (override, str(agent.model_id) if agent.model_id else None):
        if candidate:
            row = db.get(AgentModel, _as_uuid(candidate))
            if row is not None:
                return row
    row = db.execute(select(AgentModel).where(AgentModel.is_default.is_(True))).scalars().first()
    if row is None:
        row = (
            db.execute(select(AgentModel).order_by(AgentModel.created_at.desc())).scalars().first()
        )
    return row


def _tool_schemas(db: Session, agent: AgentDefinition) -> list[dict]:
    enabled = globally_enabled_keys(db)
    schemas = []
    for key in agent.enabled_skill_keys or []:
        if key not in enabled:  # 技能管理页停用后，工具不再注入任何 Agent
            continue
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

    agent = _resolve_agent(db, payload.agent_id or None)
    cfg = _resolve_model(db, agent, payload.model_id)
    if not cfg:
        raise HTTPException(status_code=400, detail="尚未配置可用的模型（设置 → Agent 模型配置）")

    system_prompt = agent.system_prompt or (
        "你是投谱 Toupu 的投资分析助手。你只能使用提供的工具回答，不要编造工具之外的信息。"
    )
    tool_schemas = _tool_schemas(db, agent)
    external_hint = (
        "你可以使用 read_external_knowledge 检索已挂载的外部知识库（如 weknora）。"
        if tool_schemas
        else ""
    )

    # 会话：续聊已有，或新建。历史消息注入 LLM 让对话有记忆。
    conv_id = _as_uuid(payload.conversation_id)
    conv = db.get(AgentConversation, conv_id) if conv_id else None
    if conv is None:
        conv = create_conversation(
            db,
            agent_id=str(agent.id),
            model_id=str(cfg.id),
            title=payload.question.strip()[:60],
        )
        history: list[dict] = []
    else:
        history = history_for_llm(db, conv.id)

    messages = [{"role": "system", "content": system_prompt + external_hint}]
    messages.extend(history)
    messages.append({"role": "user", "content": payload.question})

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

    model_name = cfg.display_name or cfg.name  # type: ignore[union-attr]
    append_message(
        db,
        conv.id,
        role="user",
        content=payload.question,
        agent_name=agent.name,
        model_name=model_name,
        model_id=str(cfg.id),
    )
    append_message(
        db,
        conv.id,
        role="assistant",
        content=answer,
        agent_name=agent.name,
        model_name=model_name,
        model_id=str(cfg.id),
    )
    db.commit()

    return ChatOut(
        answer=answer,
        agent_id=str(agent.id),
        agent_name=agent.name,
        model_id=str(cfg.id),
        model_name=model_name,
        conversation_id=str(conv.id),
        title=conv.title,
    )
