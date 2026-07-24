"""Deterministic proposal implementation difficulty (target vs assessed)."""
from __future__ import annotations

import re
from typing import Any

import config

DIFFICULTY_LEVELS = ("easy", "moderate", "hard")
_PREPRINT = re.compile(r"biorxiv|medrxiv|arxiv|preprint|research square", re.I)


def difficulty_ordinal(level: str) -> int:
    key = (level or "").strip().lower()
    if key not in DIFFICULTY_LEVELS:
        raise ValueError(f"invalid difficulty level: {level!r}")
    return DIFFICULTY_LEVELS.index(key)


def difficulty_color(delta: int) -> str:
    if delta == 0:
        return "green"
    if abs(int(delta)) == 1:
        return "amber"
    return "red"


def _is_preprint(row: dict[str, Any]) -> bool:
    blob = " ".join(
        str(row.get(k) or "")
        for k in ("journal_abbr", "journal_name", "name", "abbr")
    )
    return bool(_PREPRINT.search(blob))


def _valid_quartile(q: Any) -> str | None:
    if q is None:
        return None
    s = str(q).strip().upper()
    if s in ("", "NAN", "NONE", "NULL"):
        return None
    if s.startswith("Q") and s[1:2].isdigit():
        return s[:2] if len(s) >= 2 else s
    return None


