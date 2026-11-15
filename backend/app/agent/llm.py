# OpenAI 兼容大模型客户端（docs/agent-framework.md §分析会话）。
# 仅做 HTTP 调用，不引入任何 SDK 依赖；密钥来自数据库中已配置的 AgentModel，
# 调用前才解密读取，绝不回显。所有调用都在 Agent 专用会话里进行，模型只拿到
# 只读数据快照 + 自然语言问题，无法直接写账本。
from __future__ import annotations

from app.agent.models import AgentModel


def _default_model_id(db) -> str | None:
    from sqlalchemy import select

    row = db.execute(select(AgentModel).where(AgentModel.is_default.is_(True))).scalars().first()
    if row is not None:
        return str(row.id)
    row = db.execute(select(AgentModel).order_by(AgentModel.created_at.desc())).scalars().first()
    return str(row.id) if row is not None else None


def _resolve_model(db, model_id: str | None) -> AgentModel:
    row = db.get(AgentModel, _as_uuid(model_id)) if model_id else None
    if row is None:
        rid = _default_model_id(db)
        if rid is None:
            raise _NoModelConfigured()
        row = db.get(AgentModel, _as_uuid(rid))
        if row is None:
            raise _NoModelConfigured()
    return row


def _as_uuid(value: str):
    import uuid

    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise _NoModelConfigured() from None


class _NoModelConfigured(Exception):
    pass
