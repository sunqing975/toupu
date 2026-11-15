"""Incremental OpenAI-compatible SSE and tool-call assembly; no simulated tokens."""

import json
from collections.abc import Iterator

import httpx

from app.agent.llm import _resolve_model


def stream_with_tools(
    db,
    messages,
    schemas,
    executor,
    *,
    model_id=None,
    max_rounds=6,
    check_cancelled=lambda: None,
    executor_with_id=False,
) -> Iterator[dict]:
    cfg = _resolve_model(db, model_id)
    headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    with httpx.Client(timeout=httpx.Timeout(120, connect=15)) as client:
        for _ in range(max_rounds):
            calls: dict[int, dict] = {}
            content = ""
            finish_reason = None
            body = {"model": cfg.model, "messages": messages, "temperature": 0.3, "stream": True}
            if schemas:
                body["tools"] = schemas
            with client.stream(
                "POST", cfg.base_url.rstrip("/") + "/chat/completions", json=body, headers=headers
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"模型返回 {response.status_code}，请检查模型配置或服务状态")
                for line in response.iter_lines():
                    check_cancelled()
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        if chunk.get("error"):
                            raise RuntimeError("模型流返回错误")
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        choice = choices[0]
                        finish_reason = choice.get("finish_reason") or finish_reason
                        delta = choice.get("delta", {})
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                        if isinstance(reasoning, str) and reasoning:
                            yield {"type": "reasoning", "text": reasoning}
                        if delta.get("content"):
                            content += delta["content"]
                            yield {"type": "content", "text": delta["content"]}
                        for part in delta.get("tool_calls") or []:
                            index = part["index"]
                            call = calls.setdefault(
                                index,
                                {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                },
                            )
                            call["id"] += part.get("id") or ""
                            for key in ("name", "arguments"):
                                call["function"][key] += part.get("function", {}).get(key) or ""
                    except (ValueError, KeyError, TypeError) as exc:
                        raise RuntimeError("模型流格式无效") from exc
            if finish_reason not in ("stop", "tool_calls"):
                raise RuntimeError("模型流意外中断，回答可能不完整")
            if not calls:
                yield {"type": "complete"}
                return
            ordered = [calls[index] for index in sorted(calls)]
            messages.append(
                {"role": "assistant", "content": content or None, "tool_calls": ordered}
            )
            for call in ordered:
                fn = call["function"]
                event_id = call["id"]
                allowed = {schema["function"]["name"] for schema in schemas}
                if not event_id or fn["name"] not in allowed:
                    raise RuntimeError("模型请求了未授权或无效的工具")
                yield {
                    "type": "tool_start",
                    "id": event_id,
                    "name": fn["name"],
                    "arguments": fn["arguments"],
                }
                check_cancelled()
                result = (
                    executor(fn["name"], fn["arguments"], event_id)
                    if executor_with_id
                    else executor(fn["name"], fn["arguments"])
                )
                yield {
                    "type": "tool_end",
                    "id": event_id,
                    "name": fn["name"],
                    "result": result[:12000],
                }
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        raise RuntimeError("模型在限定轮次内未结束工具调用循环。")