def research_bar_from_papers(papers: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(papers)
    if n == 0:
        return {
            "research_bar": "easy",
            "q1_ratio": 0.0,
            "avg_if": 0.0,
            "q_coverage": 0.0,
            "q_coverage_low": True,
            "support_paper_cnt": 0,
        }

    q_ok = 0
    q1 = 0
    ifs: list[float] = []
    for r in papers:
        if _is_preprint(r):
            continue
        q = _valid_quartile(r.get("quartile"))
        if q:
            q_ok += 1
            if q == "Q1":
                q1 += 1
        raw_if = r.get("impact_factor")
        if raw_if is not None and str(raw_if).strip() != "":
            try:
                v = float(raw_if)
                if v > 0:
                    ifs.append(v)
            except (TypeError, ValueError):
                pass

    # q1_ratio and q_coverage over full |S| (spec); preprints simply never increment q1/q_ok
    q1_ratio = q1 / n
    q_coverage = q_ok / n
    avg_if = sum(ifs) / len(ifs) if ifs else 0.0

    if q1_ratio >= config.DIFFICULTY_Q1_HARD or avg_if >= config.DIFFICULTY_IF_HARD:
        bar = "hard"
    elif q1_ratio >= config.DIFFICULTY_Q1_MODERATE or avg_if >= config.DIFFICULTY_IF_MODERATE:
        bar = "moderate"
    else:
        bar = "easy"

    return {
        "research_bar": bar,
        "q1_ratio": round(q1_ratio, 3),
        "avg_if": round(avg_if, 2),
        "q_coverage": round(q_coverage, 3),
        "q_coverage_low": q_coverage < config.DIFFICULTY_Q_COVERAGE_LOW,
        "support_paper_cnt": n,
    }


def fangxin_tier(feasibility_score: float | None, cohort: int | None) -> str:
    score = float(feasibility_score) if feasibility_score is not None else 0.0
    size = int(cohort) if cohort is not None else 0
    if score >= config.DIFFICULTY_FX_EASY_SCORE and size >= config.DIFFICULTY_FX_EASY_COHORT:
        return "easy"
    if score >= config.DIFFICULTY_FX_MOD_SCORE or size >= config.DIFFICULTY_FX_MOD_COHORT:
        return "moderate"
    return "hard"


def apply_public_relief(
    tier: str, public_datasets: list[str]
) -> tuple[str, list[str]]:
    names = [n for n in public_datasets if n and str(n).strip()]
    if not names or tier == "easy":
        return tier, []
    idx = difficulty_ordinal(tier)
    new_tier = DIFFICULTY_LEVELS[max(0, idx - 1)]
    return new_tier, names


def assess_implementation_difficulty(
    *,
    target_difficulty: str,
    papers: list[dict[str, Any]],
    feasibility_score: float | None,
    available_cohort_size: int | None,
    public_datasets: list[str],
) -> dict[str, Any]:
    target = (target_difficulty or "moderate").strip().lower()
    if target not in DIFFICULTY_LEVELS:
        target = "moderate"

    research = research_bar_from_papers(papers)
    fx = fangxin_tier(feasibility_score, available_cohort_size)
    engineering, relies_on_public = apply_public_relief(fx, public_datasets)

    assessed = DIFFICULTY_LEVELS[
        max(
            difficulty_ordinal(research["research_bar"]),
            difficulty_ordinal(engineering),
        )
    ]
    delta = difficulty_ordinal(assessed) - difficulty_ordinal(target)
    color = difficulty_color(delta)

    breakdown = {
        **research,
        "fangxin_tier": fx,
        "engineering_bar": engineering,
        "feasibility_score": feasibility_score,
        "available_cohort_size": available_cohort_size,
        "relies_on_public": relies_on_public,
    }
    summary = (
        f"research={research['research_bar']} (Q1 {research['q1_ratio']:.0%}) · "
        f"engineering={engineering} (Fangxin {feasibility_score if feasibility_score is not None else 'n/a'}"
        + (f" + public: {', '.join(relies_on_public)}" if relies_on_public else "")
        + ")"
    )
    return {
        "target_difficulty": target,
        "assessed_difficulty": assessed,
        "research_bar": research["research_bar"],
        "engineering_bar": engineering,
        "difficulty_delta": delta,
        "color": color,
        "q_coverage_low": research["q_coverage_low"],
        "breakdown": breakdown,
        "summary_line": summary,
    }


def format_difficulty_markdown_header(result: dict[str, Any]) -> str:
    """Plain-text header for proposal Markdown (colors live in UI)."""
    low = " | Q coverage low" if result.get("q_coverage_low") else ""
    return (
        f"> **Difficulty** · target=`{result['target_difficulty']}` · "
        f"assessed=`{result['assessed_difficulty']}` · "
        f"delta={result['difficulty_delta']:+d} ({result['color']}){low}\n"
        f"> {result['summary_line']}\n"
    )


def load_public_datasets_for_keyword(keyword: str) -> list[str]:
    """Public datasets from V-03 recommended_public (paper-mediated)."""
    from analysis.public_dataset_feasibility import assess_public_datasets

    payload = assess_public_datasets(keyword)
    return [
        str(r["dataset"])
        for r in (payload.get("recommended_public") or [])
        if r.get("dataset")
    ]


def load_supporting_papers_for_keyword(
    keyword: str, limit: int | None = None
) -> list[dict[str, Any]]:
    from analysis.focus_filter import resolve_topic_pmids

    pmids, _strategy = resolve_topic_pmids(keyword)
    return load_supporting_papers_by_pmids(pmids, limit=limit)


def load_supporting_papers_by_pmids(
    pmids: list[str], limit: int | None = None
) -> list[dict[str, Any]]:
    from db.schema import get_conn

    normalized_pmids = list(dict.fromkeys(str(pmid).strip() for pmid in pmids if str(pmid).strip()))
    if not normalized_pmids:
        return []

    placeholders = ", ".join("?" for _ in normalized_pmids)
    lim = int(limit if limit is not None else config.TOOL_TOP_N)
    if lim < 0:
        lim = 0
    sql = f"""
        SELECT p.pmid, p.title, p.year, p.journal_name, p.journal_abbr,
               p.citation_count, j.quartile, j.impact_factor
        FROM papers p
        LEFT JOIN journals j ON p.journal_id = j.id
        WHERE p.pmid IN ({placeholders})
        ORDER BY p.year DESC
        LIMIT ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (*normalized_pmids, lim)).fetchall()
    return [dict(r) for r in rows]
