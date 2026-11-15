# 外部 MCP 服务挂载管理（docs/agent-framework.md §外部 MCP 挂载）。
# CRUD 已在 0010 迁移的 agent_mcp_servers 表；审批/挂载只由管理员在网页端配置，
# Agent 专用会话只读地拉取这些服务的资源。绝不自动调用会修改外部系统的工具。
from __future__ import annotations

import json
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
    config = payload.config or {}
    if "args" in config and (
        not isinstance(config["args"], list) or any(not isinstance(v, str) for v in config["args"])
    ):
        raise HTTPException(422, "args 必须为字符串数组")
    for key in ("env", "headers"):
        if key in config and (
            not isinstance(config[key], dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in config[key].items())
        ):
            raise HTTPException(422, f"{key} 必须为字符串键值对象")
    if "cwd" in config and not isinstance(config["cwd"], str):
        raise HTTPException(422, "cwd 必须为字符串")
    if not payload.name.strip():
        raise HTTPException(422, "服务名称不能为空")
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


class JsonImport(BaseModel):
    json_text: str


@router.post("/import", response_model=list[McpServerOut], status_code=201)
def import_servers(payload: JsonImport, db: Session = Depends(get_db)):
    """Validate the complete pasted configuration before storing anything; never launch commands."""
    if len(payload.json_text.encode()) > 100_000:
        raise HTTPException(422, "JSON 配置不得超过100KB")
    try:
        data = json.loads(payload.json_text)
        entries = data["mcpServers"]
        if not isinstance(entries, dict) or not 1 <= len(entries) <= 50:
            raise ValueError()
        parsed = []
        for name, item in entries.items():
            if not isinstance(item, dict):
                raise ValueError()
            transport = item.get("transport", item.get("type")) or (
                "http" if item.get("url") else "stdio"
            )
            if transport == "streamable-http":
                transport = "http"
            server = McpServerIn(
                name=name,
                transport=transport,
                command=item.get("command"),
                url=item.get("url"),
                enabled=False,
                config={k: item[k] for k in ("args", "env", "cwd", "headers") if k in item},
            )
            _validate(server, is_create=True)
            parsed.append(server)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(
            422, "需要有效的 mcpServers JSON 对象，每个服务须包含 command 或 url"
        ) from None
    existing = set(db.scalars(select(AgentMcpServer.name)).all())
    if any(p.name in existing for p in parsed):
        raise HTTPException(409, "存在同名 MCP 服务，请先修改名称；本次未导入")
    rows = [AgentMcpServer(**p.model_dump()) for p in parsed]
    db.add_all(rows)
    db.flush()
    for row in rows:
        record_audit(db, "agent.mcp.import", "agent_mcp_server", str(row.id), {"name": row.name})
    db.commit()
    return [_out(row) for row in rows]


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
    if transport == "stdio" and not data.get("command", row.command):
        raise HTTPException(status_code=422, detail="stdio 传输需要 command")
    if transport == "http" and not data.get("url", row.url):
        raise HTTPException(status_code=422, detail="http 传输需要 url")
    _validate(
        McpServerIn(
            name=data.get("name", row.name),
            transport=transport,
            command=data.get("command", row.command),
            url=data.get("url", row.url),
            config=data.get("config", row.config),
        ),
        is_create=False,
    )
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
