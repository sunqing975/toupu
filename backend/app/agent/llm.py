# OpenAI 兼容大模型客户端（docs/agent-framework.md §分析会话）。
# 仅做 HTTP 调用，不引入任何 SDK 依赖；密钥来自数据库中已配置的 AgentModel，
# 调用前才解密读取，绝不回显。所有调用都在 Agent 专用会话里进行，模型只拿到
# 只读数据快照 + 自然语言问题，无法直接写账本。
from __future__ import annotations

import json
from urllib.request import Request, urlopen

import httpx

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


def chat(
    db,
    messages: list[dict],
    *,
    model_id: str | None = None,
    temperature: float = 0.3,
) -> str:
    """对配置的 OpenAI 兼容端点发起一次 chat/completions，返回助手文本。

    失败（无配置/网络/鉴权）抛出 RuntimeError，由调用方转成业务错误。
    """
    try:
        cfg = _resolve_model(db, model_id)
    except _NoModelConfigured:
        raise RuntimeError("尚未配置可用的模型（Settings → Agent 模型配置）") from None

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=120.0)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"调用模型失败：{exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"模型返回 {resp.status_code}：{resp.text[:300]}")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise RuntimeError(f"解析模型响应失败：{exc}") from exc


def chat_with_tools(
    db,
    messages: list[dict],
    tool_schemas: list[dict],
    tool_executor,
    *,
    model_id: str | None = None,
    temperature: float = 0.3,
    max_rounds: int = 6,
) -> str:
    """带工具调用的对话循环（OpenAI function-calling 风格）。

    模型可在回复中请求调用工具；本函数执行后将结果回填，直到模型产出不包含
    tool_calls 的最终文本。所有工具调用（含写操作）只在 Agent 专用会话内进行，
    由 tool_executor 控制边界（如 create_draft_proposal 只建 PENDING）。
    """
    try:
        cfg = _resolve_model(db, model_id)
    except _NoModelConfigured:
        raise RuntimeError("尚未配置可用的模型（Settings → Agent 模型配置）") from None

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    for _ in range(max_rounds):
        body = {
            "model": cfg.model,
            "messages": messages,
            "tools": tool_schemas,
            "temperature": temperature,
            "stream": False,
        }
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=120.0)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"调用模型失败：{exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(f"模型返回 {resp.status_code}：{resp.text[:300]}")
        try:
            payload = resp.json()
            choice = payload["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as exc:
            raise RuntimeError(f"解析模型响应失败：{exc}") from exc

        tool_calls = choice.get("tool_calls")
        if not tool_calls:
            return choice.get("content", "")

        # 把助手这条（带 tool_calls）追加进对话，再逐个执行工具并追加 tool 结果。
        messages.append(choice)
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", "{}")
            result = tool_executor(name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": name,
                    "content": result,
                }
            )

    raise RuntimeError("模型在限定轮次内未结束工具调用循环。")


# 兼容旧式 urllib 的场景（保持与项目其余部分一致），但优先使用 httpx。
def chat_urllib(db, messages: list[dict], *, model_id: str | None = None) -> str:
    try:
        cfg = _resolve_model(db, model_id)
    except _NoModelConfigured:
        raise RuntimeError("尚未配置可用的模型（Settings → Agent 模型配置）") from None

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {"model": cfg.model, "messages": messages, "temperature": 0.3, "stream": False}
    ).encode()
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"调用模型失败：{exc}") from exc
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"解析模型响应失败：{exc}") from exc
