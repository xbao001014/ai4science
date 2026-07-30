"""Batch study-type relation signals for gap/hotspot rows."""
from __future__ import annotations

from typing import Any

from db.schema import get_conn


def count_surveys_by_method() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE COALESCE(r.status, 'active') = 'active'
              AND r.relation = 'SURVEYS_METHOD' AND e.type = 'Method'
            GROUP BY e.id
            """
        ).fetchall()
    return {str(r["name"]): int(r["cnt"]) for r in rows}


def count_covers_by_disease() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE COALESCE(r.status, 'active') = 'active'
              AND r.relation = 'COVERS_DISEASE' AND e.type = 'Disease'
            GROUP BY e.id
            """
        ).fetchall()
    return {str(r["name"]): int(r["cnt"]) for r in rows}


def annotate_study_type_rows(
    rows: list[dict[str, Any]],
    *,
    method_key: str = "method",
    disease_key: str = "disease",
) -> list[dict[str, Any]]:
    if not rows:
        return rows
    surveys = count_surveys_by_method()
    covers = count_covers_by_disease()
    for r in rows:
        m = str(r.get(method_key) or "")
        d = str(r.get(disease_key) or "")
        r["surveys_method_paper_cnt"] = int(surveys.get(m, 0))
        r["covers_disease_paper_cnt"] = int(covers.get(d, 0))
    return rows


def build_covered_gap_rows(
    method_names: list[str],
    cover_disease_names: list[str],
    applied_cooccur: dict[tuple[str, str], int],
    applied_pair_set: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in method_names:
        for d in cover_disease_names:
            key = (m, d)
            if key in applied_pair_set:
                continue
            if int(applied_cooccur.get(key, 0)) != 0:
                continue
            rows.append({
                "method": m,
                "disease": d,
                "paper_cnt": 0,
                "gap": "unexplored",
                "gap_kind": "covered",
            })
    rows = annotate_study_type_rows(rows)
    rows = [r for r in rows if int(r.get("covers_disease_paper_cnt") or 0) >= 1]
    rows.sort(
        key=lambda r: (
            -int(r.get("covers_disease_paper_cnt") or 0),
            -int(r.get("surveys_method_paper_cnt") or 0),
            str(r.get("method") or ""),
            str(r.get("disease") or ""),
        )
    )
    return rows
