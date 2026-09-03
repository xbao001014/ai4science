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
- Structure: (1) 本周概览 2-3 sentences (2) 升温方向 bullet list (3) 周环比变化 if any (4) 值得跟进的可迁移候选 top 3-5 (5) 一句风险提示.
- emerging_gap_opportunities = task-bridged transfer candidates (bridge_task, bridge_mode); do NOT treat unbridged coverage holes as opportunities.
- Mention exact numbers (recent_cnt, velocity, opportunity_score, bridge_task) from the data.
- emerging_methods = 新苗头 only (non-established). Do NOT call established baselines (LLM, SVM, CNN, deep learning, etc.) 新兴热点.
- emerging_gap_opportunities exclude established methods from the heat pool; do not recommend LLM/SVM transfers as 可迁移候选.
- Prefer nascent/emerging methods in 升温方向.
- No emoji. Professional tone. ~400-600 Chinese characters total.
"""

_BRIEF_SYSTEM_NO_OPPORTUNITIES = """You are a pathology AI research analyst.
Write a concise weekly trend brief in Chinese (简体中文) for lab directors and PI readers.

Rules:
- Use ONLY facts from the provided JSON; do not invent PMIDs or statistics.
- Structure: (1) 本周概览 2-3 sentences (2) 升温方向 bullet list (3) 周环比变化 if any (4) 一句风险提示.
- Do NOT write a 可迁移候选 / transfer-candidate section. emerging_gap_opportunities is empty; the caller appends that section deterministically.
- emerging_methods = 新苗头 only (non-established). Do NOT call established baselines (LLM, SVM, CNN, deep learning, etc.) 新兴热点.
- Prefer nascent/emerging methods in 升温方向.
- No emoji. Professional tone. ~300-500 Chinese characters total.
"""

_EMPTY_TRANSFER_SECTION = (
    "**值得跟进的可迁移候选**\n\n"
    "本期无满足证据门槛的可迁移候选（Task 桥接不足，"
    "未从普通 method×disease 组合推断）。"
)


def _client() -> OpenAI:
    return OpenAI(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE,
        timeout=config.LLM_REQUEST_TIMEOUT,
        max_retries=0,
    )


def format_transfer_candidates_section(
    opportunities: list[dict[str, Any]],
) -> str:
    """Deterministic transfer-candidate section (never infer from hot_combos)."""
    if not opportunities:
        return _EMPTY_TRANSFER_SECTION
    lines = ["**值得跟进的可迁移候选**", ""]
    for idx, opp in enumerate(opportunities[:5], start=1):
        method = opp.get("method", "")
        disease = opp.get("disease", "")
        bridge_task = opp.get("bridge_task", "")
        score = opp.get("opportunity_score", "")
        bridge_mode = opp.get("bridge_mode", "")
        lines.append(
            f"{idx}. **{method} + {disease}**："
            f"bridge_task={bridge_task}，"
            f"bridge_mode={bridge_mode}，"
            f"opportunity_score={score}"
        )
    return "\n".join(lines)


def _build_brief_context(payload: dict[str, Any]) -> str:
    wow = payload.get("week_over_week") or {}
    opportunities = payload.get("emerging_gap_opportunities") or []
    slim = {
        "week_id": payload.get("week_id"),
        "time_axis": payload.get("time_axis", "pub_date"),
        "papers_in_window": payload.get(
            "papers_in_window", payload.get("papers_ingested")
        ),
        "papers_excluded_low_precision": payload.get(
            "papers_excluded_low_precision", 0
        ),
        "papers_excluded_future_pub_date": payload.get(
            "papers_excluded_future_pub_date", 0
        ),
        "window_days": payload.get("window_days"),
        "eligible_precision": payload.get("eligible_precision"),
        "top_methods": payload.get("emerging_methods", [])[:8],
        "top_diseases": payload.get("heating_diseases", [])[:8],
        "new_limitations": payload.get("new_limitations", [])[:5],
        "emerging_gap_opportunities": opportunities[:8],
        "transfer_candidates_available": bool(opportunities),
        "week_over_week": wow if wow.get("has_baseline") else {"has_baseline": False},
    }
    return truncate_for_llm(
        json.dumps(slim, ensure_ascii=False, indent=2),
        min(config.LLM_MAX_INPUT_CHARS, 120_000),
    )


def generate_hotspot_brief(payload: dict[str, Any]) -> str:
    """Single LLM call → markdown brief."""
    opportunities = payload.get("emerging_gap_opportunities") or []
    system = _BRIEF_SYSTEM if opportunities else _BRIEF_SYSTEM_NO_OPPORTUNITIES
    user = (
        "Generate the weekly hotspot brief from this snapshot:\n\n"
        f"{_build_brief_context(payload)}"
    )
    last_exc: BaseException | None = None
    body = ""
    for attempt in range(config.LLM_RETRY_ATTEMPTS):
        try:
            response = _client().chat.completions.create(
                model=config.LLM_MODEL_AGENT,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=min(config.LLM_MAX_TOKENS, 4096),
                temperature=0.3,
                extra_body=llm_extra_body(config.OPENAI_API_BASE),
            )
            body = (response.choices[0].message.content or "").strip()
            break
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            last_exc = exc
            if attempt < config.LLM_RETRY_ATTEMPTS - 1:
                time.sleep(config.LLM_RETRY_DELAY * (2**attempt))
        except Exception as exc:
            last_exc = exc
            break
    if not body:
        return f"_Brief generation failed: {last_exc}_"

    if opportunities:
        return body + "\n\n" + format_transfer_candidates_section(opportunities)
    return body + "\n\n" + _EMPTY_TRANSFER_SECTION


def save_hotspot_brief(
    path: str | None = None,
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    min_recent: int | None = None,
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

    payload = compute_weekly_hotspots(
        window_days=window_days,
        prior_days=prior_days,
        min_recent=min_recent,
    )
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
