"""LLM one-page weekly hotspot trend brief (uses LLM_MODEL_AGENT)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

import config

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))
from llm_utils import llm_extra_body, truncate_for_llm  # noqa: E402

_BRIEF_SYSTEM = """You are a pathology AI research analyst.
Write a concise weekly trend brief in Chinese (简体中文) for lab directors and PI readers.

Rules:
- Use ONLY facts from the provided JSON; do not invent PMIDs or statistics.
- Structure: (1) 本周概览 2-3 sentences (2) 升温方向 bullet list (3) 周环比变化 if any (4) 值得跟进的交叉机会 top 3-5 (5) 一句风险提示.
- Mention exact numbers (recent_cnt, velocity, opportunity_score) from the data.
- No emoji. Professional tone. ~400-600 Chinese characters total.
"""


def _client() -> OpenAI:
    return OpenAI(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE,
        timeout=config.LLM_REQUEST_TIMEOUT,
        max_retries=0,
    )


def _build_brief_context(payload: dict[str, Any]) -> str:
    wow = payload.get("week_over_week") or {}
    slim = {
        "week_id": payload.get("week_id"),
        "papers_ingested": payload.get("papers_ingested"),
        "window_days": payload.get("window_days"),
        "top_methods": payload.get("emerging_methods", [])[:8],
        "top_diseases": payload.get("heating_diseases", [])[:8],
        "top_combos": payload.get("hot_combos", [])[:8],
        "new_limitations": payload.get("new_limitations", [])[:5],
        "emerging_gap_opportunities": payload.get("emerging_gap_opportunities", [])[:8],
        "week_over_week": wow if wow.get("has_baseline") else {"has_baseline": False},
    }
    return truncate_for_llm(
        json.dumps(slim, ensure_ascii=False, indent=2),
        min(config.LLM_MAX_INPUT_CHARS, 120_000),
    )


def generate_hotspot_brief(payload: dict[str, Any]) -> str:
    """Single LLM call → markdown brief."""
    user = (
        "Generate the weekly hotspot brief from this snapshot:\n\n"
        f"{_build_brief_context(payload)}"
    )
    last_exc: BaseException | None = None
    for attempt in range(config.LLM_RETRY_ATTEMPTS):
        try:
            response = _client().chat.completions.create(
                model=config.LLM_MODEL_AGENT,
                messages=[
                    {"role": "system", "content": _BRIEF_SYSTEM},
                    {"role": "user", "content": user},
                ],
                max_tokens=min(config.LLM_MAX_TOKENS, 4096),
                temperature=0.3,
                extra_body=llm_extra_body(config.OPENAI_API_BASE),
            )
            return (response.choices[0].message.content or "").strip()
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            last_exc = exc
            if attempt < config.LLM_RETRY_ATTEMPTS - 1:
                time.sleep(config.LLM_RETRY_DELAY * (2**attempt))
        except Exception as exc:
            last_exc = exc
            break
    return f"_Brief generation failed: {last_exc}_"


def save_hotspot_brief(
    path: str | None = None,
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    persist: bool = True,
) -> tuple[str, str, dict[str, Any]]:
    """Compute hotspots, optional persist, LLM brief. Returns (brief_path, brief_text, payload)."""
    from analysis.weekly_hotspot import (
        compute_emerging_gap_opportunities,
        compute_weekly_hotspots,
        compare_with_previous_week,
        persist_hotspot_snapshot,
        week_id,
    )

    payload = compute_weekly_hotspots(window_days=window_days, prior_days=prior_days)
    payload["week_over_week"] = compare_with_previous_week(payload)
    payload["emerging_gap_opportunities"] = compute_emerging_gap_opportunities(
        window_days=window_days,
        prior_days=prior_days,
        payload=payload,
    )

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    wid = payload["week_id"]
    brief_path = path or os.path.join(config.OUTPUT_DIR, f"weekly_hotspot_brief_{wid}.md")

    brief_body = generate_hotspot_brief(payload)
    header = (
        f"# Weekly Hotspot Brief — {wid}\n\n"
        f"_Model: {config.LLM_MODEL_AGENT}_\n\n---\n\n"
    )
    full = header + brief_body
    with open(brief_path, "w", encoding="utf-8") as f:
        f.write(full)

    if persist:
        report_path = os.path.join(config.OUTPUT_DIR, f"weekly_hotspot_{wid}.md")
        persist_hotspot_snapshot(payload, report_path=report_path)

    return brief_path, full, payload
