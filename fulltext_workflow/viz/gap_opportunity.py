"""Pure helpers for Visualization opportunity table (focus gaps × Fangxin)."""
from __future__ import annotations

from typing import Any


def data_support_tier(cohort_size: int | None, *, mapped: bool) -> str:
    """Map cohort size to high/medium/low/none. Unmapped or missing cache → none."""
    if not mapped or cohort_size is None:
        return "none"
    n = int(cohort_size)
    if n >= 500:
        return "high"
    if n >= 200:
        return "medium"
    return "low"


def summarize_opportunities(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate metrics for the Visualization summary strip."""
    combo_count = len(rows)
    scarce_count = sum(1 for r in rows if r.get("gap") in ("unexplored", "minimal"))
    mapped_count = sum(1 for r in rows if r.get("disease_id"))
    high_n = sum(1 for r in rows if r.get("data") == "high")
    high_share = (100.0 * high_n / combo_count) if combo_count else 0.0
    return {
        "combo_count": combo_count,
        "scarce_count": scarce_count,
        "mapped_count": mapped_count,
        "high_share": high_share,
    }
