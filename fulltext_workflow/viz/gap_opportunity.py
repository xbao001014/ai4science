"""Pure helpers for Visualization opportunity table (focus gaps × Fangxin)."""
from __future__ import annotations

from typing import Any

from analysis.focus_filter import meaningful_keyword_tokens


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


LIT_GAP_RANK = {"unexplored": 0, "minimal": 1}
DATA_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}


def normalize_opportunity_gap(g: dict[str, Any]) -> dict[str, Any]:
    """Unify transferable + legacy combo shapes for build_opportunity_rows."""
    out = dict(g)
    if not out.get("gap"):
        out["gap"] = out.get("literature_gap") or ""
    if "paper_cnt" not in out or out.get("paper_cnt") is None:
        out["paper_cnt"] = int(out.get("literature_paper_cnt") or 0)
    else:
        out["paper_cnt"] = int(out.get("paper_cnt") or 0)
    out.setdefault("bridge_task", "")
    out.setdefault("bridge_mode", "")
    out.setdefault("bridge_quality", "")
    out.setdefault("support_diseases", "")
    if out.get("support_diseases") is not None and not isinstance(out["support_diseases"], str):
        out["support_diseases"] = ", ".join(str(x) for x in out["support_diseases"])
    out["opportunity_score"] = float(out.get("opportunity_score") or 0.0)
    return out


def sort_opportunity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple:
        return (
            0 if r.get("source") == "Debate" else 1,
            -float(r.get("opportunity_score") or 0.0),
            LIT_GAP_RANK.get(str(r.get("gap") or ""), 2),
            DATA_RANK.get(str(r.get("data") or "none"), 3),
            int(r.get("paper_cnt") or 0),
            str(r.get("method") or "").lower(),
            str(r.get("disease") or "").lower(),
        )

    return sorted(rows, key=key)


def build_opportunity_rows(
    gaps: list[dict[str, Any]],
    disease_cases: dict[str, int],
    disease_id_by_name: dict[str, str | None],
    *,
    source_default: str = "Corpus",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for g in gaps:
        g = normalize_opportunity_gap(g)
        method = str(g.get("method") or "")
        disease = str(g.get("disease") or "")
        did = disease_id_by_name.get(disease)
        if did and did in disease_cases:
            tier = data_support_tier(disease_cases[did], mapped=True)
        elif did:
            tier = data_support_tier(None, mapped=False)  # no cache
        else:
            did = None
            tier = data_support_tier(None, mapped=False)
        out.append({
            "source": source_default,
            "method": method,
            "disease": disease,
            "gap": g.get("gap") or "",
            "paper_cnt": int(g.get("paper_cnt") or 0),
            "bridge_task": g.get("bridge_task") or "",
            "bridge_mode": g.get("bridge_mode") or "",
            "bridge_quality": g.get("bridge_quality") or "",
            "support_diseases": g.get("support_diseases") or "",
            "opportunity_score": float(g.get("opportunity_score") or 0.0),
            "gap_kind": g.get("gap_kind") or "applied",
            "covers_disease_paper_cnt": int(g.get("covers_disease_paper_cnt") or 0),
            "surveys_method_paper_cnt": int(g.get("surveys_method_paper_cnt") or 0),
            "disease_id": did,
            "data": tier,
            "row_key": f"{method}||{disease}",
        })
    return out


def apply_debate_overlay(
    rows: list[dict[str, Any]],
    debate_titles: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    matched_title_idxs: set[int] = set()
    debate_keys: set[str] = set()
    for i, title in enumerate(debate_titles):
        tokens = meaningful_keyword_tokens(title)
        if not tokens:
            continue
        for r in rows:
            hay = f"{r.get('method', '')} {r.get('disease', '')}".lower()
            if any(t in hay for t in tokens):
                debate_keys.add(str(r.get("row_key")))
                matched_title_idxs.add(i)
    updated = []
    for r in rows:
        nr = dict(r)
        if str(nr.get("row_key")) in debate_keys:
            nr["source"] = "Debate"
        updated.append(nr)
    unmatched = [
        t for i, t in enumerate(debate_titles)
        if i not in matched_title_idxs
    ]
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in unmatched:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return updated, uniq


def filter_opportunity_rows(
    rows: list[dict[str, Any]],
    *,
    scarce_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    out = rows
    if scarce_only:
        out = [r for r in out if r.get("gap") in ("unexplored", "minimal")]
    return out[: max(0, int(limit))]


def primary_viz_gaps(
    focus: str | None,
    *,
    limit: int | None = None,
    window_days: int | None = None,
    opportunities: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Main-table source only. Never falls back to method_disease_combo_gap."""
    if not (focus or "").strip():
        return []
    if opportunities is not None:
        return opportunities
    from analysis.weekly_hotspot import compute_emerging_gap_opportunities
    return list(
        compute_emerging_gap_opportunities(
            focus=focus,
            limit=limit,
            window_days=window_days,
        )
    )


def assemble_opportunity_view(
    *,
    gaps: list[dict[str, Any]],
    disease_cases: dict[str, int],
    disease_id_by_name: dict[str, str | None],
    debate_titles: list[str] | None = None,
    scarce_only: bool = True,
    limit: int = 30,
) -> dict[str, Any]:
    gaps = [normalize_opportunity_gap(g) for g in gaps]
    rows = build_opportunity_rows(gaps, disease_cases, disease_id_by_name)
    unmatched: list[str] = []
    if debate_titles:
        rows, unmatched = apply_debate_overlay(rows, debate_titles)
    rows = sort_opportunity_rows(rows)
    rows = filter_opportunity_rows(rows, scarce_only=scarce_only, limit=limit)
    return {
        "rows": rows,
        "summary": summarize_opportunities(rows),
        "unmatched_debate": unmatched,
        "debate_matched_count": sum(1 for r in rows if r.get("source") == "Debate"),
    }
