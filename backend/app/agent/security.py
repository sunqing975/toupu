# Agent Token 校验与只读网关元信息（docs/risk-agent-rules.md §7/§8）。
# 明文只在创建时返回一次；库里只存 sha256；每次调用（含失败）写 agent_operations。
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.risk.models import AgentOperation, AgentToken

VALID_SCOPES = frozenset(
    {
        "read:accounts",
        "read:positions",
        "read:transactions",
        "read:market",
        "read:performance",
        "read:risk",
        "read:plans",
        "read:proposals",
        "write:proposals",
    }
)


def hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def log_operation(
    db: Session,
    token_id,
    resource: str,
    scope: str | None,
    http_status: int,
    detail: dict | None = None,
) -> None:
    """只追加审计；成功调用由调用方更新 last_used_at。"""
    db.add(
        AgentOperation(
            token_id=token_id,
            resource=resource,
            scope=scope,
            http_status=http_status,
            detail=detail,
        )
    )
    db.commit()


def _record_failure(resource: str, http_status: int, reason: str) -> None:
    """校验失败也留痕（agent_operations.token_id 可空）。"""
    with SessionLocal() as db:
        log_operation(db, None, resource, None, http_status, {"reason": reason})


def require_scope(
    x_agent_token: str | None,
    scope: str,
    resource: str,
    db: Session,
) -> AgentToken:
    """校验 X-Agent-Token 存在、active、未吊销、具备所需 scope。"""
    if x_agent_token is None:
        _record_failure(resource, 401, "missing token")
        raise HTTPException(status_code=401, detail="Agent Token 无效")
    token = (
        db.execute(select(AgentToken).where(AgentToken.token_hash == hash_token(x_agent_token)))
        .scalars()
        .one_or_none()
    )
    if token is None:
        _record_failure(resource, 401, "invalid token")
        raise HTTPException(status_code=401, detail="Agent Token 无效")
    if token.revoked_at is not None or not token.active:
        log_operation(db, token.id, resource, scope, 401, {"reason": "revoked"})
        raise HTTPException(status_code=401, detail="Agent Token 已吊销")
    if scope not in (token.scopes or []):
        log_operation(db, token.id, resource, scope, 403, {"reason": "scope missing"})
        raise HTTPException(status_code=403, detail=f"Agent Token 缺少 scope：{scope}")
    return token


def log_success(db: Session, token: AgentToken, resource: str, scope: str) -> None:
    """成功调用：写 agent_operations + 更新 last_used_at。"""
    log_operation(db, token.id, resource, scope, 200)
    token.last_used_at = datetime.now(UTC)
    db.commit()


class Meta(BaseModel):
    as_of: str
    source: str
    is_estimate: bool = False
    is_delayed: bool = False
    missing: list[str] = []
    queried_at: str


def meta(
    as_of: str,
    source: str,
    *,
    is_estimate: bool = False,
    is_delayed: bool = False,
    missing: list[str] | None = None,
) -> Meta:
    return Meta(
        as_of=as_of,
        source=source,
        is_estimate=is_estimate,
        is_delayed=is_delayed,
        missing=missing or [],
        queried_at=datetime.now(UTC).isoformat(),
    )
