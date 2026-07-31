"""Tests for disallow_duplicate_tools in run_tool_agent."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import analysis.agent_utils as agent_utils  # noqa: E402
from analysis.agent_utils import run_tool_agent  # noqa: E402


def _completion(message: SimpleNamespace, finish_reason: str = "tool_calls"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)]
    )


def _assistant_tool_call(name: str, arguments: str = "{}", call_id: str = "call_1"):
    tc = SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    return SimpleNamespace(
        content=None,
        tool_calls=[tc],
        model_dump=lambda exclude_none=True: {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        },
    )


def test_disallow_duplicate_tools_blocks_second_call(monkeypatch):
    calls = {"n": 0}
    invoke_count = {"n": 0}
    schema = {
        "type": "function",
        "function": {
            "name": "corpus_focus_coverage",
            "description": "coverage",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    def fake_create(**_kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _completion(
                _assistant_tool_call("corpus_focus_coverage", "{}", f"call_{calls['n']}"),
                finish_reason="tool_calls",
            )
        msg = SimpleNamespace(
            content="## Candidate research gap summary\ndone",
            tool_calls=None,
            model_dump=lambda exclude_none=True: {
                "role": "assistant",
                "content": "## Candidate research gap summary\ndone",
            },
        )
        return _completion(msg, finish_reason="stop")

    def coverage(**_kwargs):
        invoke_count["n"] += 1
        return {"focus_subset": {"papers": 1}, "global": {"papers": 10}}

    monkeypatch.setattr(
        agent_utils._client.chat.completions,
        "create",
        fake_create,
    )

    messages = [{"role": "user", "content": "scout"}]
    events = list(
        run_tool_agent(
            messages=messages,
            tools={"corpus_focus_coverage": coverage},
            tool_schemas=[schema],
            role="optimist",
            max_iters=5,
            disallow_duplicate_tools=True,
        )
    )

    assert invoke_count["n"] == 1
    assert any(
        e.get("type") == "tool_error" and "same tool" in str(e.get("error", "")).lower()
        for e in events
    )
    err_payloads = [
        json.loads(m["content"])
        for m in messages
        if m.get("role") == "tool"
    ]
    assert any(p.get("duplicate_tool_blocked") for p in err_payloads)
