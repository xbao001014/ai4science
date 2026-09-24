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
from analysis.agent_utils import memoize_readonly_tools, run_tool_agent  # noqa: E402


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
        e.get("type") == "tool_error" and "same arguments" in str(e.get("error", "")).lower()
        for e in events
    )
    err_payloads = [
        json.loads(m["content"])
        for m in messages
        if m.get("role") == "tool"
    ]
    assert any(p.get("duplicate_tool_blocked") for p in err_payloads)


def test_distinct_queries_to_same_tool_are_allowed(monkeypatch):
    arguments = [
        '{"query":"MSI-H colorectal cancer"}',
        '{"query":"dMMR colorectal cancer"}',
    ]
    calls = {"n": 0}
    seen_queries = []

    def fake_create(**_kwargs):
        calls["n"] += 1
        if calls["n"] <= len(arguments):
            return _completion(_assistant_tool_call(
                "literature_evidence_search", arguments[calls["n"] - 1],
                f"call_{calls['n']}",
            ))
        msg = SimpleNamespace(
            content="## Candidate research gap summary\ndone",
            tool_calls=None,
            model_dump=lambda exclude_none=True: {
                "role": "assistant", "content": "## Candidate research gap summary\ndone",
            },
        )
        return _completion(msg, finish_reason="stop")

    def search(**kwargs):
        seen_queries.append(kwargs["query"])
        return {"records": []}

    monkeypatch.setattr(agent_utils._client.chat.completions, "create", fake_create)
    events = list(run_tool_agent(
        messages=[{"role": "user", "content": "scout"}],
        tools={"literature_evidence_search": search},
        tool_schemas=[{
            "type": "function",
            "function": {
                "name": "literature_evidence_search",
                "description": "search",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }],
        role="optimist", max_iters=4, disallow_duplicate_tools=True,
    ))

    assert seen_queries == ["MSI-H colorectal cancer", "dMMR colorectal cancer"]
    assert not any(event["type"] == "tool_error" for event in events)


def test_identical_readonly_result_reused_across_roles():
    calls = {"n": 0}
    shared_cache = {}

    def coverage(*, focus: str):
        calls["n"] += 1
        return {"focus": focus, "papers": calls["n"]}

    scout = memoize_readonly_tools({"corpus_focus_coverage": coverage}, shared_cache)
    reviewer = memoize_readonly_tools({"corpus_focus_coverage": coverage}, shared_cache)
    first = scout["corpus_focus_coverage"](focus="肠癌")
    second = reviewer["corpus_focus_coverage"](focus="肠癌")
    different = reviewer["corpus_focus_coverage"](focus="胃癌")

    assert calls["n"] == 2
    assert first["papers"] == second["papers"] == 1
    assert second["_telemetry"] == {"cache_hit": True, "cache_source": "debate_session"}
    assert different["papers"] == 2
