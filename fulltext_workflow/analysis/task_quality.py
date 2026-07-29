"""Task entity quality tiers for bridging and audit."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Literal

from extractor.entity_normalize import (
    is_reject_task,
    normalize_entity_name,
)

TaskTier = Literal["reject", "weak", "ok"]

_STOP = frozenset({"of", "the", "and", "a", "an", "for", "in", "on", "to"})


def classify_task_quality(name: str) -> TaskTier:
    canon = normalize_entity_name(name, "Task")
    if is_reject_task(canon):
        return "reject"
    tokens = [t for t in canon.split() if t and t not in _STOP]
    if len(tokens) <= 1:
        return "weak"
    return "ok"


def _token_set(name: str) -> frozenset[str]:
    canon = normalize_entity_name(name, "Task")
    return frozenset(t for t in canon.split() if t and t not in _STOP)


def near_duplicate_candidates(names: list[str], *, min_shared_tokens: int = 2) -> list[dict[str, Any]]:
    """Suggest unmapped near-duplicates for synonym table curation (no auto-merge)."""
    uniq = sorted({normalize_entity_name(n, "Task") for n in names if n and n.strip()})
    out: list[dict[str, Any]] = []
    for i, a in enumerate(uniq):
        ta = _token_set(a)
        if len(ta) < min_shared_tokens:
            continue
        for b in uniq[i + 1 :]:
            if a == b:
                continue
            tb = _token_set(b)
            shared = ta & tb
            if len(shared) >= min_shared_tokens and ta != tb:
                out.append({"a": a, "b": b, "shared_tokens": sorted(shared)})
    return out[:50]


def audit_task_names(names: list[str]) -> dict[str, Any]:
    by_tier: dict[str, list[str]] = defaultdict(list)
    for raw in names:
        tier = classify_task_quality(raw)
        by_tier[tier].append(normalize_entity_name(raw, "Task"))
    counts = {t: len(by_tier.get(t, [])) for t in ("reject", "weak", "ok")}
    return {
        "counts": counts,
        "by_tier": {k: sorted(set(v)) for k, v in by_tier.items()},
        "near_duplicate_candidates": near_duplicate_candidates(names),
    }


def _fetch_task_rows() -> list[dict[str, Any]]:
    from db.schema import get_conn

    sql = """
        SELECT e.name AS name,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt
        FROM entities e
        LEFT JOIN relations r
          ON r.object_id = e.id
         AND r.object_type = 'Task'
         AND r.relation = 'PERFORMS_TASK'
         AND COALESCE(r.status, 'active') = 'active'
        WHERE e.type = 'Task'
        GROUP BY e.id, e.name
        ORDER BY paper_cnt DESC, e.name ASC
    """
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql).fetchall()]


def _fetch_performs_task_coverage() -> dict[str, int]:
    from db.schema import get_conn

    with get_conn() as conn:
        extracted = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE COALESCE(extraction_done, 0) = 1"
        ).fetchone()[0]
        with_task = conn.execute(
            """
            SELECT COUNT(DISTINCT source_pmid)
            FROM relations
            WHERE relation = 'PERFORMS_TASK'
              AND COALESCE(status, 'active') = 'active'
              AND source_pmid IS NOT NULL
              AND TRIM(source_pmid) != ''
            """
        ).fetchone()[0]
        task_entities = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE type = 'Task'"
        ).fetchone()[0]
        linked_tasks = conn.execute(
            """
            SELECT COUNT(DISTINCT e.id)
            FROM entities e
            JOIN relations r
              ON r.object_id = e.id
             AND r.object_type = 'Task'
             AND r.relation = 'PERFORMS_TASK'
             AND COALESCE(r.status, 'active') = 'active'
            WHERE e.type = 'Task'
            """
        ).fetchone()[0]
    return {
        "extracted_papers": int(extracted),
        "papers_with_performs_task": int(with_task),
        "task_entities": int(task_entities),
        "linked_task_entities": int(linked_tasks),
    }


def _tier_examples(
    rows: list[dict[str, Any]],
    *,
    limit_examples: int,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tier = classify_task_quality(str(row["name"]))
        grouped[tier].append(row)
    for tier in grouped:
        grouped[tier].sort(
            key=lambda r: (-int(r.get("paper_cnt") or 0), str(r["name"]))
        )
    return {
        tier: grouped.get(tier, [])[:limit_examples]
        for tier in ("reject", "weak", "ok")
    }


def _format_example_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_None._\n"
    lines = ["| Task | Papers |", "| --- | ---: |"]
    for row in rows:
        lines.append(f"| {row['name']} | {int(row.get('paper_cnt') or 0)} |")
    return "\n".join(lines) + "\n"


def _format_near_duplicate_table(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "_None._\n"
    lines = ["| A | B | Shared tokens |", "| --- | --- | --- |"]
    for item in candidates:
        shared = ", ".join(item.get("shared_tokens") or [])
        lines.append(f"| {item['a']} | {item['b']} | {shared} |")
    return "\n".join(lines) + "\n"


def run_task_quality_audit(*, limit_examples: int = 20) -> str:
    """Read Task entities from SQLite and return a markdown audit report."""
    rows = _fetch_task_rows()
    names = [str(row["name"]) for row in rows]
    audit = audit_task_names(names)
    coverage = _fetch_performs_task_coverage()
    examples = _tier_examples(rows, limit_examples=limit_examples)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    extracted = coverage["extracted_papers"]
    with_task = coverage["papers_with_performs_task"]
    pct = (100.0 * with_task / extracted) if extracted else 0.0
    task_entities = coverage["task_entities"]
    linked_tasks = coverage["linked_task_entities"]
    task_pct = (100.0 * linked_tasks / task_entities) if task_entities else 0.0

    parts = [
        "# Task Quality Audit",
        "",
        f"Generated: {generated}",
        "",
        "## Summary",
        "",
        "| Tier | Count |",
        "| --- | ---: |",
        f"| reject | {audit['counts']['reject']} |",
        f"| weak | {audit['counts']['weak']} |",
        f"| ok | {audit['counts']['ok']} |",
        "",
        f"**Total Task entities:** {task_entities}",
        "",
        "## PERFORMS_TASK coverage",
        "",
        f"- Extracted papers: {extracted}",
        f"- Papers with PERFORMS_TASK: {with_task} ({pct:.1f}%)",
        f"- Task entities linked via PERFORMS_TASK: {linked_tasks} / {task_entities} ({task_pct:.1f}%)",
        "",
        "## reject examples",
        "",
        _format_example_table(examples["reject"]),
        "## weak examples",
        "",
        _format_example_table(examples["weak"]),
        "## ok examples",
        "",
        _format_example_table(examples["ok"]),
        "## Near-duplicate candidates",
        "",
        _format_near_duplicate_table(audit["near_duplicate_candidates"]),
    ]
    return "\n".join(parts)
