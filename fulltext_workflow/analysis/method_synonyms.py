"""Analysis-layer Method alias → canonical soft mapping."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from extractor.entity_normalize import _norm_key, is_generic_method
from analysis.method_maturity import established_method_aliases

_METHOD_SYNONYMS: dict[str, str] = {
    # curated human-approved only (seeds)
    "llm": "large language model",
    "large language models": "large language model",
    "support vector machines": "support vector machine",
    "svms": "support vector machine",
}

_SAFE_PLURALS: dict[str, str] = {
    "models": "model",
    "networks": "network",
    "algorithms": "algorithm",
}

_SKELETON_DROP = frozenset({
    "framework", "frameworks", "model", "models", "based", "using",
    "approach", "method", "methods", "system", "pipeline", "tool",
    "algorithm", "algorithms", "network", "networks", "the", "a", "an",
    "with", "and", "for", "of", "in", "on", "to",
})

_PAREN_RE = re.compile(r"^(?P<head>.+?)\s*\((?P<inner>[^)]+)\)\s*$")


def load_method_synonyms() -> dict[str, str]:
    return dict(_METHOD_SYNONYMS)


def apply_auto_method_canonical(name: str) -> str:
    key = _norm_key(name)
    established = established_method_aliases()
    # parenthetical: "support vector machine (svm)"
    m = _PAREN_RE.match(key)
    if m:
        head = _norm_key(m.group("head"))
        inner = _norm_key(m.group("inner"))
        if (
            head in established
            or inner in established
            or head in _METHOD_SYNONYMS
            or inner in _METHOD_SYNONYMS
        ):
            # prefer longer established form when inner is short alias
            if head in established or head in _METHOD_SYNONYMS.values() or len(head) >= len(inner):
                key = head
            else:
                key = inner
    # safe last-token plural
    parts = key.split()
    if parts and parts[-1] in _SAFE_PLURALS:
        parts = parts[:-1] + [_SAFE_PLURALS[parts[-1]]]
        key = " ".join(parts)
    # established alias collapse to preferred display form
    if key in ("llm", "large language models"):
        return "large language model"
    if key in ("svm", "svms", "support vector machines"):
        return "support vector machine"
    return key


def resolve_method_canonical(name: str) -> str:
    key = _norm_key(name)
    if key in _METHOD_SYNONYMS:
        return _METHOD_SYNONYMS[key]
    auto = apply_auto_method_canonical(name)
    if auto in _METHOD_SYNONYMS:
        return _METHOD_SYNONYMS[auto]
    return auto


def method_skeleton(name: str) -> str:
    tokens = [
        t for t in _norm_key(name).replace("-", " ").split()
        if t and t not in _SKELETON_DROP
    ]
    return " ".join(tokens)


def near_duplicate_method_candidates(
    names: list[str],
    *,
    min_shared_tokens: int = 2,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from rapidfuzz import fuzz

    uniq = sorted({_norm_key(n) for n in names if n and str(n).strip()})
    # skip pairs already co-resolved
    out: list[dict[str, Any]] = []
    for i, a in enumerate(uniq):
        sa = method_skeleton(a)
        ta = frozenset(sa.split())
        for b in uniq[i + 1 :]:
            if resolve_method_canonical(a) == resolve_method_canonical(b) and a != b:
                continue  # already merged at runtime
            sb = method_skeleton(b)
            tb = frozenset(sb.split())
            shared = ta & tb
            reason = None
            score = 0.0
            if sa and sa == sb and sa:
                reason = "skeleton"
                score = 1.0
            elif len(shared) >= min_shared_tokens:
                reason = "jaccard"
                score = len(shared) / max(len(ta | tb), 1)
            else:
                ratio = fuzz.token_set_ratio(a, b) / 100.0
                if ratio >= 0.9 and abs(len(a) - len(b)) <= max(10, len(a) // 2):
                    reason = "fuzz"
                    score = ratio
            if not reason:
                continue
            # forbid suggesting map onto umbrella generic
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if is_generic_method(shorter):
                continue
            out.append({
                "alias": longer,
                "suggested_canonical": shorter,
                "score": round(score, 3),
                "reason": reason,
                "shared_tokens": sorted(shared),
            })
    out.sort(key=lambda r: (-float(r["score"]), r["alias"]))
    return out[:limit]


def _fetch_method_rows() -> list[dict[str, Any]]:
    """Load every Method entity with its distinct active APPLIES_METHOD paper count."""
    from db.schema import get_conn

    sql = """
        SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS paper_cnt
        FROM entities e
        LEFT JOIN relations r
          ON r.object_id = e.id
         AND r.relation = 'APPLIES_METHOD'
         AND COALESCE(r.status, 'active') = 'active'
        WHERE e.type = 'Method'
        GROUP BY e.id, e.name
        ORDER BY paper_cnt DESC, e.name ASC
    """
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql).fetchall()]


def run_method_cluster_audit(limit: int = 50) -> str:
    """Return a read-only markdown report of suggested Method synonym clusters."""
    rows = _fetch_method_rows()
    counts = {str(row["name"]): int(row["paper_cnt"] or 0) for row in rows}
    candidates = near_duplicate_method_candidates(list(counts), limit=max(0, limit))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parts = [
        "# Method Cluster Audit",
        "",
        f"Generated: {generated}",
        "",
        "This report is read-only. Review candidates and curate into "
        "`_METHOD_SYNONYMS` manually; it does not change entity names or write mappings.",
        "",
        "## Summary",
        "",
        f"- Method entities: {len(rows)}",
        f"- Suggested candidates shown: {len(candidates)}",
        "",
        "## Near-duplicate candidates",
        "",
    ]
    if not candidates:
        parts.append("_None._")
    else:
        parts.extend([
            "| Alias | Suggested canonical | Papers | Score | Reason |",
            "| --- | --- | ---: | ---: | --- |",
        ])
        for candidate in candidates:
            alias = str(candidate["alias"])
            canonical = str(candidate["suggested_canonical"])
            parts.append(
                f"| {alias} | {canonical} | {counts.get(alias, 0)} | "
                f"{candidate['score']} | {candidate['reason']} |"
            )
    return "\n".join(parts) + "\n"
