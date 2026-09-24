"""Compact, truthful display of per-operation debate cost telemetry."""
from __future__ import annotations

from typing import Any


def summarize_cost_events(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    completed = [r for r in rows if r.get("status") in {"success", "failed"}]
    llm = [r for r in rows if r.get("event_kind") == "llm"]
    completed_llm = [r for r in completed if r.get("event_kind") == "llm"]
    tools = [r for r in completed if r.get("event_kind") == "tool"]
    requests = {r.get("request_id") or r.get("operation_id") for r in llm}
    missing_usage = sum(
        1 for r in llm
        if r.get("prompt_tokens") is None or r.get("completion_tokens") is None
    )
    known_cache = [r for r in tools if r.get("cache_hit") in (0, 1)]
    return {
        "llm_requests": len(requests),
        "llm_attempts": len(llm),
        "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in llm),
        "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in llm),
        "missing_usage": missing_usage,
        "known_usage": sum(1 for r in llm if r.get("prompt_tokens") is not None
                           and r.get("completion_tokens") is not None),
        "tool_calls": len(tools),
        "tool_seconds": sum(float(r.get("duration_ms") or 0) for r in tools) / 1000,
        "llm_seconds": sum(float(r.get("duration_ms") or 0) for r in completed_llm) / 1000,
        "cache_hits": sum(1 for r in known_cache if r.get("cache_hit") == 1),
        "cache_known": len(known_cache),
        "retries": sum(1 for r in llm if int(r.get("attempt_no") or 1) > 1),
        "failures": sum(1 for r in completed if r.get("status") == "failed"),
        "interrupted": sum(1 for r in rows if r.get("status") == "interrupted"),
        "running": sum(1 for r in rows if r.get("status") == "running"),
    }


def format_cost_summary(summary: dict[str, Any] | None) -> str:
    if summary is None:
        return "历史运行未采集成本指标"
    if summary["llm_requests"] == 0:
        tokens = "tokens 无记录"
    elif summary["known_usage"] == 0:
        tokens = "tokens 未记录"
    elif summary["missing_usage"]:
        tokens = (
            f"tokens {summary['prompt_tokens']:,} 入 / {summary['completion_tokens']:,} 出"
            "（部分缺失）"
        )
    else:
        tokens = f"tokens {summary['prompt_tokens']:,} 入 / {summary['completion_tokens']:,} 出"
    cache = (
        f"缓存 {summary['cache_hits']}/{summary['cache_known']}"
        if summary["cache_known"] else "缓存状态未知"
    )
    unclosed = summary["running"] + summary["interrupted"]
    return (
        f"LLM {summary['llm_requests']} 次 · {tokens} · "
        f"工具 {summary['tool_calls']} 次 / {summary['tool_seconds']:.1f} 秒 · "
        f"{cache} · 重试 {summary['retries']}"
        + (f" · 未闭合记录 {unclosed}" if unclosed else "")
    )


def diagnostic_rows(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    completed = [r for r in rows if r.get("status") in {"success", "failed"}]
    return sorted(
        completed, key=lambda r: float(r.get("duration_ms") or 0), reverse=True
    )[:limit]


def role_cost_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roles = sorted({str(r.get("role") or "") for r in rows if r.get("role")})
    out = []
    for role in roles:
        summary = summarize_cost_events([r for r in rows if r.get("role") == role])
        if summary is not None:
            out.append({"role": role, **summary})
    return out
