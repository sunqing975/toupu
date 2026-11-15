import json
from types import SimpleNamespace

import httpx
import pytest

from app.agent import llm_stream


def chunk(delta, finish=None):
    return "data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}) + "\n\n"


def setup_stream(monkeypatch, rounds):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text=rounds.pop(0))

    factory = httpx.Client
    monkeypatch.setattr(
        llm_stream.httpx,
        "Client",
        lambda **kw: factory(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(
        llm_stream,
        "_resolve_model",
        lambda *_: SimpleNamespace(api_key="test", model="test", base_url="https://test/v1"),
    )
    return requests


def test_incremental_reasoning_and_split_tool_arguments(monkeypatch):
    first = chunk({"reasoning_content": "核对"})
    first += chunk(
        {
            "tool_calls": [
                {"index": 0, "id": "call1", "function": {"name": "lookup", "arguments": '{"x":'}}
            ]
        }
    )
    first += chunk({"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}, "tool_calls")
    requests = setup_stream(
        monkeypatch, [first, chunk({"content": "**结"}) + chunk({"content": "论**"}, "stop")]
    )
    calls = []

    def execute(name, args):
        calls.append((name, json.loads(args)))
        return "data"

    events = llm_stream.stream_with_tools(None, [], [{"function": {"name": "lookup"}}], execute)
    assert next(events) == {"type": "reasoning", "text": "核对"}
    assert not calls
    remaining = list(events)
    assert calls == [("lookup", {"x": 1})]
    assert [e["type"] for e in remaining] == [
        "tool_start",
        "tool_end",
        "content",
        "content",
        "complete",
    ]
    assert requests[1]["messages"][-1]["tool_call_id"] == "call1"
    assert all(r["stream"] for r in requests)


@pytest.mark.parametrize("finish", [None, "length", "content_filter"])
def test_truncated_stream_never_completes(monkeypatch, finish):
    setup_stream(monkeypatch, [chunk({"content": "partial"}, finish)])
    events = llm_stream.stream_with_tools(None, [], [], None)
    assert next(events)["text"] == "partial"
    with pytest.raises(RuntimeError):
        list(events)


def test_unknown_tool_never_executes(monkeypatch):
    setup_stream(
        monkeypatch,
        [
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "x",
                            "function": {"name": "forbidden", "arguments": "{}"},
                        }
                    ]
                },
                "tool_calls",
            )
        ],
    )
    with pytest.raises(RuntimeError, match="未授权"):
        list(llm_stream.stream_with_tools(None, [], [], lambda *_: pytest.fail("executed")))
