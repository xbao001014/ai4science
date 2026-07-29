"""Task entity quality tiers for bridging and audit."""
from __future__ import annotations

from collections import defaultdict
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
