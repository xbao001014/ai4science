"""Deterministic public-dataset feasibility (V-03) from KG USES_DATASET.

Selection is paper-mediated via resolve_topic_pmids — dataset names need not
contain the focus keyword (e.g. Camelyon17 for breast topics).
"""
from __future__ import annotations

import re
from typing import Any

import config
from analysis.focus_filter import resolve_topic_pmids
from db.schema import get_conn
from extractor.dataset_access import PUBLIC_DATASET_ALIASES


def _norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def alias_hit(dataset_name: str) -> bool:
    """True if name matches PUBLIC_DATASET_ALIASES or a canonical token."""
    key = _norm_key(dataset_name)
    if not key:
        return False
    if key in PUBLIC_DATASET_ALIASES:
        return True
    canons = set(PUBLIC_DATASET_ALIASES.values())
    for canon in canons:
        if re.search(rf"(^|[^a-z0-9]){re.escape(canon)}([^a-z0-9]|$)", key):
            return True
    return False


def _query_datasets_for_pmids(pmids: list[str]) -> list[dict[str, Any]]:
    if not pmids:
        return []
    placeholders = ", ".join("?" for _ in pmids)
    sql = f"""
        SELECT e_ds.name AS dataset,
               COALESCE(e_ds.access_class, 'unknown') AS access_class,
               COUNT(DISTINCT r_ds.source_pmid) AS used_by_papers,
               GROUP_CONCAT(DISTINCT r_ds.source_pmid) AS pmid_blob
        FROM relations r_ds
        JOIN entities e_ds ON r_ds.object_id = e_ds.id
        WHERE r_ds.relation = 'USES_DATASET'
          AND e_ds.type = 'Dataset'
          AND r_ds.source_pmid IN ({placeholders})
        GROUP BY e_ds.id
        ORDER BY
          CASE COALESCE(e_ds.access_class, 'unknown')
            WHEN 'public' THEN 0
            WHEN 'private' THEN 1
            ELSE 2
          END,
          used_by_papers DESC
    """
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(pmids)).fetchall()
    out: list[dict[str, Any]] = []
    n_ex = max(1, int(config.V03_EXAMPLE_PMIDS))
    for r in rows:
        blob = r["pmid_blob"] or ""
        example = [p for p in str(blob).split(",") if p.strip()][:n_ex]
        out.append(
            {
                "dataset": r["dataset"],
                "access_class": (r["access_class"] or "unknown").lower(),
                "used_by_papers": int(r["used_by_papers"] or 0),
                "example_pmids": example,
            }
        )
    return out


def _compute_score(recommended: list[dict[str, Any]], topic_paper_cnt: int) -> float:
    if not recommended:
        return 0.0
    n_pub = min(len(recommended), int(config.V03_MAX_PUBLIC_FOR_SCORE))
    score = n_pub * float(config.V03_SCORE_PER_PUBLIC)
    if any(r.get("alias_hit") for r in recommended):
        score += float(config.V03_SCORE_ALIAS_BONUS)
    covered = sum(int(r.get("used_by_papers") or 0) for r in recommended)
    if topic_paper_cnt > 0:
        score += min(0.3, covered / max(topic_paper_cnt, 1) * 0.3)
    cap = float(config.V03_SCORE_COVERAGE_CAP)
    return round(min(cap, max(0.0, score)), 3)


def _status_and_gaps(
    *,
    topic_paper_cnt: int,
    recommended: list[dict[str, Any]],
    other: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    gaps: list[str] = []
    if topic_paper_cnt == 0:
        return "NONE", ["No literature match for focus/gap keyword"]

    if not recommended and not other:
        return "NONE", ["No Dataset entities linked via USES_DATASET in topic papers"]

    min_papers = int(config.V03_OK_MIN_PAPERS)
    if recommended:
        ok = any(
            bool(r.get("alias_hit")) or int(r.get("used_by_papers") or 0) >= min_papers
            for r in recommended
        )
        if ok:
            return "OK", gaps
        gaps.append(
            f"Public datasets found but coverage weak "
            f"(need alias hit or ≥{min_papers} papers per set)"
        )
        return "WEAK", gaps

    unknowns = [r for r in other if r.get("access_class") == "unknown"]
    privates = [r for r in other if r.get("access_class") == "private"]
    if unknowns:
        gaps.append("No confirmed public datasets; only unknown access_class candidates")
        return "WEAK", gaps
    if privates:
        gaps.append("Only private/in-house cohorts extracted for this topic")
        return "NONE", gaps
    return "NONE", ["No usable public datasets for this topic"]


def assess_public_datasets(keyword: str) -> dict[str, Any]:
    """Build V-03 public-dataset feasibility report for a focus/gap keyword."""
    kw = (keyword or "").strip()
    pmids, strategy = resolve_topic_pmids(kw)
    topic_paper_cnt = len(pmids)
    rows = _query_datasets_for_pmids(pmids)

    recommended: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for row in rows:
        ac = row["access_class"]
        entry = {
            "dataset": row["dataset"],
            "used_by_papers": row["used_by_papers"],
            "alias_hit": alias_hit(str(row["dataset"])),
            "example_pmids": row["example_pmids"],
        }
        if ac == "public":
            recommended.append(entry)
        else:
            other.append(
                {
                    "dataset": row["dataset"],
                    "access_class": ac,
                    "used_by_papers": row["used_by_papers"],
                }
            )

    status, gaps = _status_and_gaps(
        topic_paper_cnt=topic_paper_cnt,
        recommended=recommended,
        other=other,
    )
    score = _compute_score(recommended, topic_paper_cnt)
    roles = (
        ["external_validation", "pretrain_or_comparison"]
        if recommended
        else []
    )

    return {
        "description": "公开数据集可行性 (V-03)",
        "keyword": kw,
        "match_strategy": strategy,
        "topic_paper_cnt": topic_paper_cnt,
        "public_coverage_score": score,
        "status": status,
        "recommended_public": recommended,
        "other_datasets": other,
        "gaps": gaps,
        "roles_for_proposal": roles,
    }
