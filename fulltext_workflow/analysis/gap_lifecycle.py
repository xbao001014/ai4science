"""Limitation temporal profiles and heuristic gap-resolution signals."""
from __future__ import annotations

import bisect
import json
import time
from typing import Any

import config
from analysis.impact_scoring import aggregate_paper_impact
from db.schema import (
    get_conn,
    insert_limitation_resolution_signals,
    limitation_lifecycle_stats,
    upsert_limitation_temporal,
)


def _log(msg: str) -> None:
    print(f"[Gap-Lifecycle] {msg}", flush=True)


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
    from analysis.focus_filter import focus_pmid_in_clause, normalize_focus

    f = normalize_focus(focus)
    focus_sql = focus_pmid_in_clause("r.source_pmid", f)
    params: list[Any] = [midpoint, recent_cutoff]

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


def _load_paper_entities(pmids: set[str]) -> dict[str, dict[str, set[str]]]:
    if not pmids:
        return {}
    out: dict[str, dict[str, set[str]]] = {}
    pmid_list = list(pmids)
    chunk = 900
    for start in range(0, len(pmid_list), chunk):
        batch = pmid_list[start : start + chunk]
        placeholders = ",".join("?" * len(batch))
        rows = _q(
            f"""
            SELECT r.source_pmid, e.name, e.type
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE r.source_pmid IN ({placeholders})
              AND e.type IN ('Disease', 'Task', 'Method')
            """,
            tuple(batch),
        )
        for row in rows:
            bucket = out.setdefault(
                row["source_pmid"], {"Disease": set(), "Task": set(), "Method": set()}
            )
            bucket[row["type"]].add(row["name"])
    return out


class _FollowupIndex:
    """In-memory index to avoid per-limitation SQL in batch runs."""

    def __init__(self) -> None:
        self._paper_entities: dict[str, dict[str, set[str]]] = {}
        self._limitation_anchors: dict[int, list[tuple[str, int]]] = {}
        self._followups_by_disease: dict[str, list[tuple[int, str]]] = {}
        self._followup_years: dict[str, list[int]] = {}
        self._anchor_cache: dict[tuple[int, int], dict[str, set[str]]] = {}
        self._load()

    def _load(self) -> None:
        anchor_rows = _q(
            """
            SELECT r.object_id AS limitation_id, p.pmid, p.year
            FROM relations r
            JOIN papers p ON r.source_pmid = p.pmid
            WHERE r.relation = 'REPORTS_LIMITATION'
              AND p.year IS NOT NULL
            """
        )
        anchor_pmids: set[str] = set()
        for row in anchor_rows:
            pmid = row["pmid"]
            anchor_pmids.add(pmid)
            self._limitation_anchors.setdefault(row["limitation_id"], []).append(
                (pmid, int(row["year"]))
            )

        self._paper_entities = _load_paper_entities(anchor_pmids)

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
            disease = row["disease"]
            self._followups_by_disease.setdefault(disease, []).append(
                (int(row["year"]), row["pmid"])
            )
        for disease, items in self._followups_by_disease.items():
            self._followup_years[disease] = [year for year, _ in items]

    def anchor_entities(
        self, limitation_id: int, first_year: int
    ) -> dict[str, set[str]]:
        key = (limitation_id, first_year)
        cached = self._anchor_cache.get(key)
        if cached is not None:
            return cached

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
        result = {"Disease": diseases, "Task": tasks, "Method": methods}
        self._anchor_cache[key] = result
        return result

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
            items = self._followups_by_disease.get(disease)
            if not items:
                continue
            years = self._followup_years.get(disease, [])
            idx = bisect.bisect_right(years, after_year)
            for year, pmid in items[idx:]:
                if pmid in seen:
                    continue
                seen.add(pmid)
                matches.append((year, pmid))
        matches.sort(key=lambda item: item[0])
        return matches


_FOLLOWUP_INDEX: _FollowupIndex | None = None
_BULK_FOLLOWUP_STATS_CACHE: dict[int, dict[str, Any]] | None = None


def _get_followup_index() -> _FollowupIndex:
    global _FOLLOWUP_INDEX
    if _FOLLOWUP_INDEX is None:
        _FOLLOWUP_INDEX = _FollowupIndex()
    return _FOLLOWUP_INDEX


def reset_followup_index() -> None:
    global _FOLLOWUP_INDEX, _BULK_FOLLOWUP_STATS_CACHE
    _FOLLOWUP_INDEX = None
    _BULK_FOLLOWUP_STATS_CACHE = None


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


