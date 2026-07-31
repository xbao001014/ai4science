"""Analysis-layer Method alias → canonical soft mapping."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from extractor.entity_normalize import _norm_key
from analysis.method_maturity import is_established_blacklist

_METHOD_SYNONYMS: dict[str, str] = {
    # curated human-approved only (seeds)
    "llm": "large language model",
    "large language models": "large language model",
    "support vector machines": "support vector machine",
    "svms": "support vector machine",
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


def _parenthetical_is_same_concept(head: str, inner: str) -> bool:
    """Return whether the parenthetical is a known alias of its head."""
    initials = "".join(
        token[0] for token in re.findall(r"[a-z0-9]+", head) if token
    )
    if inner == initials:
        return True
    return (
        _METHOD_SYNONYMS.get(head, head)
        == _METHOD_SYNONYMS.get(inner, inner)
        and (head in _METHOD_SYNONYMS or inner in _METHOD_SYNONYMS)
    )


def apply_auto_method_canonical(name: str) -> str:
    key = _norm_key(name)
    # parenthetical: "support vector machine (svm)"
    m = _PAREN_RE.match(key)
    if m:
        head = _norm_key(m.group("head"))
        inner = _norm_key(m.group("inner"))
        if _parenthetical_is_same_concept(head, inner):
            # Parenthetical aliases conventionally expand a shorter acronym.
            key = head if len(head) >= len(inner) else inner
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
    paper_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    from rapidfuzz import fuzz

    counts = {
        _norm_key(name): int(count or 0)
        for name, count in (paper_counts or {}).items()
    }
    records = []
    for name in sorted({_norm_key(n) for n in names if n and str(n).strip()}):
        skeleton = method_skeleton(name)
        tokens = frozenset(skeleton.split())
        records.append({
            "name": name,
            "canonical": resolve_method_canonical(name),
            "skeleton": skeleton,
            "tokens": tokens,
            "paper_cnt": counts.get(name, 0),
        })
    token_blocks: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        for token in record["tokens"]:
            token_blocks.setdefault(token, []).append(index)

    out: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for i, left in enumerate(records):
        candidate_indices: set[int] = set()
        for token in left["tokens"]:
            candidate_indices.update(token_blocks[token])
        for j in candidate_indices:
            if j <= i or (i, j) in seen_pairs:
                continue  # already merged at runtime
            seen_pairs.add((i, j))
            right = records[j]
            if left["canonical"] == right["canonical"] and left["name"] != right["name"]:
                continue
            shared = left["tokens"] & right["tokens"]
            reason = None
            score = 0.0
            if left["skeleton"] and left["skeleton"] == right["skeleton"]:
                reason = "skeleton"
                score = 1.0
            elif len(shared) >= min_shared_tokens:
                reason = "jaccard"
                score = len(shared) / max(len(left["tokens"] | right["tokens"]), 1)
            else:
                ratio = fuzz.token_set_ratio(left["name"], right["name"]) / 100.0
                if ratio >= 0.9 and abs(len(left["name"]) - len(right["name"])) <= max(10, len(left["name"]) // 2):
                    reason = "fuzz"
                    score = ratio
            if not reason:
                continue
            canonical, alias = sorted(
                (left, right),
                key=lambda record: (-record["paper_cnt"], len(record["name"]), record["name"]),
            )
            # Never suggest collapsing onto established or generic umbrellas.
            if is_established_blacklist(canonical["name"]):
                continue
            out.append({
                "alias": alias["name"],
                "suggested_canonical": canonical["name"],
                "score": round(score, 3),
                "reason": reason,
                "shared_tokens": sorted(shared),
            })
    out.sort(key=lambda r: (-float(r["score"]), r["alias"], r["suggested_canonical"]))
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
    counts: dict[str, int] = {}
    for row in rows:
        key = _norm_key(str(row["name"]))
        counts[key] = max(counts.get(key, 0), int(row["paper_cnt"] or 0))
    candidates = near_duplicate_method_candidates(
        list(counts), limit=max(0, limit), paper_counts=counts
    )
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
