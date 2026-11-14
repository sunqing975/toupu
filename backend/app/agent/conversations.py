# Agent 会话持久化：历史会话存库、可回看/续聊（用户反馈「历史会话也要存」）。
# 会话与消息分表；chat_router 每次问答都调用 append_message 落库。
# 安全：历史消息仅作为对话上下文注入 LLM，不改变账本。
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.models import AgentConversation, AgentMessage
from app.audit import record_audit
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent/conversations", tags=["agent-conversations"])

# 注入 LLM 的历史轮数上限（避免无限增长拖垮上下文）。
HISTORY_LIMIT = 20


def _as_uuid(value: str | None):
    try:
        return uuid.UUID(value) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def create_conversation(
    db: Session,
    *,
    agent_id: str | None = None,
    model_id: str | None = None,
    title: str = "",
) -> AgentConversation:
    conv = AgentConversation(
        title=title[:60],
        agent_id=agent_id,
        model_id=model_id,
    )
    db.add(conv)
    db.flush()
    return conv


def append_message(
    db: Session,
    conversation_id: uuid.UUID,
    *,
    role: str,
    content: str,
    agent_name: str | None = None,
    model_name: str | None = None,
    model_id: str | None = None,
) -> AgentMessage:
    msg = AgentMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        agent_name=agent_name,
        model_name=model_name,
        model_id=model_id,
    )
    db.add(msg)
    conv = db.get(AgentConversation, conversation_id)
    if conv is not None:
        conv.updated_at = datetime.now(UTC)
    return msg


def history_for_llm(db: Session, conversation_id: uuid.UUID) -> list[dict]:
    """返回最近 HISTORY_LIMIT 条 user/assistant 消息，按时间升序，供 LLM 续聊。"""
    rows = list(
        db.execute(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at.desc())
            .limit(HISTORY_LIMIT)
        )
        .scalars()
        .all()
    )
    rows.reverse()
    return [{"role": m.role, "content": m.content} for m in rows if m.role in ("user", "assistant")]


class ConversationPatch(BaseModel):
    title: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    agent_name: str | None = None
    model_name: str | None = None
    model_id: str | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    agent_id: str | None = None
    model_id: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    message_count: int = 0


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = []


def _list_query(db: Session, archived: bool = False):
    counts = dict(
        db.execute(
            select(AgentMessage.conversation_id, func.count()).group_by(
                AgentMessage.conversation_id
            )
        ).all()
    )
    convs = list(
        db.execute(
            select(AgentConversation)
            .where(
                AgentConversation.archived_at.is_not(None)
                if archived
                else AgentConversation.archived_at.is_(None)
            )
            .order_by(AgentConversation.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        ConversationOut(
            id=c.id,
            title=c.title,
            agent_id=c.agent_id,
            model_id=c.model_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
            archived_at=c.archived_at,
            message_count=counts.get(c.id, 0),
        )
        for c in convs
    ]


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    archived: bool = False, db: Session = Depends(get_db)
) -> list[ConversationOut]:
    return _list_query(db, archived)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConversationOut)
def new_conversation(db: Session = Depends(get_db)) -> ConversationOut:
    conv = create_conversation(db)
    db.commit()
    db.refresh(conv)
    return ConversationOut.model_validate(conv, from_attributes=True)


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(
    conversation_id: uuid.UUID, db: Session = Depends(get_db)
) -> ConversationDetailOut:
    conv = db.get(AgentConversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = list(
        db.execute(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at)
        )
        .scalars()
        .all()
    )
    return ConversationDetailOut(
        id=conv.id,
        title=conv.title,
        agent_id=conv.agent_id,
        model_id=conv.model_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        archived_at=conv.archived_at,
        message_count=len(msgs),
        messages=[MessageOut.model_validate(m, from_attributes=True) for m in msgs],
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: uuid.UUID, payload: ConversationPatch, db: Session = Depends(get_db)
) -> ConversationOut:
    conv = db.get(AgentConversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    conv.title = payload.title.strip()[:60]
    conv.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conv)
    return ConversationOut.model_validate(conv, from_attributes=True)


def _archive(db: Session, conversation_id: uuid.UUID, archived: bool) -> ConversationOut:
    conv = db.get(AgentConversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if (conv.archived_at is not None) != archived:
        conv.archived_at = datetime.now(UTC) if archived else None
        record_audit(
            db,
            "conversation.archive" if archived else "conversation.restore",
            "agent_conversation",
            str(conv.id),
        )
        db.commit()
    return ConversationOut.model_validate(conv, from_attributes=True)


@router.post("/{conversation_id}/archive", response_model=ConversationOut)
def archive_conversation(
    conversation_id: uuid.UUID, db: Session = Depends(get_db)
) -> ConversationOut:
    return _archive(db, conversation_id, True)


@router.post("/{conversation_id}/restore", response_model=ConversationOut)
def restore_conversation(
    conversation_id: uuid.UUID, db: Session = Depends(get_db)
) -> ConversationOut:
    return _archive(db, conversation_id, False)
