"""Citation / IF weighting helpers for gap research ranking."""
from __future__ import annotations

import math
from typing import Any

import config


def cite_per_year(citation_count: float | int | None, year: int | None) -> float:
    if not citation_count:
        return 0.0
    yr = year or config.SEARCH_YEAR_END
    return float(citation_count) / max(1, 2026 - int(yr))


def norm_if(impact_factor: float | None) -> float:
    if not impact_factor or impact_factor <= 0:
        return 0.0
    return min(float(impact_factor) / 20.0, 1.0)


def compute_impact_score(
    avg_cite: float | None,
    avg_cite_per_year: float | None,
    avg_if: float | None,
    q1_ratio: float | None,
) -> float:
    """Return 0–3 impact contribution for priority ranking."""
    ac = float(avg_cite or 0)
    acy = float(avg_cite_per_year or 0)
    aif = norm_if(avg_if)
    q1 = float(q1_ratio or 0)

    raw = (
        0.30 * math.log1p(ac)
        + 0.30 * math.log1p(acy)
        + 0.20 * aif
        + 0.20 * q1
    )
    return round(min(3.0, raw * 1.2), 2)


def impact_tier(impact_score: float) -> str:
    if impact_score >= 2.0:
        return "High"
    if impact_score >= 1.0:
        return "Medium"
    if impact_score > 0:
        return "Emerging"
    return "Unknown"


def literature_gap_points(gap: str) -> int:
    if gap == "unexplored":
        return 3
    if gap == "minimal":
        return 2
    return 1


def data_support_points(mock_cases: int) -> int:
    if mock_cases >= 500:
        return 3
    if mock_cases >= 200:
        return 1
    return 0


def total_priority_score(
    literature_gap: str,
    mock_cases: int,
    impact_score: float,
) -> float:
    """Gap evidence + data feasibility + literature impact (each ~0–3)."""
    lit = literature_gap_points(literature_gap)
    data = data_support_points(mock_cases)
    return round(
        lit * config.GAP_WEIGHT_EVIDENCE
        + data * config.GAP_WEIGHT_FEASIBILITY
        + impact_score * config.GAP_WEIGHT_IMPACT,
        2,
    )


def aggregate_paper_impact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize citation/IF stats from paper-level rows."""
    if not rows:
        return {
            "support_paper_cnt": 0,
            "avg_cite": 0.0,
            "avg_cite_per_year": 0.0,
            "avg_if": 0.0,
            "q1_ratio": 0.0,
            "impact_score": 0.0,
            "impact_tier": "Unknown",
        }

    cites = [float(r.get("citation_count") or 0) for r in rows]
    cpys = [cite_per_year(r.get("citation_count"), r.get("year")) for r in rows]
    ifs = [float(r["impact_factor"]) for r in rows if r.get("impact_factor")]
    q1 = sum(
        1 for r in rows
        if str(r.get("quartile") or "").upper().startswith("Q1")
    )

    avg_cite = sum(cites) / len(cites)
    avg_cpy = sum(cpys) / len(cpys)
    avg_if = sum(ifs) / len(ifs) if ifs else 0.0
    q1_ratio = q1 / len(rows)

    score = compute_impact_score(avg_cite, avg_cpy, avg_if, q1_ratio)
    return {
        "support_paper_cnt": len(rows),
        "avg_cite": round(avg_cite, 1),
        "avg_cite_per_year": round(avg_cpy, 2),
        "avg_if": round(avg_if, 2),
        "q1_ratio": round(q1_ratio, 2),
        "impact_score": score,
        "impact_tier": impact_tier(score),
    }
