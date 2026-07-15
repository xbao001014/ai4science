"""Weekly ops memory: fingerprinting, persist, soft-avoid prompt blocks."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import config
from analysis.weekly_hotspot import week_id as iso_week_id
from db.schema import (
    fetch_ops_gap_items_for_runs,
    fetch_recent_ops_runs,
    find_ops_gap_items_by_run,
    find_ops_run_by_week_focus,
    insert_ops_gap_items,
    insert_ops_proposal,
    insert_ops_run,
    update_ops_run_finalize,
    update_ops_run_hotspot,
    update_ops_run_proposal_path,
)
from pipeline_utils import parse_gap_sections, parse_gap_titles

_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)


def normalize_focus_key(focus: str | None) -> str:
    if focus is None:
        return "__all__"
    s = " ".join(str(focus).strip().lower().split())
    return s if s else "__all__"


def tokenize_for_fingerprint(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall((text or "").lower())
    return sorted(set(tokens))


def fingerprint_gap_title(title: str) -> str:
    toks = tokenize_for_fingerprint(title)
    joined = " ".join(toks)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def jaccard_overlap(a: str, b: str) -> float:
    sa, sb = set(tokenize_for_fingerprint(a)), set(tokenize_for_fingerprint(b))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class MemoryGapItem:
    run_id: int
    week_id: str
    title: str
    research_question: str = ""
    fingerprint: str = ""
    status: str = "reported"


@dataclass
class MemoryBundle:
    focus_key: str
    run_ids: list[int] = field(default_factory=list)
    items: list[MemoryGapItem] = field(default_factory=list)


def create_ops_run(focus_raw: str | None, source: str, *, week_id: str | None = None) -> int:
    wid = week_id or iso_week_id()
    key = normalize_focus_key(focus_raw)
    return insert_ops_run(
        week_id=wid,
        focus_raw=(focus_raw or "") if focus_raw else None,
        focus_key=key,
        source=source,
    )


def finalize_ops_run(
    run_id: int,
    *,
    gap_report_path: str = "",
    hotspot_week_id: str = "",
    proposal_report_path: str = "",
) -> None:
    update_ops_run_finalize(
        run_id,
        gap_report_path=gap_report_path,
        hotspot_week_id=hotspot_week_id,
        proposal_report_path=proposal_report_path,
    )


def _extract_research_question(section_md: str) -> str:
    m = re.search(
        r"\*\*Research question\*\*[：:]\s*(.+)",
        section_md or "",
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()[:500]
    m = re.search(r"\*\*研究问题\*\*[：:]\s*(.+)", section_md or "")
    return m.group(1).strip()[:500] if m else ""


def persist_gaps_from_report(
    run_id: int,
    report_text: str,
    *,
    status_by_title: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    sections = parse_gap_sections(report_text)
    if not sections:
        titles = parse_gap_titles(report_text)
        sections = [(t, t) for t in titles]
    items: list[dict[str, Any]] = []
    max_chars = config.OPS_MEMORY_SECTION_MAX_CHARS
    status_map = status_by_title or {}
    for i, (title, body) in enumerate(sections, start=1):
        items.append({
            "rank_pos": i,
            "title": title,
            "research_question": _extract_research_question(body),
            "fingerprint": fingerprint_gap_title(title),
            "section_md": (body or "")[:max_chars],
            "status": status_map.get(title, "reported"),
        })
    insert_ops_gap_items(run_id, items)
    return items


def resolve_gap_item_id(run_id: int, gap_title: str | None) -> int | None:
    """Match a gap title to an ops_gap_items row (exact, then Jaccard)."""
    title = (gap_title or "").strip()
    if not title:
        return None
    items = find_ops_gap_items_by_run(run_id)
    if not items:
        return None
    lower = title.lower()
    for it in items:
        if (it.get("title") or "").strip().lower() == lower:
            return int(it["id"])
    thr = config.OPS_MEMORY_JACCARD_THRESHOLD
    best_id: int | None = None
    best_score = 0.0
    for it in items:
        score = jaccard_overlap(title, it.get("title") or "")
        if score >= thr and score > best_score:
            best_score = score
            best_id = int(it["id"])
    return best_id


def persist_proposal(
    run_id: int,
    *,
    gap_item_id: int | None = None,
    gap_title: str | None = None,
    proposal_path: str = "",
    proposal_md: str = "",
    feasibility_score: float | None = None,
    critic_score: float | None = None,
    status: str = "",
    write_file: bool = True,
) -> int:
    """Persist a research proposal linked to an ops run / gap item.

    Prefer writing Markdown under output/ and storing ``proposal_path``;
    truncate inline ``proposal_md`` when a path is available.
    """
    import os
    from datetime import datetime

    if gap_item_id is None and gap_title:
        gap_item_id = resolve_gap_item_id(run_id, gap_title)

    path = proposal_path
    md = proposal_md or ""
    if write_file and md and not path:
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = fingerprint_gap_title(gap_title or "proposal")[:8]
        path = os.path.join(
            config.OUTPUT_DIR, f"ops_proposal_{run_id}_{safe}_{stamp}.md"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)

    stored_md = md
    if path and len(stored_md) > config.OPS_MEMORY_SECTION_MAX_CHARS:
        stored_md = stored_md[: config.OPS_MEMORY_SECTION_MAX_CHARS]

    prop_id = insert_ops_proposal(
        run_id,
        gap_item_id=gap_item_id,
        proposal_path=path,
        proposal_md=stored_md,
        feasibility_score=feasibility_score,
        critic_score=critic_score,
        status=status or "generated",
    )
    if path:
        update_ops_run_proposal_path(run_id, path)
    return prop_id


def link_hotspot_week(
    hotspot_week_id: str,
    *,
    focus_key: str = "__all__",
    source: str = "hotspot",
) -> int:
    existing = find_ops_run_by_week_focus(hotspot_week_id, focus_key)
    if existing:
        update_ops_run_hotspot(existing, hotspot_week_id)
        return existing
    rid = insert_ops_run(
        week_id=hotspot_week_id,
        focus_raw=None if focus_key == "__all__" else focus_key,
        focus_key=focus_key,
        source=source,
    )
    update_ops_run_hotspot(rid, hotspot_week_id)
    finalize_ops_run(rid, hotspot_week_id=hotspot_week_id)
    return rid


def load_recent_gaps(
    focus: str | None,
    limit_runs: int | None = None,
) -> MemoryBundle:
    key = normalize_focus_key(focus)
    lim = limit_runs if limit_runs is not None else config.OPS_MEMORY_LOOKBACK_RUNS
    runs = fetch_recent_ops_runs(key, lim)
    run_ids = [int(r["run_id"]) for r in runs]
    week_by_run = {int(r["run_id"]): (r.get("week_id") or "") for r in runs}
    raw_items = fetch_ops_gap_items_for_runs(run_ids)
    items = [
        MemoryGapItem(
            run_id=int(it["run_id"]),
            week_id=week_by_run.get(int(it["run_id"]), ""),
            title=it["title"],
            research_question=it.get("research_question") or "",
            fingerprint=it.get("fingerprint") or "",
            status=it.get("status") or "reported",
        )
        for it in raw_items
    ]
    return MemoryBundle(focus_key=key, run_ids=run_ids, items=items)


def format_memory_prompt_block(bundle: MemoryBundle) -> str:
    if not bundle.items:
        return ""
    lines = [
        "【Ops memory — soft avoid】",
        f"focus_key={bundle.focus_key}; recent finished runs={len(bundle.run_ids)}",
        "Recently covered directions (prefer novel angles; if revisiting, state Distinction / previously covered):",
    ]
    seen: set[str] = set()
    for it in bundle.items:
        key = it.title.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        q = f" — {it.research_question}" if it.research_question else ""
        lines.append(f"- [{it.week_id}] {it.title}{q}")
    lines.append(
        "Do not merely restate the list above; Skeptic should treat high-overlap items without "
        "stated distinction as duplicate_risk / weak_evidence, not automatic false_gaps."
    )
    return "\n".join(lines)


def tag_revisited_against_memory(
    titles: list[str],
    bundle: MemoryBundle,
    threshold: float | None = None,
) -> list[tuple[str, str]]:
    thr = (
        threshold
        if threshold is not None
        else config.OPS_MEMORY_JACCARD_THRESHOLD
    )
    out: list[tuple[str, str]] = []
    mem_titles = [it.title for it in bundle.items]
    for title in titles:
        status = "reported"
        for mt in mem_titles:
            if jaccard_overlap(title, mt) >= thr:
                status = "revisited"
                break
        out.append((title, status))
    return out


def persist_debate_report(
    report_text: str,
    *,
    focus: str | None,
    source: str,
    gap_report_path: str = "",
    enabled: bool | None = None,
) -> int | None:
    on = config.OPS_MEMORY_ENABLED if enabled is None else enabled
    if not on or not (report_text or "").strip():
        return None
    prior = load_recent_gaps(focus)
    rid = create_ops_run(focus, source)
    titles = parse_gap_titles(report_text)
    status_map: dict[str, str] = {}
    if prior.items and titles:
        status_map = dict(tag_revisited_against_memory(titles, prior))
    persist_gaps_from_report(rid, report_text, status_by_title=status_map)
    finalize_ops_run(rid, gap_report_path=gap_report_path)
    return rid
