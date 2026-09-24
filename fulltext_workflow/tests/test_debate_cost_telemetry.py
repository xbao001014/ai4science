from __future__ import annotations

import sys
import sqlite3
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import analysis.agent_utils as agent_utils
from analysis.debate_memory import create_debate_session, persist_cost_event, resume_debate_session
from db.schema import fetch_debate_cost_events, init_db, interrupt_running_debate_cost_events
from utils.debate_cost_ui import format_cost_summary, role_cost_rows, summarize_cost_events


def test_existing_cost_table_adds_new_llm_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "old_cost.sqlite"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE debate_cost_events (
            operation_id TEXT PRIMARY KEY, session_id TEXT, round_no INTEGER,
            role TEXT, event_kind TEXT, status TEXT, request_id TEXT,
            attempt_no INTEGER, model TEXT, tool_name TEXT, call_id TEXT,
            started_at_utc TEXT
        )""")
    init_db()
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(debate_cost_events)")}
    assert {"iteration", "usage_source", "retry_source"} <= columns


def test_llm_retry_records_provider_usage_and_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "retries.sqlite"))
    init_db()
    state = create_debate_session(focus="肠癌", max_rounds=1, top_n=1)
    class RateLimited(Exception):
        status_code = 429

    calls = {"n": 0}

    def create(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("limited")
        return SimpleNamespace(
            id="resp-1", usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150),
            choices=[SimpleNamespace(finish_reason="stop")],
        )

    monkeypatch.setattr(agent_utils._client.chat.completions, "create", create)
    monkeypatch.setattr(agent_utils.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(config, "LLM_RETRY_ATTEMPTS", 2)
    events = []
    gen = agent_utils._chat_with_metrics(
        role="skeptic", iteration=1, messages=[], request_kwargs={"model": "test"}
    )
    try:
        while True:
            events.append(next(gen))
    except StopIteration as stop:
        response, error = stop.value
    assert error is None and response.id == "resp-1"
    finishes = [e for e in events if e["type"] == "cost_finish"]
    assert [e["status"] for e in finishes] == ["failed", "success"]
    assert finishes[0]["retry_reason_code"] == "rate_limit"
    assert finishes[1]["prompt_tokens"] == 120
    assert finishes[1]["completion_tokens"] == 30
    assert len([e for e in events if e["type"] == "llm_retry"]) == 1
    for event in events:
        if event["type"] in {"cost_start", "cost_finish"}:
            persist_cost_event(state, round_no=1, event=event)
    stored = fetch_debate_cost_events(state.session_id)
    summary = summarize_cost_events(stored)
    assert summary and summary["llm_requests"] == 1 and summary["retries"] == 1
    assert summary["prompt_tokens"] == 120 and summary["completion_tokens"] == 30
    assert any(r["retry_reason_code"] == "rate_limit" and r["retry_source"] == "agent" for r in stored)
    assert any(r["usage_source"] == "provider" for r in stored)


def test_tool_metrics_persist_and_unknown_usage_stays_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "cost.sqlite"))
    init_db()
    state = create_debate_session(focus="肠癌", max_rounds=1, top_n=1)
    calls = {"n": 0}

    def create(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            call = SimpleNamespace(id="c1", function=SimpleNamespace(name="catalog", arguments="{}"))
            message = SimpleNamespace(
                content=None, tool_calls=[call],
                model_dump=lambda exclude_none=True: {"role": "assistant", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "catalog", "arguments": "{}"}}
                ]},
            )
        else:
            message = SimpleNamespace(
                content="done", tool_calls=None,
                model_dump=lambda exclude_none=True: {"role": "assistant", "content": "done"},
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)

    monkeypatch.setattr(agent_utils._client.chat.completions, "create", create)
    events = list(agent_utils.run_tool_agent(
        messages=[{"role": "user", "content": "test"}],
        tools={"catalog": lambda: {"data": [{"id": 1}], "_telemetry": {
            "cache_hit": True, "cache_source": "pathology_catalog"}}},
        tool_schemas=[{"type": "function", "function": {"name": "catalog", "parameters": {"type": "object"}}}],
        role="optimist", max_iters=3,
    ))
    for event in events:
        if event["type"] in {"cost_start", "cost_finish"}:
            persist_cost_event(state, round_no=1, event=event)
    rows = fetch_debate_cost_events(state.session_id)
    assert len(rows) == 3
    tool = next(r for r in rows if r["event_kind"] == "tool")
    assert tool["cache_hit"] == 1 and tool["cache_source"] == "pathology_catalog"
    assert tool["raw_result_chars"] > 0 and tool["sent_result_chars"] > 0
    assert tool["duration_ms"] is not None
    assert "_telemetry" not in next(e for e in events if e["type"] == "tool_result")["result"]
    summary = summarize_cost_events(rows)
    assert summary and summary["llm_requests"] == 2
    assert summary["missing_usage"] == 2 and summary["cache_hits"] == 1
    assert "tokens 未记录" in format_cost_summary(summary)
    interrupt_running_debate_cost_events(state.session_id)
    assert all(r["status"] == "success" for r in fetch_debate_cost_events(state.session_id))


def test_empty_and_unknown_cache_are_not_zero_usage_claims():
    assert format_cost_summary(None) == "历史运行未采集成本指标"
    summary = summarize_cost_events([{
        "event_kind": "tool", "status": "success", "operation_id": "t1",
        "duration_ms": 50, "cache_hit": None,
    }])
    assert summary and summary["cache_known"] == 0
    assert "缓存状态未知" in format_cost_summary(summary)
    assert role_cost_rows([{"role": "skeptic", "event_kind": "tool",
                            "status": "success", "duration_ms": 50}])[0]["tool_seconds"] == 0.05


def test_unclosed_llm_requests_are_counted_without_inventing_tokens():
    summary = summarize_cost_events([{
        "event_kind": "llm", "status": "running", "operation_id": "old-1",
        "request_id": "req-1", "prompt_tokens": None, "completion_tokens": None,
    }])
    assert summary and summary["llm_requests"] == 1
    assert summary["known_usage"] == 0
    assert "未闭合记录 1" in format_cost_summary(summary)


def test_resume_marks_unfinished_request_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "interrupted.sqlite"))
    init_db()
    state = create_debate_session(focus="肠癌", max_rounds=2, top_n=2)
    persist_cost_event(state, round_no=1, event={
        "type": "cost_start", "event_kind": "llm", "operation_id": "pending-1",
        "role": "optimist", "request_id": "req-1", "attempt_no": 1,
        "started_at_utc": "2026-09-23T00:00:00.000+00:00",
    })
    resume_debate_session(state.session_id)
    row = fetch_debate_cost_events(state.session_id)[0]
    assert row["status"] == "interrupted" and row["duration_ms"] is None