def _profiles_for_resolution(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = config.GAP_LIFECYCLE_RESOLUTION_STATUSES
    if not allowed:
        return profiles
    return [p for p in profiles if p.get("temporal_status") in allowed]


def compute_limitation_gap_status(
    focus: str | None = None,
) -> list[dict[str, Any]]:
    """Temporal + resolution rows for agent tools (bulk follow-up stats, not per-row scan)."""
    from analysis.focus_filter import normalize_focus
    from db.schema import get_limitation_temporal_rows

    f = normalize_focus(focus)
    if f:
        profiles = compute_limitation_temporal_profiles(focus=f)
    else:
        cached = get_limitation_temporal_rows(
            focus=None,
            temporal_statuses=sorted(config.GAP_LIFECYCLE_RESOLUTION_STATUSES),
        )
        profiles = cached if cached else compute_limitation_temporal_profiles(focus=None)

    targets = _profiles_for_resolution(profiles)
    stats_map = _bulk_followup_stats()
    rows: list[dict[str, Any]] = []
    for profile in targets:
        stat = stats_map.get(profile["limitation_id"], {})
        followup_cnt = int(stat.get("followup_paper_cnt") or 0)
        first_fu = stat.get("first_followup_year")
        resolution_signal = _classify_resolution_signal(
            profile.get("first_year"),
            profile.get("last_year"),
            followup_cnt,
            first_fu,
        )
        rows.append({
            **profile,
            "followup_paper_cnt": followup_cnt,
            "first_followup_year": first_fu,
            "resolution_signal": resolution_signal,
        })

    rows.sort(
        key=lambda r: (
            {"moderate": 3, "weak": 2, "none": 1}.get(r["resolution_signal"], 0),
            r.get("paper_cnt", 0),
        ),
        reverse=True,
    )
    return rows[: config.TOOL_TOP_N]


def _resolution_status_filter_sql(alias: str = "lt") -> str:
    allowed = config.GAP_LIFECYCLE_RESOLUTION_STATUSES
    if not allowed:
        return ""
    placeholders = ",".join("?" * len(allowed))
    return f" AND {alias}.temporal_status IN ({placeholders})"


def _load_followup_by_disease() -> tuple[
    dict[str, list[tuple[int, str]]], dict[str, list[int]]
]:
    """Preload follow-up papers grouped by disease (one scan)."""
    rows = _q(
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
        ORDER BY ed.name, p.year, p.pmid
        """
    )
    by_disease: dict[str, list[tuple[int, str]]] = {}
    years_map: dict[str, list[int]] = {}
    for row in rows:
        disease = row["disease"]
        by_disease.setdefault(disease, []).append((int(row["year"]), row["pmid"]))
    for disease, items in by_disease.items():
        years_map[disease] = [year for year, _ in items]
    return by_disease, years_map


def _load_anchor_diseases_by_limitation() -> dict[int, tuple[int, int | None, set[str]]]:
    """limitation_id -> (first_year, last_year, diseases on early anchor papers)."""
    allowed = tuple(config.GAP_LIFECYCLE_RESOLUTION_STATUSES)
    status_filter = _resolution_status_filter_sql("lt")
    params: list[Any] = list(allowed) if allowed else []

    rows = _q(
        f"""
        SELECT lt.limitation_id,
               lt.first_year,
               lt.last_year,
               ed.name AS disease
        FROM limitation_temporal lt
        JOIN relations r ON r.object_id = lt.limitation_id
            AND r.relation = 'REPORTS_LIMITATION'
        JOIN papers p ON p.pmid = r.source_pmid
        JOIN relations rd ON rd.source_pmid = r.source_pmid
        JOIN entities ed ON rd.object_id = ed.id AND ed.type = 'Disease'
        WHERE p.year <= lt.first_year + 1
          {status_filter}
          AND EXISTS (
              SELECT 1 FROM relations rm
              JOIN entities em ON rm.object_id = em.id
              WHERE rm.source_pmid = r.source_pmid
                AND em.type IN ('Method', 'Task')
          )
        """,
        tuple(params),
    )
    out: dict[int, tuple[int, int | None, set[str]]] = {}
    for row in rows:
        lid = int(row["limitation_id"])
        if lid not in out:
            out[lid] = (int(row["first_year"]), row.get("last_year"), set())
        out[lid][2].add(row["disease"])
    return out


def _followup_stats_merged(
    diseases: set[str],
    after_year: int,
    followup_by_disease: dict[str, list[tuple[int, str]]],
    followup_years: dict[str, list[int]],
) -> tuple[int, int | None]:
    """Count all distinct follow-up pmids after after_year and earliest matching year."""
    import heapq

    if not diseases:
        return 0, None

    heap: list[tuple[int, str, str, int]] = []
    for disease in diseases:
        items = followup_by_disease.get(disease)
        if not items:
            continue
        years = followup_years.get(disease, [])
        idx = bisect.bisect_right(years, after_year)
        if idx < len(items):
            year, pmid = items[idx]
            heapq.heappush(heap, (year, pmid, disease, idx + 1))

    seen: set[str] = set()
    first_year: int | None = None

    while heap:
        year, pmid, disease, next_idx = heapq.heappop(heap)
        items = followup_by_disease[disease]

        if next_idx < len(items):
            ny, np = items[next_idx]
            heapq.heappush(heap, (ny, np, disease, next_idx + 1))

        if pmid in seen:
            continue
        seen.add(pmid)
        if first_year is None or year < first_year:
            first_year = year

    return len(seen), first_year


def _bulk_followup_stats(
    *, verbose: bool = False, use_cache: bool = True
) -> dict[int, dict[str, Any]]:
    """Multi-step: preload followup index + anchor diseases, aggregate in Python."""
    global _BULK_FOLLOWUP_STATS_CACHE
    if use_cache and _BULK_FOLLOWUP_STATS_CACHE is not None:
        return _BULK_FOLLOWUP_STATS_CACHE

    t0 = time.time()
    if verbose:
        _log("  Loading follow-up papers by disease…")
    followup_by_disease, followup_years = _load_followup_by_disease()
    if verbose:
        _log(
            f"  {sum(len(v) for v in followup_by_disease.values())} rows, "
            f"{len(followup_by_disease)} diseases in {time.time() - t0:.1f}s"
        )

    t1 = time.time()
    if verbose:
        _log("  Loading anchor diseases for eligible limitations…")
    anchors = _load_anchor_diseases_by_limitation()
    if verbose:
        _log(f"  {len(anchors)} limitations in {time.time() - t1:.1f}s")

    t2 = time.time()
    if verbose:
        _log("  Aggregating follow-up stats…")
    result: dict[int, dict[str, Any]] = {}
    for i, (limitation_id, (first_year, last_year, diseases)) in enumerate(
        anchors.items(), start=1
    ):
        cnt, first_fu = _followup_stats_merged(
            diseases, first_year, followup_by_disease, followup_years
        )
        result[limitation_id] = {
            "limitation_id": limitation_id,
            "first_year": first_year,
            "last_year": last_year,
            "followup_paper_cnt": cnt,
            "first_followup_year": first_fu,
        }
        if verbose and i % 1000 == 0:
            _log(f"  Aggregated {i}/{len(anchors)}")

    if verbose:
        _log(f"  Aggregation done in {time.time() - t2:.1f}s")
    if use_cache:
        _BULK_FOLLOWUP_STATS_CACHE = result
    return result


def _classify_resolution_signal(
    first_year: int | None,
    last_year: int | None,
    followup_paper_cnt: int,
    first_followup_year: int | None,
) -> str:
    if followup_paper_cnt >= config.GAP_RESOLUTION_MIN_FOLLOWUP:
        if first_followup_year and last_year and first_followup_year > last_year:
            return "moderate"
        if first_followup_year and first_year and first_followup_year > first_year:
            return "moderate"
        return "weak"
    if followup_paper_cnt == 1:
        return "weak"
    return "none"


def compute_resolution_signal_rows(
    profiles: list[dict[str, Any]],
    *,
    verbose: bool = False,
    use_bulk_sql: bool = True,
) -> list[dict[str, Any]]:
    """Build DB rows for limitation_resolution_signals."""
    targets = _profiles_for_resolution(profiles)
    if verbose:
        skipped = len(profiles) - len(targets)
        _log(
            f"Resolution targets: {len(targets)} "
            f"(skipped {skipped} by status filter "
            f"{sorted(config.GAP_LIFECYCLE_RESOLUTION_STATUSES)})"
        )

    db_rows: list[dict[str, Any]] = []
    empty_shared = json.dumps({"diseases": [], "tasks": [], "methods": []})

    if use_bulk_sql:
        if verbose:
            _log("  Follow-up resolution (indexed)…")
        t0 = time.time()
        stats_map = _bulk_followup_stats(verbose=verbose)
        if verbose:
            _log(f"  Resolution stats ready in {time.time() - t0:.1f}s")

        for profile in targets:
            limitation_id = profile["limitation_id"]
            row = stats_map.get(limitation_id, {})
            followup_cnt = int(row.get("followup_paper_cnt") or 0)
            first_fu = row.get("first_followup_year")
            signal = _classify_resolution_signal(
                profile.get("first_year"),
                profile.get("last_year"),
                followup_cnt,
                first_fu,
            )

            if signal in ("weak", "moderate"):
                db_rows.append({
                    "limitation_id": limitation_id,
                    "signal_type": "topic_followup",
                    "anchor_pmid": None,
                    "followup_pmid": None,
                    "anchor_year": profile.get("first_year"),
                    "followup_year": first_fu,
                    "shared_entities": empty_shared,
                    "confidence": 0.7 if signal == "moderate" else 0.45,
                })

            if profile.get("temporal_status") == "declining":
                db_rows.append({
                    "limitation_id": limitation_id,
                    "signal_type": "mention_decline",
                    "anchor_pmid": None,
                    "followup_pmid": None,
                    "anchor_year": profile.get("first_year"),
                    "followup_year": profile.get("last_year"),
                    "shared_entities": empty_shared,
                    "confidence": 0.55,
                })
        return db_rows

    reset_followup_index()
    index = _get_followup_index()
    total = len(targets)
    for i, profile in enumerate(targets, start=1):
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

        if verbose and (i % 500 == 0 or i == total):
            _log(f"Resolution progress: {i}/{total}")

    return db_rows


def compute_combo_gap_temporal(focus: str | None = None) -> list[dict[str, Any]]:
    """Method×disease combos with temporal gap_phase."""
    from analysis.focus_filter import (
        focus_pmid_in_clause,
        focus_sql_clause,
        normalize_focus,
    )

    f = normalize_focus(focus)
    mf = focus_pmid_in_clause("r.source_pmid", f) if f else ""
    df = focus_sql_clause("e.name", f) if f else ""

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


def run_gap_lifecycle(
    *,
    force: bool = True,
    temporal_only: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Batch compute and persist limitation temporal + resolution signals."""
    t0 = time.time()
    reset_followup_index()

    if verbose:
        _log("Clearing old lifecycle rows…")
    with get_conn() as conn:
        conn.execute("PRAGMA synchronous=NORMAL")
        if force:
            conn.execute("DELETE FROM limitation_resolution_signals")
            conn.execute("DELETE FROM limitation_temporal")
        else:
            conn.execute("DELETE FROM limitation_resolution_signals")

    if verbose:
        _log("Computing temporal profiles…")
    profiles = compute_limitation_temporal_profiles()
    if verbose:
        _log(f"  {len(profiles)} profiles in {time.time() - t0:.1f}s")

    def _progress(done: int, total: int) -> None:
        if verbose:
            _log(f"  Upsert progress: {done}/{total}")

    t1 = time.time()
    if verbose:
        _log("Writing limitation_temporal…")
    upsert_limitation_temporal(profiles, on_progress=_progress)
    if verbose:
        _log(f"  Done in {time.time() - t1:.1f}s")

    resolution_rows: list[dict[str, Any]] = []
    if not temporal_only:
        t2 = time.time()
        if verbose:
            _log("Computing resolution signals…")
        resolution_rows = compute_resolution_signal_rows(profiles, verbose=verbose)
        if verbose:
            _log(f"  {len(resolution_rows)} signals in {time.time() - t2:.1f}s")

        t3 = time.time()
        if verbose:
            _log("Writing limitation_resolution_signals…")
        insert_limitation_resolution_signals(resolution_rows, on_progress=_progress)
        if verbose:
            _log(f"  Done in {time.time() - t3:.1f}s")
    elif verbose:
        _log("Skipped resolution (--temporal-only)")

    stats = limitation_lifecycle_stats()
    stats["profiles_computed"] = len(profiles)
    stats["signals_computed"] = len(resolution_rows)
    stats["elapsed_seconds"] = round(time.time() - t0, 1)
    if verbose:
        _log(f"Finished in {stats['elapsed_seconds']}s")
    return stats
