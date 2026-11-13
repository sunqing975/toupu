# 外部 MCP 服务挂载管理（docs/agent-framework.md §外部 MCP 挂载）。
# CRUD 已在 0010 迁移的 agent_mcp_servers 表；审批/挂载只由管理员在网页端配置，
# Agent 专用会话只读地拉取这些服务的资源。绝不自动调用会修改外部系统的工具。
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.mcp_client import test_connection
from app.agent.models import AgentMcpServer
from app.audit import record_audit
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/agent/mcp-servers", tags=["agent-mcp-servers"])


class McpServerIn(BaseModel):
    name: str
    transport: str  # 'stdio' | 'http'
    command: str | None = None
    url: str | None = None
    config: dict | None = None
    enabled: bool = True


class McpServerPatch(BaseModel):
    name: str | None = None
    transport: str | None = None
    command: str | None = None
    url: str | None = None
    config: dict | None = None
    enabled: bool | None = None


class McpServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    transport: str
    command: str | None = None
    url: str | None = None
    config: dict | None = None
    enabled: bool
    created_at: str


class McpTestResult(BaseModel):
    ok: bool
    detail: str


def _out(row: AgentMcpServer) -> McpServerOut:
    return McpServerOut(
        id=row.id,
        name=row.name,
        transport=row.transport,
        command=row.command,
        url=row.url,
        config=row.config,
        enabled=row.enabled,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def _validate(payload, *, is_create: bool) -> None:
    if payload.transport not in ("stdio", "http"):
        raise HTTPException(status_code=422, detail="transport 仅支持 stdio 或 http")
    if payload.transport == "stdio" and not payload.command:
        raise HTTPException(status_code=422, detail="stdio 传输需要 command")
    if payload.transport == "http" and not payload.url:
        raise HTTPException(status_code=422, detail="http 传输需要 url")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=McpServerOut)
def create_server(payload: McpServerIn, db: Session = Depends(get_db)) -> McpServerOut:
    _validate(payload, is_create=True)
    row = AgentMcpServer(
        name=payload.name,
        transport=payload.transport,
        command=payload.command,
        url=payload.url,
        config=payload.config,
        enabled=payload.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    record_audit(db, "agent.mcp.create", "agent_mcp_server", str(row.id), {"name": payload.name})
    db.commit()
    return _out(row)


@router.get("", response_model=list[McpServerOut])
def list_servers(db: Session = Depends(get_db)) -> list[McpServerOut]:
    rows = (
        db.execute(select(AgentMcpServer).order_by(AgentMcpServer.created_at.desc()))
        .scalars()
        .all()
    )
    return [_out(s) for s in rows]


@router.get("/{server_id}", response_model=McpServerOut)
def get_server(server_id: uuid.UUID, db: Session = Depends(get_db)) -> McpServerOut:
    row = db.get(AgentMcpServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="外部 MCP 服务不存在")
    return _out(row)


@router.patch("/{server_id}", response_model=McpServerOut)
def update_server(
    server_id: uuid.UUID, payload: McpServerPatch, db: Session = Depends(get_db)
) -> McpServerOut:
    row = db.get(AgentMcpServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="外部 MCP 服务不存在")
    data = payload.model_dump(exclude_unset=True)
    transport = data.get("transport", row.transport)
    if transport not in ("stdio", "http"):
        raise HTTPException(status_code=422, detail="transport 仅支持 stdio 或 http")
    if transport == "stdio" and ("command" in data) and not (data.get("command") or row.command):
        raise HTTPException(status_code=422, detail="stdio 传输需要 command")
    if transport == "http" and ("url" in data) and not (data.get("url") or row.url):
        raise HTTPException(status_code=422, detail="http 传输需要 url")
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    record_audit(db, "agent.mcp.update", "agent_mcp_server", str(server_id))
    db.commit()
    return _out(row)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    row = db.get(AgentMcpServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="外部 MCP 服务不存在")
    db.delete(row)
    db.commit()
    record_audit(db, "agent.mcp.delete", "agent_mcp_server", str(server_id))
    db.commit()


@router.post("/{server_id}/test", response_model=McpTestResult)
def test_server(server_id: uuid.UUID, db: Session = Depends(get_db)) -> McpTestResult:
    row = db.get(AgentMcpServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="外部 MCP 服务不存在")
    ok, detail = _run_test(row)
    return McpTestResult(ok=ok, detail=detail)


def _run_test(row: AgentMcpServer) -> tuple[bool, str]:
    import asyncio

    try:
        return asyncio.run(test_connection(row))
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
