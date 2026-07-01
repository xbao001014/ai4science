"""Limitation temporal profiles and heuristic gap-resolution signals."""
from __future__ import annotations

import json
from typing import Any

import config
from analysis.impact_scoring import aggregate_paper_impact
from db.schema import (
    get_conn,
    insert_limitation_resolution_signals,
    limitation_lifecycle_stats,
    upsert_limitation_temporal,
)


def corpus_midpoint() -> int:
    return (config.SEARCH_YEAR_START + config.SEARCH_YEAR_END) // 2


def recent_year_cutoff() -> int:
    return config.SEARCH_YEAR_END - config.GAP_RECENT_YEARS


def classify_temporal_status(
    first_year: int | None,
    last_year: int | None,
    paper_cnt: int,
    recent_cnt: int,
    recent_ratio: float,
) -> str:
    if not first_year or not last_year or paper_cnt <= 0:
        return "stable"
    cutoff = recent_year_cutoff()
    if first_year >= cutoff:
        return "emerging"
    if recent_cnt == 0 and last_year < cutoff:
        return "declining"
    if first_year < cutoff and recent_ratio >= config.GAP_PERSISTENT_RATIO:
        return "persistent"
    return "stable"


def _q(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _limitation_impact_by_id() -> dict[int, dict[str, Any]]:
    rows = _q(
        """
        SELECT r.object_id AS limitation_id,
               p.citation_count,
               p.year,
               j.impact_factor,
               j.quartile
        FROM relations r
        JOIN papers p ON r.source_pmid = p.pmid
        LEFT JOIN journals j ON p.journal_id = j.id
        WHERE r.relation = 'REPORTS_LIMITATION'
          AND p.year IS NOT NULL
        """
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["limitation_id"], []).append(row)
    return {
        limitation_id: aggregate_paper_impact(papers)
        for limitation_id, papers in grouped.items()
    }


def compute_limitation_temporal_profiles(
    focus: str | None = None,
) -> list[dict[str, Any]]:
    """Build limitation temporal rows from relations + papers (live compute)."""
    midpoint = corpus_midpoint()
    recent_cutoff = recent_year_cutoff()
    focus_sql = ""
    params: list[Any] = [midpoint, recent_cutoff]
    if focus:
        focus_sql = " AND LOWER(e.name) LIKE LOWER(?)"
        params.append(f"%{focus}%")

    base_rows = _q(
        f"""
        SELECT e.id AS limitation_id,
               e.name AS limitation_name,
               MIN(p.year) AS first_year,
               MAX(p.year) AS last_year,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               SUM(CASE WHEN r.polarity = 'asserted' THEN 1 ELSE 0 END) AS asserted_cnt,
               SUM(CASE WHEN r.polarity = 'hypothesized' THEN 1 ELSE 0 END) AS hypothesized_cnt,
               SUM(CASE WHEN p.year <= ? THEN 1 ELSE 0 END) AS early_cnt,
               SUM(CASE WHEN p.year >= ? THEN 1 ELSE 0 END) AS recent_cnt,
               GROUP_CONCAT(DISTINCT r.evidence_section) AS sections
        FROM relations r
        JOIN entities e ON r.object_id = e.id AND e.type = 'Limitation'
        JOIN papers p ON r.source_pmid = p.pmid
        WHERE r.relation = 'REPORTS_LIMITATION'
          AND p.year IS NOT NULL
          {focus_sql}
        GROUP BY e.id
        HAVING paper_cnt >= 1
        ORDER BY paper_cnt DESC
        """,
        tuple(params),
    )

    impact_map = _limitation_impact_by_id()
    profiles: list[dict[str, Any]] = []
    for row in base_rows:
        paper_cnt = int(row["paper_cnt"] or 0)
        recent_cnt = int(row["recent_cnt"] or 0)
        recent_ratio = round(recent_cnt / max(paper_cnt, 1), 3)
        first_year = row.get("first_year")
        last_year = row.get("last_year")
        status = classify_temporal_status(
            first_year, last_year, paper_cnt, recent_cnt, recent_ratio
        )
        impact = impact_map.get(
            row["limitation_id"],
            aggregate_paper_impact([]),
        )
        year_span = (last_year - first_year) if first_year and last_year else 0
        profiles.append({
            "limitation_id": row["limitation_id"],
            "limitation_name": row["limitation_name"],
            "limitation": row["limitation_name"],
            "first_year": first_year,
            "last_year": last_year,
            "year_span": year_span,
            "paper_cnt": paper_cnt,
            "asserted_cnt": int(row["asserted_cnt"] or 0),
            "hypothesized_cnt": int(row["hypothesized_cnt"] or 0),
            "early_cnt": int(row["early_cnt"] or 0),
            "recent_cnt": recent_cnt,
            "recent_ratio": recent_ratio,
            "sections": row.get("sections") or "",
            "temporal_status": status,
            "avg_cite": impact["avg_cite"],
            "avg_cite_per_year": impact["avg_cite_per_year"],
            "impact_tier": impact["impact_tier"],
        })
    return profiles


class _FollowupIndex:
    """In-memory index to avoid per-limitation SQL in batch runs."""

    def __init__(self) -> None:
        self._paper_entities: dict[str, dict[str, set[str]]] = {}
        self._limitation_anchors: dict[int, list[tuple[str, int]]] = {}
        self._followups_by_disease: dict[str, list[tuple[int, str]]] = {}
        self._load()

    def _load(self) -> None:
        entity_rows = _q(
            """
            SELECT r.source_pmid, e.name, e.type
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type IN ('Disease', 'Task', 'Method')
            """
        )
        for row in entity_rows:
            bucket = self._paper_entities.setdefault(
                row["source_pmid"], {"Disease": set(), "Task": set(), "Method": set()}
            )
            bucket[row["type"]].add(row["name"])

        anchor_rows = _q(
            """
            SELECT r.object_id AS limitation_id, p.pmid, p.year
            FROM relations r
            JOIN papers p ON r.source_pmid = p.pmid
            WHERE r.relation = 'REPORTS_LIMITATION'
              AND p.year IS NOT NULL
            """
        )
        for row in anchor_rows:
            self._limitation_anchors.setdefault(row["limitation_id"], []).append(
                (row["pmid"], int(row["year"]))
            )

        followup_rows = _q(
            """
            SELECT DISTINCT p.pmid, p.year, ed.name AS disease
            FROM papers p
            JOIN relations rd ON rd.source_pmid = p.pmid
            JOIN entities ed ON rd.object_id = ed.id AND ed.type = 'Disease'
            WHERE p.year IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM relations rm
                  JOIN entities em ON rm.object_id = em.id
                  WHERE rm.source_pmid = p.pmid
                    AND em.type IN ('Task', 'Method')
                    AND rm.evidence_section IN ('results', 'methods')
              )
            ORDER BY p.year ASC
            """
        )
        for row in followup_rows:
            self._followups_by_disease.setdefault(row["disease"], []).append(
                (int(row["year"]), row["pmid"])
            )

    def anchor_entities(
        self, limitation_id: int, first_year: int
    ) -> dict[str, set[str]]:
        diseases: set[str] = set()
        tasks: set[str] = set()
        methods: set[str] = set()
        for pmid, year in self._limitation_anchors.get(limitation_id, []):
            if year > first_year + 1:
                continue
            ents = self._paper_entities.get(pmid, {})
            diseases |= ents.get("Disease", set())
            tasks |= ents.get("Task", set())
            methods |= ents.get("Method", set())
        return {"Disease": diseases, "Task": tasks, "Method": methods}

    def followups(
        self,
        diseases: set[str],
        tasks: set[str],
        methods: set[str],
        after_year: int,
    ) -> list[tuple[int, str]]:
        if not diseases or (not tasks and not methods):
            return []
        seen: set[str] = set()
        matches: list[tuple[int, str]] = []
        for disease in diseases:
            for year, pmid in self._followups_by_disease.get(disease, []):
                if year <= after_year or pmid in seen:
                    continue
                seen.add(pmid)
                matches.append((year, pmid))
        matches.sort(key=lambda item: item[0])
        return matches


_FOLLOWUP_INDEX: _FollowupIndex | None = None


def _get_followup_index() -> _FollowupIndex:
    global _FOLLOWUP_INDEX
    if _FOLLOWUP_INDEX is None:
        _FOLLOWUP_INDEX = _FollowupIndex()
    return _FOLLOWUP_INDEX


def reset_followup_index() -> None:
    global _FOLLOWUP_INDEX
    _FOLLOWUP_INDEX = None


def compute_resolution_signal(
    profile: dict[str, Any],
    *,
    index: _FollowupIndex | None = None,
) -> dict[str, Any]:
    """Heuristic follow-up signal for one limitation profile."""
    limitation_id = profile["limitation_id"]
    first_year = profile.get("first_year")
    last_year = profile.get("last_year")
    if not first_year:
        return {
            "limitation_id": limitation_id,
            "limitation_name": profile.get("limitation_name", ""),
            "followup_paper_cnt": 0,
            "first_followup_year": None,
            "resolution_signal": "none",
            "shared_entities": {"diseases": [], "tasks": [], "methods": []},
        }

    idx = index or _get_followup_index()
    ents = idx.anchor_entities(limitation_id, first_year)
    diseases = ents.get("Disease", set())
    tasks = ents.get("Task", set())
    methods = ents.get("Method", set())

    followup_matches = idx.followups(diseases, tasks, methods, after_year=first_year)
    followup_paper_cnt = len(followup_matches)
    first_followup_year = followup_matches[0][0] if followup_matches else None

    if followup_paper_cnt >= config.GAP_RESOLUTION_MIN_FOLLOWUP:
        if first_followup_year and last_year and first_followup_year > last_year:
            resolution_signal = "moderate"
        elif first_followup_year and first_followup_year > first_year:
            resolution_signal = "moderate"
        else:
            resolution_signal = "weak"
    elif followup_paper_cnt == 1:
        resolution_signal = "weak"
    else:
        resolution_signal = "none"

    return {
        "limitation_id": limitation_id,
        "limitation_name": profile.get("limitation_name", ""),
        "followup_paper_cnt": followup_paper_cnt,
        "first_followup_year": first_followup_year,
        "resolution_signal": resolution_signal,
        "shared_entities": {
            "diseases": sorted(diseases),
            "tasks": sorted(tasks),
            "methods": sorted(methods),
        },
    }


def compute_limitation_gap_status(
    focus: str | None = None,
) -> list[dict[str, Any]]:
    reset_followup_index()
    index = _get_followup_index()
    profiles = compute_limitation_temporal_profiles(focus=focus)
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        signal = compute_resolution_signal(profile, index=index)
        rows.append({**profile, **signal})
    rows.sort(
        key=lambda r: (
            {"moderate": 3, "weak": 2, "none": 1}.get(r["resolution_signal"], 0),
            r.get("paper_cnt", 0),
        ),
        reverse=True,
    )
    return rows[: config.TOOL_TOP_N]


def compute_resolution_signal_rows(
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build DB rows for limitation_resolution_signals."""
    reset_followup_index()
    index = _get_followup_index()
    db_rows: list[dict[str, Any]] = []
    for profile in profiles:
        limitation_id = profile["limitation_id"]
        signal = compute_resolution_signal(profile, index=index)
        shared = signal.get("shared_entities") or {}
        shared_json = json.dumps(shared, ensure_ascii=False)

        if signal["resolution_signal"] in ("weak", "moderate"):
            confidence = 0.7 if signal["resolution_signal"] == "moderate" else 0.45
            db_rows.append({
                "limitation_id": limitation_id,
                "signal_type": "topic_followup",
                "anchor_pmid": None,
                "followup_pmid": None,
                "anchor_year": profile.get("first_year"),
                "followup_year": signal.get("first_followup_year"),
                "shared_entities": shared_json,
                "confidence": confidence,
            })

        if profile.get("temporal_status") == "declining":
            db_rows.append({
                "limitation_id": limitation_id,
                "signal_type": "mention_decline",
                "anchor_pmid": None,
                "followup_pmid": None,
                "anchor_year": profile.get("first_year"),
                "followup_year": profile.get("last_year"),
                "shared_entities": shared_json,
                "confidence": 0.55,
            })

    return db_rows


def compute_combo_gap_temporal(focus: str | None = None) -> list[dict[str, Any]]:
    """Method×disease combos with temporal gap_phase."""
    mf = ""
    df = ""
    if focus:
        mf = f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"
        df = mf

    top_methods = _q(f"""
        SELECT e.name
        FROM relations r JOIN entities e ON r.object_id=e.id
        WHERE e.type='Method' AND r.relation='APPLIES_METHOD' {mf}
        GROUP BY e.id ORDER BY COUNT(*) DESC LIMIT {config.TOOL_TOP_N}
    """)
    top_diseases = _q(f"""
        SELECT e.name
        FROM relations r JOIN entities e ON r.object_id=e.id
        WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE' {df}
        GROUP BY e.id ORDER BY COUNT(*) DESC LIMIT {config.TOOL_TOP_N}
    """)
    method_names = [r["name"] for r in top_methods]
    disease_names = [r["name"] for r in top_diseases]
    if not method_names or not disease_names:
        return []

    combo_rows = _q("""
        WITH pm AS (
            SELECT r.source_pmid, e.name AS method
            FROM relations r JOIN entities e ON r.object_id=e.id
            WHERE e.type='Method' AND r.relation='APPLIES_METHOD'
        ),
        pd AS (
            SELECT r.source_pmid, e.name AS disease
            FROM relations r JOIN entities e ON r.object_id=e.id
            WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE'
        )
        SELECT pm.method, pd.disease, p.year
        FROM pm
        JOIN pd ON pm.source_pmid = pd.source_pmid
        JOIN papers p ON p.pmid = pm.source_pmid
        WHERE p.year IS NOT NULL
    """)
    from collections import defaultdict

    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in combo_rows:
        buckets[(row["method"], row["disease"])].append(int(row["year"]))

    recent_cutoff = recent_year_cutoff()
    gaps: list[dict[str, Any]] = []
    for method in method_names:
        for disease in disease_names:
            years = buckets.get((method, disease), [])
            paper_cnt = len(years)
            first_paper_year = min(years) if years else None
            last_paper_year = max(years) if years else None
            recent_cnt = sum(1 for y in years if y >= recent_cutoff)

            if paper_cnt == 0:
                gap_phase = "unexplored"
            elif recent_cnt == 0 and last_paper_year and last_paper_year < recent_cutoff:
                gap_phase = "dormant"
            elif paper_cnt <= 2 and last_paper_year and last_paper_year >= recent_cutoff:
                gap_phase = "nascent"
            else:
                gap_phase = "active"

            gaps.append({
                "method": method,
                "disease": disease,
                "paper_cnt": paper_cnt,
                "first_paper_year": first_paper_year,
                "last_paper_year": last_paper_year,
                "recent_cnt": recent_cnt,
                "gap_phase": gap_phase,
            })

    gaps.sort(key=lambda g: (g["gap_phase"] != "unexplored", g["paper_cnt"], g["method"]))
    return gaps[:40]


def run_gap_lifecycle(*, force: bool = True) -> dict[str, Any]:
    """Batch compute and persist limitation temporal + resolution signals."""
    reset_followup_index()
    with get_conn() as conn:
        if force:
            conn.execute("DELETE FROM limitation_resolution_signals")
            conn.execute("DELETE FROM limitation_temporal")
        else:
            conn.execute("DELETE FROM limitation_resolution_signals")

    profiles = compute_limitation_temporal_profiles()
    upsert_limitation_temporal(profiles)
    resolution_rows = compute_resolution_signal_rows(profiles)
    insert_limitation_resolution_signals(resolution_rows)

    stats = limitation_lifecycle_stats()
    stats["profiles_computed"] = len(profiles)
    stats["signals_computed"] = len(resolution_rows)
    return stats
