# 外部 MCP 服务挂载客户端（docs/agent-framework.md §外部知识库/MCP 挂载）。
# 本系统对外提供 MCP 服务（app/agent/mcp_server.py），也支持「挂载」外部 MCP：
# 管理员在 AgentMcpServer 表中登记 stdio / http 型服务，专用会话在拼快照时把
# 这些服务的只读资源与工具名注入提示词，让模型能结合外部知识（如 weknora 等）。
#
# 安全边界（agent.md §8 / docs/risk-agent-rules.md §7）：
# - 外部服务由管理员显式配置，连接前不信任其内容；每次调用失败都被吞掉并标注，
#   绝不因为某个外部服务异常而中断用户会话。
# - 只读：只读取资源与列出工具，不调用任何会修改外部系统的工具。
# - 超时：每个服务最多 20s，避免挂起。
from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from app.agent.models import AgentMcpServer

_MCP_TIMEOUT = 20.0
_MAX_RES_CHARS = 2000
_MAX_RES = 10


def fetch_external_knowledge(db, *, question: str | None = None) -> str:
    """连接所有已启用的外部 MCP 服务，聚合其只读资源文本。

    返回可直接拼接进提示词的多段文本；无任何可用服务或连接失败时返回空串。
    本函数同步调用（专用会话是同步 FastAPI 端点），内部用 asyncio.run 驱动异步客户端。
    """
    servers = (
        db.execute(select(AgentMcpServer).where(AgentMcpServer.enabled.is_(True))).scalars().all()
    )
    if not servers:
        return ""

    async def _collect() -> list[str]:
        sections: list[str] = []
        for srv in servers:
            try:
                text = await asyncio.wait_for(_gather_one(srv, question), timeout=_MCP_TIMEOUT)
                if text:
                    sections.append(f"[外部知识库 {srv.name}]\n{text}")
            except Exception as exc:  # noqa: BLE001
                reason = f"{type(exc).__name__}"
                sections.append(f"[外部知识库 {srv.name}：本次连接失败，已跳过：{reason}]")
        return sections

    sections = asyncio.run(_collect())
    return "\n\n".join(sections)


async def _gather_one(srv: AgentMcpServer, question: str | None) -> str:
    config = srv.config or {}
    if srv.transport == "stdio":
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=srv.command or "",
            args=list(config.get("args", []) or []),
            env={**os.environ, **(config.get("env", {}) or {})},
            cwd=config.get("cwd"),
        )
        async with stdio_client(params) as (r, w):
            return await _read_session(r, w, srv, question)
    else:  # http
        from mcp.client.streamable_http import streamablehttp_client

        headers = dict(config.get("headers", {}) or {})
        async with streamablehttp_client(srv.url or "", headers=headers) as (r, w, _):
            return await _read_session(r, w, srv, question)


async def _read_session(r, w, srv: AgentMcpServer, question: str | None) -> str:
    from mcp import ClientSession

    async with ClientSession(r, w) as session:
        await session.initialize()
        parts: list[str] = []
        try:
            res = await session.list_resources()
            items = res.resources[:_MAX_RES]
            for item in items:
                try:
                    rr = await session.read_resource(item.uri)
                    for content in getattr(rr, "contents", []) or []:
                        body = getattr(content, "text", "") or ""
                        if body:
                            parts.append(f"- {item.name or item.uri}: {body[:_MAX_RES_CHARS]}")
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        try:
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            if names:
                parts.append("可用工具：" + ", ".join(names))
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(parts)


async def test_connection(srv: AgentMcpServer) -> tuple[bool, str]:
    """探测单个外部服务连通性，用于前端「测试连接」。"""
    try:
        text = await asyncio.wait_for(_gather_one(srv, None), timeout=_MCP_TIMEOUT)
        return True, f"连接成功，已读取 {len(text)} 字符"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
