"""Tests for execute_kg_sql hard call budget in run_tool_agent."""
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


def _assistant_tool_calls(calls: list[tuple[str, str]], content: str | None = None):
    tool_calls = []
    dump_calls = []
    for index, (name, arguments) in enumerate(calls, start=1):
        call_id = f"call_{index}"
        tool_calls.append(
            SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(name=name, arguments=arguments),
            )
        )
        dump_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        )
    return SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        model_dump=lambda exclude_none=True: {
            "role": "assistant",
            "content": content,
            "tool_calls": dump_calls,
        },
    )


def test_sql_budget_blocks_third_execute_kg_sql(monkeypatch):
    invoke_count = {"n": 0}
    create_kwargs = []

    def fake_sql(**_kwargs):
        invoke_count["n"] += 1
        return {"row_count": 0, "data": [], "description": "ok"}

    def fake_create(**kwargs):
        create_kwargs.append(kwargs)
        n = len(create_kwargs)
        if n == 1:
            return _completion(
                _assistant_tool_calls(
                    [
                        ("execute_kg_sql", json.dumps({"sql": "SELECT 1 LIMIT 1"})),
                        ("execute_kg_sql", json.dumps({"sql": "SELECT 2 LIMIT 1"})),
                    ]
                )
            )
        if n == 2:
            # Model tries a third SQL after budget; schema should no longer expose it,
            # but even if called, runtime must block.
            return _completion(
                _assistant_tool_calls(
                    [("execute_kg_sql", json.dumps({"sql": "SELECT 3 LIMIT 1"}))]
                )
            )
        msg = SimpleNamespace(
            content='```json\n{"overall_confidence": 6.0}\n```',
            tool_calls=None,
            model_dump=lambda exclude_none=True: {
                "role": "assistant",
                "content": '```json\n{"overall_confidence": 6.0}\n```',
            },
        )
        return _completion(msg, finish_reason="stop")

    monkeypatch.setattr(agent_utils._client.chat.completions, "create", fake_create)

    messages = [{"role": "user", "content": "review"}]
    events = list(
        run_tool_agent(
            messages=messages,
            tools={"execute_kg_sql": fake_sql},
            tool_schemas=[
                {
                    "type": "function",
                    "function": {
                        "name": "execute_kg_sql",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            role="skeptic",
            max_iters=5,
            max_sql_calls=2,
        )
    )

    assert invoke_count["n"] == 2
    blocked = [
        e
        for e in events
        if e.get("type") == "tool_error" and "SQL call budget" in str(e.get("error", ""))
    ]
    assert blocked
    # After budget, next LLM turn should not advertise execute_kg_sql
    assert len(create_kwargs) >= 2
    second_tools = create_kwargs[1].get("tools") or []
    assert all(
        (t.get("function") or {}).get("name") != "execute_kg_sql" for t in second_tools
    )


def test_empty_sql_result_gets_stop_scanning_hint(monkeypatch):
    def fake_sql(**_kwargs):
        return {"row_count": 0, "data": []}

    calls = {"n": 0}

    def fake_create_seq(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _completion(
                _assistant_tool_calls(
                    [("execute_kg_sql", json.dumps({"sql": "SELECT 1 LIMIT 1"}))]
                )
            )
        msg = SimpleNamespace(
            content="done",
            tool_calls=None,
            model_dump=lambda exclude_none=True: {"role": "assistant", "content": "done"},
        )
        return _completion(msg, finish_reason="stop")

    monkeypatch.setattr(agent_utils._client.chat.completions, "create", fake_create_seq)

    messages = [{"role": "user", "content": "review"}]
    events = list(
        run_tool_agent(
            messages=messages,
            tools={"execute_kg_sql": fake_sql},
            tool_schemas=[
                {
                    "type": "function",
                    "function": {"name": "execute_kg_sql", "parameters": {"type": "object"}},
                }
            ],
            role="moderator",
            max_iters=3,
            max_sql_calls=2,
        )
    )
    result_events = [e for e in events if e.get("type") == "tool_result"]
    assert result_events
    hint = str(result_events[0]["result"].get("hint", "")).lower()
    assert "curated" in hint or "keyword" in hint


def test_failed_sql_does_not_consume_successful_budget(monkeypatch):
    invoke_count = {"n": 0}
    create_kwargs = []

    def fake_sql(**_kwargs):
        invoke_count["n"] += 1
        if invoke_count["n"] == 1:
            return {"error": "ambiguous column name: confidence"}
        return {"row_count": 1, "data": [{"ok": 1}]}

    def fake_create(**kwargs):
        create_kwargs.append(kwargs)
        n = len(create_kwargs)
        if n <= 3:
            return _completion(
                _assistant_tool_calls(
                    [("execute_kg_sql", json.dumps({"sql": f"SELECT {n} LIMIT 1"}))]
                )
            )
        msg = SimpleNamespace(
            content="done",
            tool_calls=None,
            model_dump=lambda exclude_none=True: {"role": "assistant", "content": "done"},
        )
        return _completion(msg, finish_reason="stop")

    monkeypatch.setattr(agent_utils._client.chat.completions, "create", fake_create)

    messages = [{"role": "user", "content": "review"}]
    events = list(
        run_tool_agent(
            messages=messages,
            tools={"execute_kg_sql": fake_sql},
            tool_schemas=[
                {
                    "type": "function",
                    "function": {"name": "execute_kg_sql", "parameters": {"type": "object"}},
                }
            ],
            role="skeptic",
            max_iters=5,
            max_sql_calls=2,
        )
    )

    # 1 fail + 2 success = 3 invokes; third success still allowed because fail didn't count
    assert invoke_count["n"] == 3
    errors = [e for e in events if e.get("type") == "tool_error"]
    assert any("ambiguous column" in str(e.get("error", "")) for e in errors)
    assert any(
        "did not consume" in str(e.get("error", "")).lower()
        or "DID NOT consume" in str(
            next(
                (
                    m.get("content", "")
                    for m in messages
                    if m.get("role") == "tool"
                ),
                "",
            )
        )
        for e in errors
    ) or any(
        "did not consume" in str(m.get("content", "")).lower()
        for m in messages
        if m.get("role") == "tool"
    )


def test_post_budget_sql_only_turn_disables_tools_next(monkeypatch):
    create_kwargs = []

    def fake_sql(**_kwargs):
        return {"row_count": 1, "data": [{"x": 1}]}

    def fake_create(**kwargs):
        create_kwargs.append(kwargs)
        n = len(create_kwargs)
        if n == 1:
            return _completion(
                _assistant_tool_calls(
                    [
                        ("execute_kg_sql", json.dumps({"sql": "SELECT 1 LIMIT 1"})),
                        ("execute_kg_sql", json.dumps({"sql": "SELECT 2 LIMIT 1"})),
                    ]
                )
            )
        if n == 2:
            return _completion(
                _assistant_tool_calls(
                    [("execute_kg_sql", json.dumps({"sql": "SELECT 3 LIMIT 1"}))]
                )
            )
        # Third LLM turn should have tools disabled (None)
        msg = SimpleNamespace(
            content="final",
            tool_calls=None,
            model_dump=lambda exclude_none=True: {"role": "assistant", "content": "final"},
        )
        return _completion(msg, finish_reason="stop")

    monkeypatch.setattr(agent_utils._client.chat.completions, "create", fake_create)

    messages = [{"role": "user", "content": "review"}]
    list(
        run_tool_agent(
            messages=messages,
            tools={"execute_kg_sql": fake_sql},
            tool_schemas=[
                {
                    "type": "function",
                    "function": {"name": "execute_kg_sql", "parameters": {"type": "object"}},
                }
            ],
            role="moderator",
            max_iters=5,
            max_sql_calls=2,
        )
    )

    assert len(create_kwargs) >= 3
    assert create_kwargs[2].get("tools") is None
    assert create_kwargs[2].get("tool_choice") == "none"
