"""Tests for phantom format-tool recovery in run_tool_agent."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import analysis.agent_utils as agent_utils  # noqa: E402
from analysis.agent_utils import (  # noqa: E402
    last_assistant_content,
    parse_json_block,
    run_tool_agent,
)


def _completion(message: SimpleNamespace, finish_reason: str = "tool_calls"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)]
    )


def _assistant_tool_call(name: str, arguments: str, content: str | None = None):
    tc = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    msg = SimpleNamespace(
        content=content,
        tool_calls=[tc],
        model_dump=lambda exclude_none=True: {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        },
    )
    return msg


def test_phantom_json_tool_with_payload_recovers_as_content(monkeypatch):
    payload = {"accept": False, "overall_confidence": 6.2, "revision_priority": "tighten"}
    calls = {"n": 0}

    def fake_create(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _completion(
                _assistant_tool_call("json", json.dumps(payload)),
                finish_reason="tool_calls",
            )
        raise AssertionError("should stop after phantom recovery")

    monkeypatch.setattr(
        agent_utils._client.chat.completions,
        "create",
        fake_create,
    )

    messages = [{"role": "user", "content": "synthesize"}]
    events = list(
        run_tool_agent(
            messages=messages,
            tools={"corpus_focus_coverage": lambda: {}},
            tool_schemas=[],
            role="moderator",
            max_iters=3,
        )
    )

    assert any(
        e.get("type") == "tool_error" and "json" in str(e.get("error", "")).lower()
        for e in events
    )
    text = last_assistant_content(messages)
    recovered = parse_json_block(text, fallback={})
    assert recovered.get("accept") is False
    assert recovered.get("overall_confidence") == 6.2
    assert calls["n"] == 1


def test_phantom_json_tool_empty_args_gets_corrective_hint(monkeypatch):
    calls = {"n": 0}
    second_kwargs: dict = {}
    schema = {
        "type": "function",
        "function": {
            "name": "corpus_focus_coverage",
            "description": "coverage",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    def fake_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _completion(
                _assistant_tool_call("json", "{}"),
                finish_reason="tool_calls",
            )
        second_kwargs.update(kwargs)
        # Second turn: model complies with a normal content message
        msg = SimpleNamespace(
            content='```json\n{"accept": false, "overall_confidence": 5.0}\n```',
            tool_calls=None,
            model_dump=lambda exclude_none=True: {
                "role": "assistant",
                "content": '```json\n{"accept": false, "overall_confidence": 5.0}\n```',
            },
        )
        return _completion(msg, finish_reason="stop")

    monkeypatch.setattr(
        agent_utils._client.chat.completions,
        "create",
        fake_create,
    )

    messages = [{"role": "user", "content": "synthesize"}]
    events = list(
        run_tool_agent(
            messages=messages,
            tools={"corpus_focus_coverage": lambda: {}},
            tool_schemas=[schema],
            role="moderator",
            max_iters=3,
        )
    )

    err = next(e for e in events if e.get("type") == "tool_error")
    assert "not a tool" in err["error"].lower() or "message content" in err["error"].lower()
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert tool_msgs
    assert "message content" in tool_msgs[0]["content"].lower()
    assert calls["n"] == 2
    # Empty phantom → next turn forces text (tools disabled).
    assert second_kwargs.get("tools") is None
    assert second_kwargs.get("tool_choice") == "none"
    assert any(
        m.get("role") == "user" and "tools are disabled" in m.get("content", "").lower()
        for m in messages
    )


def test_phantom_json_empty_in_text_only_mode_stops(monkeypatch):
    """If tools are already off and model still calls json:{}, do not loop forever."""
    calls = {"n": 0}

    def fake_create(**_kwargs):
        calls["n"] += 1
        return _completion(
            _assistant_tool_call("json", "{}"),
            finish_reason="tool_calls",
        )

    monkeypatch.setattr(
        agent_utils._client.chat.completions,
        "create",
        fake_create,
    )

    messages = [{"role": "user", "content": "synthesize"}]
    list(
        run_tool_agent(
            messages=messages,
            tools={},
            tool_schemas=[],
            role="skeptic",
            max_iters=5,
        )
    )
    assert calls["n"] == 1
