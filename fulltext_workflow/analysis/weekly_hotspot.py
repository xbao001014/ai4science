"""Weekly research hotspot detection from recent publication dates."""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import config
from analysis.impact_scoring import literature_gap_points, norm_if
from analysis.method_maturity import (
    annotate_method_rows,
    classify_method_maturity,
    context_novelty_bonus,
    corpus_applies_method_counts_canonical,
    maturity_penalty,
    nascent_bonus,
)
from analysis.method_role import annotate_method_role, load_method_roles
from analysis.method_synonyms import resolve_method_canonical
from db.schema import (
    get_conn,
    get_weekly_hotspot_snapshots,
    list_weekly_hotspot_weeks,
    replace_weekly_hotspot_snapshots,
    upsert_weekly_hotspot_run,
)
from extractor.entity_normalize import is_low_value_method

# Main boards require at least month-level PubMed dates (折中).
_ELIGIBLE_PRECISION = ("day", "month")

# Task bridges are stronger when a paper demonstrates the full method-disease-task
# combination, rather than only linking the method and disease through task evidence
# in different papers.
_BRIDGE_BONUS_SAME = 2.0
_BRIDGE_BONUS_CROSS = 1.0

# Uncapped pool for new_methods: emerging_score pre-slice must not drop nascent rows.
_NEW_METHODS_POOL_UNCAPPED = 1_000_000


def _q(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def week_id(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def previous_week_id(wid: str | None = None) -> str:
    current = wid or week_id()
    year_s, week_s = current.split("-W")
    dt = datetime.fromisocalendar(int(year_s), int(week_s), 1) - timedelta(weeks=1)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def emerging_score(
    recent_cnt: int,
    prior_cnt: int,
    avg_cite: float,
    avg_cpy: float,
    avg_if: float,
) -> float:
    if recent_cnt <= 0:
        return 0.0
    velocity = (recent_cnt - prior_cnt) / max(prior_cnt, 1)
    raw = (
        0.4 * math.log1p(recent_cnt)
        + 0.3 * max(0.0, velocity)
        + 0.2 * math.log1p(avg_cpy)
        + 0.1 * norm_if(avg_if)
    )
    return round(raw, 3)


def _window_params(window_days: int, prior_days: int) -> tuple[str, str, str]:
    recent_start = f"-{window_days} days"
    prior_start = f"-{window_days + prior_days} days"
    return recent_start, prior_start, recent_start


def _eligible_pub_predicate(alias: str = "p") -> str:
    """SQL fragment: paper has usable pub_date for weekly windows."""
    return (
        f"{alias}.date_precision IN ('day', 'month') "
        f"AND {alias}.pub_date IS NOT NULL AND trim({alias}.pub_date) != ''"
    )


def _pub_date_not_future(alias: str = "p") -> str:
    """Exclude future-dated records (ahead-of-print / bad pub_date)."""
    return f"date({alias}.pub_date) <= date('now')"


def _window_pub_predicate(alias: str = "p") -> str:
    """Eligible pub_date within [now-N, now] publication windows."""
    return f"{_eligible_pub_predicate(alias)} AND {_pub_date_not_future(alias)}"


def count_window_papers(window_days: int) -> int:
    """Count papers with eligible pub_date in the recent publication window."""
    recent_start, _, _ = _window_params(window_days, 0)
    row = _q(
        f"""
        SELECT COUNT(*) AS n FROM papers p
        WHERE {_window_pub_predicate('p')}
          AND date(p.pub_date) >= date('now', ?)
        """,
        (recent_start,),
    )
    return int(row[0]["n"]) if row else 0


def count_excluded_future_pub_dates(window_days: int) -> int:
    """Eligible day/month papers in-window by lower bound but pub_date > today."""
    recent_start, _, _ = _window_params(window_days, 0)
    row = _q(
        f"""
        SELECT COUNT(*) AS n FROM papers p
        WHERE {_eligible_pub_predicate('p')}
          AND date(p.pub_date) >= date('now', ?)
          AND date(p.pub_date) > date('now')
        """,
        (recent_start,),
    )
    return int(row[0]["n"]) if row else 0


def count_excluded_low_precision(window_days: int) -> int:
    """Papers whose pub_date falls in-window but precision is year/unknown."""
    recent_start, _, _ = _window_params(window_days, 0)
    row = _q(
        """
        SELECT COUNT(*) AS n FROM papers p
        WHERE p.pub_date IS NOT NULL AND trim(p.pub_date) != ''
          AND date(p.pub_date) >= date('now', ?)
          AND COALESCE(p.date_precision, '') NOT IN ('day', 'month')
        """,
        (recent_start,),
    )
    return int(row[0]["n"] if row else 0)


# Backward-compatible alias (old name meant ingest count).
count_ingested_papers = count_window_papers


def _enrich_entity_rows(rows: list[dict]) -> list[dict]:
    for row in rows:
        recent = int(row.get("recent_cnt") or 0)
        prior = int(row.get("prior_cnt") or 0)
        avg_cite = float(row.get("avg_cite") or 0)
        avg_if = float(row.get("avg_if") or 0)
        avg_cpy = float(row.get("avg_cpy") or avg_cite)
        row["velocity"] = round((recent - prior) / max(prior, 1), 2)
        row["emerging_score"] = emerging_score(recent, prior, avg_cite, avg_cpy, avg_if)
    rows.sort(key=lambda r: r["emerging_score"], reverse=True)
    return rows


def _compute_emerging_method_entities(
    *,
    recent_start: str,
    prior_start: str,
    prior_end: str,
    min_recent: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Aggregate applied-Method edges by canonical, counting distinct PMIDs."""
    window_pub = _window_pub_predicate("p")
    edge_rows = _q(
        f"""
        WITH recent_pmids AS (
            SELECT COALESCE(p.source_key,p.pmid) AS pmid FROM papers p
            WHERE {window_pub}
              AND date(p.pub_date) >= date('now', ?)
        ),
        prior_pmids AS (
            SELECT COALESCE(p.source_key,p.pmid) AS pmid FROM papers p
            WHERE {window_pub}
              AND date(p.pub_date) >= date('now', ?)
              AND date(p.pub_date) < date('now', ?)
        )
        SELECT e.name, r.source_pmid AS pmid,
               r.source_pmid IN (SELECT pmid FROM recent_pmids) AS in_recent,
               r.source_pmid IN (SELECT pmid FROM prior_pmids) AS in_prior,
               COALESCE(p.citation_count, 0) AS cite,
               1.0 * COALESCE(p.citation_count, 0)
                   / MAX(2026 - COALESCE(p.year, ?), 1) AS cpy,
               COALESCE(j.impact_factor, 0) AS impact_factor
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        JOIN papers p ON p.source_key = r.source_pmid
          OR (p.source_key IS NULL AND p.pmid = r.source_pmid)
        LEFT JOIN journals j ON p.journal_id = j.id
        WHERE e.type = 'Method'
          AND r.relation = 'APPLIES_METHOD'
          AND COALESCE(r.status, 'active') = 'active'
          AND (
              r.source_pmid IN (SELECT pmid FROM recent_pmids)
              OR r.source_pmid IN (SELECT pmid FROM prior_pmids)
          )
        """,
        (recent_start, prior_start, prior_end, config.SEARCH_YEAR_END),
    )
    buckets: dict[str, dict[str, Any]] = {}
    for edge in edge_rows:
        raw_name = str(edge["name"])
        if is_low_value_method(raw_name):
            continue
        canonical = resolve_method_canonical(raw_name)
        if is_low_value_method(canonical):
            continue
        bucket = buckets.setdefault(
            canonical,
            {"recent_pmids": set(), "prior_pmids": set(), "aliases": set(), "metrics": {}},
        )
        bucket["aliases"].add(raw_name)
        pmid = str(edge["pmid"])
        if edge["in_recent"]:
            bucket["recent_pmids"].add(pmid)
            bucket["metrics"][pmid] = (
                float(edge["cite"] or 0),
                float(edge["cpy"] or 0),
                float(edge["impact_factor"] or 0),
            )
        if edge["in_prior"]:
            bucket["prior_pmids"].add(pmid)

    rows: list[dict[str, Any]] = []
    for name, bucket in buckets.items():
        recent_pmids = bucket["recent_pmids"]
        if len(recent_pmids) < min_recent:
            continue
        metrics = list(bucket["metrics"].values())
        if not metrics:
            continue
        aliases = sorted(bucket["aliases"])
        pmid_by_cite = sorted(
            recent_pmids,
            key=lambda pmid: float(bucket["metrics"].get(pmid, (0.0, 0.0, 0.0))[0]),
            reverse=True,
        )
        rows.append({
            "name": name,
            "type": "Method",
            "recent_cnt": len(recent_pmids),
            "prior_cnt": len(bucket["prior_pmids"]),
            "avg_cite": round(sum(m[0] for m in metrics) / len(metrics), 1),
            "avg_cpy": round(sum(m[1] for m in metrics) / len(metrics), 2),
            "avg_if": round(sum(m[2] for m in metrics) / len(metrics), 2),
            "alias_count": len(aliases),
            "aliases": ", ".join(aliases[:5]),
            "top_pmids": pmid_by_cite[:3],
        })
    return _enrich_entity_rows(rows)[:limit]


def compute_new_methods(
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    counts: dict[str, int] | None = None,
    role_by_name: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Nascent methods in the publication window (min_recent=1, no heat Top-N)."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    rows = compute_emerging_entities(
        "Method",
        window_days=window,
        prior_days=prior,
        min_recent=1,
        limit=_NEW_METHODS_POOL_UNCAPPED,
    )
    annotate_method_rows(rows, counts=counts)
    if role_by_name is not None:
        annotate_method_role(rows, role_by_name=role_by_name)
    else:
        annotate_method_role(rows)
    nascent = [row for row in rows if row.get("method_maturity") == "nascent"]
    nascent.sort(
        key=lambda row: (
            -int(row.get("corpus_paper_cnt") or 0),
            -float(row.get("emerging_score") or 0),
            str(row.get("name") or ""),
        )
    )
    return nascent[: config.HOTSPOT_NEW_METHODS_MAX]


def compute_emerging_entities(
    entity_type: str,
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    min_recent: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Entities ranked by velocity in the recent publication window."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    min_r = min_recent if min_recent is not None else config.HOTSPOT_MIN_RECENT_PAPERS
    top_n = limit if limit is not None else config.HOTSPOT_TOP_N
    recent_start, prior_start, prior_end = _window_params(window, prior)
    if entity_type == "Method":
        return _compute_emerging_method_entities(
            recent_start=recent_start,
            prior_start=prior_start,
            prior_end=prior_end,
            min_recent=min_r,
            limit=top_n,
        )
    # Method heat should reflect techniques applied in papers, not RELATED_TO
    # co-mentions of umbrella terms (deep learning / pathomics / ...).
    relation_filter = (
        "AND r.relation = 'APPLIES_METHOD'" if entity_type == "Method" else ""
    )
    window_pub = _window_pub_predicate("p")

    rows = _q(
        f"""
        WITH recent_pmids AS (
            SELECT COALESCE(p.source_key,p.pmid) AS pmid FROM papers p
            WHERE {window_pub}
              AND date(p.pub_date) >= date('now', ?)
        ),
        prior_pmids AS (
            SELECT COALESCE(p.source_key,p.pmid) AS pmid FROM papers p
            WHERE {window_pub}
              AND date(p.pub_date) >= date('now', ?)
              AND date(p.pub_date) < date('now', ?)
        )
        SELECT e.name,
               e.type,
               COUNT(DISTINCT CASE
                   WHEN r.source_pmid IN (SELECT pmid FROM recent_pmids)
                   THEN r.source_pmid END) AS recent_cnt,
               COUNT(DISTINCT CASE
                   WHEN r.source_pmid IN (SELECT pmid FROM prior_pmids)
                   THEN r.source_pmid END) AS prior_cnt,
               ROUND(AVG(CASE
                   WHEN r.source_pmid IN (SELECT pmid FROM recent_pmids)
                   THEN COALESCE(p.citation_count, 0) END), 1) AS avg_cite,
               ROUND(AVG(CASE
                   WHEN r.source_pmid IN (SELECT pmid FROM recent_pmids)
                   THEN 1.0 * COALESCE(p.citation_count, 0)
                        / MAX(2026 - COALESCE(p.year, ?), 1) END), 2) AS avg_cpy,
               ROUND(AVG(CASE
                   WHEN r.source_pmid IN (SELECT pmid FROM recent_pmids)
                   THEN COALESCE(j.impact_factor, 0) END), 2) AS avg_if
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        JOIN papers p ON p.source_key = r.source_pmid
          OR (p.source_key IS NULL AND p.pmid = r.source_pmid)
        LEFT JOIN journals j ON p.journal_id = j.id
        WHERE e.type = ?
          {relation_filter}
        GROUP BY e.id
        HAVING recent_cnt >= ?
        """,
        (
            recent_start,
            prior_start,
            prior_end,
            config.SEARCH_YEAR_END,
            entity_type,
            min_r,
        ),
    )
    return _enrich_entity_rows(rows)[:top_n]


def _top_pmids_for_entity(entity_name: str, entity_type: str, window_days: int) -> list[str]:
    recent_start, _, _ = _window_params(window_days, 0)
    relation_filter = (
        "AND r.relation = 'APPLIES_METHOD'" if entity_type == "Method" else ""
    )
    name_filter = "" if entity_type == "Method" else "AND e.name = ?"
    window_pub = _window_pub_predicate("p")
    rows = _q(
        f"""
        SELECT DISTINCT COALESCE(p.source_key,p.pmid) AS pmid, e.name
        FROM papers p
        JOIN relations r ON r.source_pmid = p.source_key
          OR (p.source_key IS NULL AND r.source_pmid = p.pmid)
        JOIN entities e ON r.object_id = e.id
        WHERE e.type = ?
          {relation_filter}
          {name_filter}
          AND {window_pub}
          AND date(p.pub_date) >= date('now', ?)
        ORDER BY COALESCE(p.citation_count, 0) DESC, p.year DESC
        """,
        (
            (entity_type, recent_start)
            if entity_type == "Method"
            else (entity_type, entity_name, recent_start)
        ),
    )
    if entity_type == "Method":
        seen: set[str] = set()
        out: list[str] = []
        for row in rows:
            if resolve_method_canonical(str(row["name"])) != entity_name:
                continue
            pmid = str(row["pmid"])
            if pmid in seen:
                continue
            seen.add(pmid)
            out.append(pmid)
            if len(out) >= 3:
                break
        return out
    return [str(r["pmid"]) for r in rows if str(r["name"]) == entity_name][:3]


def _combo_gap_phase(recent: int, prior: int) -> str:
    if prior == 0 and recent <= 2:
        return "nascent"
    if recent > prior:
        return "heating"
    if recent >= 2:
        return "active"
    return "stable"


def _format_disease_list(diseases: list[str], *, max_show: int = 8) -> str:
    shown = diseases[:max_show]
    text = ", ".join(shown)
    if len(diseases) > max_show:
        text += f" …(+{len(diseases) - max_show})"
    return text


def group_hot_combos_by_method(combos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse pair rows into one row per method (diseases listed together).

    Prefer payload field ``hot_combos_by_method`` from ``compute_weekly_hotspots``,
    which uses distinct-PMID unions. This helper is a display fallback that
    summarizes already-built pair rows (counts taken from the strongest pair).
    """
    groups: dict[str, dict[str, Any]] = {}
    for row in combos:
        method = str(row.get("method") or "")
        if not method:
            continue
        group = groups.get(method)
        if group is None:
            group = {
                "method": method,
                "diseases_list": [],
                "recent_cnt": 0,
                "prior_cnt": 0,
                "velocity": 0.0,
                "gap_phase": row.get("gap_phase"),
                "emerging_score": 0.0,
                "method_maturity": row.get("method_maturity"),
                "corpus_paper_cnt": row.get("corpus_paper_cnt"),
            }
            groups[method] = group
        disease = str(row.get("disease") or "").strip()
        if disease:
            group["diseases_list"].append(disease)
        score = float(row.get("emerging_score") or 0)
        if score >= float(group["emerging_score"] or 0):
            group["emerging_score"] = row.get("emerging_score")
            group["recent_cnt"] = int(row.get("recent_cnt") or 0)
            group["prior_cnt"] = int(row.get("prior_cnt") or 0)
            group["velocity"] = row.get("velocity")
            group["gap_phase"] = row.get("gap_phase")
        if group.get("method_maturity") is None:
            group["method_maturity"] = row.get("method_maturity")
        if group.get("corpus_paper_cnt") is None:
            group["corpus_paper_cnt"] = row.get("corpus_paper_cnt")

    out: list[dict[str, Any]] = []
    for group in groups.values():
        diseases = sorted(set(group.pop("diseases_list")))
        group["disease_cnt"] = len(diseases)
        group["diseases"] = _format_disease_list(diseases)
        out.append(group)
    out.sort(
        key=lambda r: (
            0 if r.get("method_maturity") != "established" else 1,
            -float(r.get("emerging_score") or 0),
            str(r.get("method") or ""),
        )
    )
    return out


def compute_hot_combos(
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Method×disease pairs active in the recent publication window."""
    pairs, _grouped = compute_hot_combo_boards(
        window_days=window_days,
        prior_days=prior_days,
        limit=limit,
    )
    return pairs


def compute_hot_combo_boards(
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (pair rows, method-collapsed rows with distinct-PMID stats)."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    top_n = limit if limit is not None else config.HOTSPOT_TOP_N
    recent_start, prior_start, prior_end = _window_params(window, prior)
    window_pub = _window_pub_predicate("p")

    rows = _q(
        f"""
        WITH recent_pmids AS (
            SELECT COALESCE(p.source_key,p.pmid) AS pmid FROM papers p
            WHERE {window_pub}
              AND date(p.pub_date) >= date('now', ?)
        ),
        prior_pmids AS (
            SELECT COALESCE(p.source_key,p.pmid) AS pmid FROM papers p
            WHERE {window_pub}
              AND date(p.pub_date) >= date('now', ?)
              AND date(p.pub_date) < date('now', ?)
        )
        SELECT em.name AS method,
               ed.name AS disease,
               COALESCE(p.source_key,p.pmid) AS pmid,
               COALESCE(p.source_key,p.pmid) IN (SELECT pmid FROM recent_pmids) AS in_recent,
               COALESCE(p.source_key,p.pmid) IN (SELECT pmid FROM prior_pmids) AS in_prior
        FROM papers p
        JOIN relations rm ON rm.source_pmid = p.source_key
          OR (p.source_key IS NULL AND rm.source_pmid = p.pmid)
            AND rm.relation = 'APPLIES_METHOD'
        JOIN entities em ON rm.object_id = em.id AND em.type = 'Method'
        JOIN relations rd ON rd.source_pmid = p.source_key
          OR (p.source_key IS NULL AND rd.source_pmid = p.pmid)
            AND rd.relation = 'TARGETS_DISEASE'
        JOIN entities ed ON rd.object_id = ed.id AND ed.type = 'Disease'
        WHERE COALESCE(p.source_key,p.pmid) IN (SELECT pmid FROM recent_pmids)
           OR COALESCE(p.source_key,p.pmid) IN (SELECT pmid FROM prior_pmids)
        """,
        (recent_start, prior_start, prior_end),
    )

    buckets: dict[tuple[str, str], dict[str, set[str]]] = {}
    for row in rows:
        raw_method = str(row["method"])
        if is_low_value_method(raw_method):
            continue
        method = resolve_method_canonical(raw_method)
        if is_low_value_method(method):
            continue
        key = (method, str(row["disease"]))
        bucket = buckets.setdefault(key, {"recent_pmids": set(), "prior_pmids": set()})
        if row["in_recent"]:
            bucket["recent_pmids"].add(str(row["pmid"]))
        if row["in_prior"]:
            bucket["prior_pmids"].add(str(row["pmid"]))

    out: list[dict[str, Any]] = []
    method_agg: dict[str, dict[str, Any]] = {}
    for (method, disease), bucket in buckets.items():
        recent = len(bucket["recent_pmids"])
        prior_cnt = len(bucket["prior_pmids"])
        if recent <= 0:
            continue
        phase = _combo_gap_phase(recent, prior_cnt)
        out.append({
            "method": method,
            "disease": disease,
            "recent_cnt": recent,
            "prior_cnt": prior_cnt,
            "velocity": round((recent - prior_cnt) / max(prior_cnt, 1), 2),
            "gap_phase": phase,
            "emerging_score": emerging_score(recent, prior_cnt, 0, 0, 0),
        })
        agg = method_agg.setdefault(
            method,
            {"recent_pmids": set(), "prior_pmids": set(), "diseases": set()},
        )
        agg["recent_pmids"].update(bucket["recent_pmids"])
        agg["prior_pmids"].update(bucket["prior_pmids"])
        agg["diseases"].add(disease)

    out.sort(
        key=lambda r: (
            -float(r["emerging_score"]),
            str(r["method"]),
            str(r["disease"]),
        )
    )

    grouped: list[dict[str, Any]] = []
    for method, agg in method_agg.items():
        recent = len(agg["recent_pmids"])
        prior_cnt = len(agg["prior_pmids"])
        if recent <= 0:
            continue
        diseases = sorted(agg["diseases"])
        phase = _combo_gap_phase(recent, prior_cnt)
        grouped.append({
            "method": method,
            "diseases": _format_disease_list(diseases),
            "disease_cnt": len(diseases),
            "recent_cnt": recent,
            "prior_cnt": prior_cnt,
            "velocity": round((recent - prior_cnt) / max(prior_cnt, 1), 2),
            "gap_phase": phase,
            "emerging_score": emerging_score(recent, prior_cnt, 0, 0, 0),
        })
    grouped.sort(
        key=lambda r: (
            -float(r["emerging_score"]),
            str(r["method"]),
        )
    )
    return out[:top_n], grouped[:top_n]


def compute_emerging_limitations(
    *,
    window_days: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Limitations newly reported in the recent publication window."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    top_n = limit if limit is not None else config.HOTSPOT_TOP_N
    recent_start, _, _ = _window_params(window, 0)
    window_pub = _window_pub_predicate("p")

    rows = _q(
        f"""
        SELECT e.name AS limitation,
               COUNT(DISTINCT r.source_pmid) AS recent_cnt,
               ROUND(AVG(COALESCE(p.citation_count, 0)), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id = e.id AND e.type = 'Limitation'
        JOIN papers p ON p.source_key = r.source_pmid
          OR (p.source_key IS NULL AND p.pmid = r.source_pmid)
        WHERE r.relation = 'REPORTS_LIMITATION'
          AND COALESCE(r.status, 'active') = 'active'
          AND {window_pub}
          AND date(p.pub_date) >= date('now', ?)
        GROUP BY e.id
        HAVING recent_cnt >= 1
        ORDER BY recent_cnt DESC
        LIMIT ?
        """,
        (recent_start, top_n),
    )
    return [dict(r) for r in rows]


def compute_weekly_hotspots(
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    min_recent: int | None = None,
) -> dict[str, Any]:
    """Aggregate all weekly hotspot leaderboards."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    min_r = min_recent if min_recent is not None else config.HOTSPOT_MIN_RECENT_PAPERS
    wid = week_id()
    in_window = count_window_papers(window)
    excluded = count_excluded_low_precision(window)
    excluded_future = count_excluded_future_pub_dates(window)

    methods = compute_emerging_entities(
        "Method", window_days=window, prior_days=prior, min_recent=min_r
    )
    diseases = compute_emerging_entities(
        "Disease", window_days=window, prior_days=prior, min_recent=min_r
    )
    tasks = compute_emerging_entities(
        "Task", window_days=window, prior_days=prior, min_recent=min_r
    )
    combos, combos_by_method = compute_hot_combo_boards(
        window_days=window, prior_days=prior
    )
    limitations = compute_emerging_limitations(window_days=window)
    counts = corpus_applies_method_counts_canonical()
    role_map = load_method_roles()
    annotate_method_rows(methods, counts=counts)
    annotate_method_role(methods, role_by_name=role_map)
    new_methods = compute_new_methods(
        window_days=window,
        prior_days=prior,
        counts=counts,
        role_by_name=role_map,
    )
    active_methods = list(methods)
    emerging_methods = [
        row for row in methods if row.get("method_maturity") != "established"
    ]
    annotate_method_rows(combos, name_key="method", counts=counts)
    annotate_method_rows(combos_by_method, name_key="method", counts=counts)
    annotate_method_role(combos, name_key="method", role_by_name=role_map)
    annotate_method_role(
        combos_by_method,
        name_key="method",
        role_by_name=role_map,
    )
    try:
        from analysis.method_family_supervised import load_active_method_family_name_map
        from analysis.method_taxonomy import FAMILIES

        family_release_id, family_by_name = load_active_method_family_name_map()
        family_labels = {family.family_id: family.zh for family in FAMILIES}
    except Exception:
        family_release_id, family_by_name, family_labels = None, {}, {}
    for rows, key in (
        (methods, "name"),
        (combos, "method"),
        (combos_by_method, "method"),
    ):
        annotate_method_family_rows(
            rows,
            name_key=key,
            family_by_name=family_by_name,
            family_labels=family_labels,
        )
    method_families = (
        group_method_family_rows(emerging_methods, family_labels)
        if family_release_id
        else []
    )
    _maturity_sort = lambda row: (
        0 if row.get("method_maturity") != "established" else 1,
        -float(row.get("emerging_score") or 0),
    )
    combos.sort(key=_maturity_sort)
    combos_by_method.sort(key=_maturity_sort)

    for section in (emerging_methods, diseases, tasks):
        for row in section[:5]:
            row["top_pmids"] = _top_pmids_for_entity(
                row["name"], row["type"], window
            )

    return {
        "week_id": wid,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": window,
        "prior_window_days": prior,
        "min_recent_papers": min_r,
        "time_axis": "pub_date",
        "eligible_precision": list(_ELIGIBLE_PRECISION),
        "papers_in_window": in_window,
        # Persist column / older callers still use papers_ingested.
        "papers_ingested": in_window,
        "papers_excluded_low_precision": excluded,
        "papers_excluded_future_pub_date": excluded_future,
        "emerging_methods": emerging_methods,
        "active_methods": active_methods,
        "new_methods": new_methods,
        "method_families": method_families,
        "method_family_release_id": family_release_id,
        "heating_diseases": diseases,
        "emerging_tasks": tasks,
        "hot_combos": combos,
        "hot_combos_by_method": combos_by_method,
        "new_limitations": limitations,
    }


def annotate_method_family_rows(
    rows: list[dict[str, Any]],
    *,
    name_key: str,
    family_by_name: dict[str, str],
    family_labels: dict[str, str],
) -> None:
    for row in rows:
        family_id = family_by_name.get(str(row.get(name_key) or ""))
        row["method_family"] = family_id or "unknown"
        row["method_family_zh"] = family_labels.get(family_id, "未归类")


def group_method_family_rows(
    rows: list[dict[str, Any]], family_labels: dict[str, str]
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("method_family") or "unknown")].append(row)
    grouped: list[dict[str, Any]] = []
    for family_id, family_rows in buckets.items():
        ordered = sorted(
            family_rows,
            key=lambda row: float(row.get("emerging_score") or 0),
            reverse=True,
        )
        grouped.append(
            {
                "family_id": family_id,
                "family_name_zh": family_labels.get(family_id, "未归类"),
                "method_count": len(family_rows),
                "methods": "；".join(str(row["name"]) for row in ordered[:8]),
                "recent_cnt": sum(int(row.get("recent_cnt") or 0) for row in family_rows),
                "prior_cnt": sum(int(row.get("prior_cnt") or 0) for row in family_rows),
                "emerging_score": round(
                    max(float(row.get("emerging_score") or 0) for row in family_rows), 2
                ),
            }
        )
    grouped.sort(
        key=lambda row: (float(row["emerging_score"]), int(row["recent_cnt"])),
        reverse=True,
    )
    return grouped


def _serialize_pmids(pmids: list[str] | None) -> str:
    return json.dumps(pmids or [], ensure_ascii=False)


def payload_to_snapshot_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten compute payload into DB snapshot rows."""
    rows: list[dict[str, Any]] = []

    def _add(board: str, items: list[dict], *, key_field: str, type_field: str | None = None) -> None:
        for rank, item in enumerate(items, start=1):
            rows.append({
                "board": board,
                "item_key": item[key_field],
                "entity_type": item.get(type_field) if type_field else None,
                "rank_pos": rank,
                "recent_cnt": item.get("recent_cnt"),
                "prior_cnt": item.get("prior_cnt"),
                "velocity": item.get("velocity"),
                "emerging_score": item.get("emerging_score"),
                "avg_cite": item.get("avg_cite"),
                "avg_if": item.get("avg_if"),
                "gap_phase": item.get("gap_phase"),
                "top_pmids": _serialize_pmids(item.get("top_pmids")),
            })

    _add("method", payload["emerging_methods"], key_field="name", type_field="type")
    _add("method_family", payload.get("method_families", []), key_field="family_id")
    _add("disease", payload["heating_diseases"], key_field="name", type_field="type")
    _add("task", payload["emerging_tasks"], key_field="name", type_field="type")
    for rank, combo in enumerate(payload["hot_combos"], start=1):
        rows.append({
            "board": "combo",
            "item_key": f"{combo['method']}|{combo['disease']}",
            "entity_type": "Method×Disease",
            "rank_pos": rank,
            "recent_cnt": combo.get("recent_cnt"),
            "prior_cnt": combo.get("prior_cnt"),
            "velocity": combo.get("velocity"),
            "emerging_score": combo.get("emerging_score"),
            "avg_cite": None,
            "avg_if": None,
            "gap_phase": combo.get("gap_phase"),
            "top_pmids": "[]",
        })
    for rank, lim in enumerate(payload["new_limitations"], start=1):
        rows.append({
            "board": "limitation",
            "item_key": lim["limitation"],
            "entity_type": "Limitation",
            "rank_pos": rank,
            "recent_cnt": lim.get("recent_cnt"),
            "prior_cnt": None,
            "velocity": None,
            "emerging_score": None,
            "avg_cite": lim.get("avg_cite"),
            "avg_if": None,
            "gap_phase": None,
            "top_pmids": "[]",
        })
    return rows


def persist_hotspot_snapshot(payload: dict[str, Any], report_path: str = "") -> int:
    """Write run metadata + leaderboard rows for week-over-week comparison."""
    wid = payload["week_id"]
    upsert_weekly_hotspot_run(
        wid,
        window_days=int(payload["window_days"]),
        prior_window_days=int(payload["prior_window_days"]),
        papers_ingested=int(payload["papers_ingested"]),
        report_path=report_path,
    )
    rows = payload_to_snapshot_rows(payload)
    return replace_weekly_hotspot_snapshots(wid, rows)


def _current_board_map(payload: dict[str, Any], board: str) -> dict[str, dict[str, Any]]:
    if board == "method":
        items = payload["emerging_methods"]
        return {r["name"]: {**r, "item_key": r["name"]} for r in items}
    if board == "method_family":
        items = payload.get("method_families", [])
        return {r["family_id"]: {**r, "item_key": r["family_id"]} for r in items}
    if board == "disease":
        items = payload["heating_diseases"]
        return {r["name"]: {**r, "item_key": r["name"]} for r in items}
    if board == "combo":
        return {
            f"{r['method']}|{r['disease']}": {
                **r,
                "item_key": f"{r['method']}|{r['disease']}",
                "label": f"{r['method']} × {r['disease']}",
            }
            for r in payload["hot_combos"]
        }
    return {}


def compare_with_previous_week(
    payload: dict[str, Any],
    *,
    top_n: int | None = None,
) -> dict[str, Any]:
    """Compare current payload against the previous week's persisted snapshot."""
    top = top_n if top_n is not None else min(10, config.HOTSPOT_TOP_N)
    cur_week = payload["week_id"]
    prev_week = previous_week_id(cur_week)
    known_weeks = set(list_weekly_hotspot_weeks(limit=104))
    if prev_week not in known_weeks:
        return {
            "previous_week_id": prev_week,
            "has_baseline": False,
            "boards": {},
        }

    boards_out: dict[str, Any] = {}
    for board in ("method", "disease", "combo"):
        cur_map = _current_board_map(payload, board)
        cur_top = sorted(
            cur_map.values(),
            key=lambda r: float(r.get("emerging_score") or 0),
            reverse=True,
        )[:top]
        prev_rows = get_weekly_hotspot_snapshots(prev_week, board)
        prev_map = {r["item_key"]: r for r in prev_rows}
        prev_top = sorted(
            prev_rows,
            key=lambda r: int(r.get("rank_pos") or 999),
        )[:top]

        cur_keys = {r["item_key"] for r in cur_top}
        prev_keys = {r["item_key"] for r in prev_top}

        new_entrants = []
        for row in cur_top:
            if row["item_key"] not in prev_map:
                new_entrants.append({
                    "item_key": row["item_key"],
                    "label": row.get("label") or row["item_key"],
                    "emerging_score": row.get("emerging_score"),
                    "recent_cnt": row.get("recent_cnt"),
                })

        cooled = []
        for row in prev_top:
            if row["item_key"] not in cur_keys:
                cooled.append({
                    "item_key": row["item_key"],
                    "label": row["item_key"].replace("|", " × "),
                    "emerging_score": row.get("emerging_score"),
                    "rank_pos": row.get("rank_pos"),
                })

        rank_changes = []
        for row in cur_top:
            prev = prev_map.get(row["item_key"])
            if not prev:
                continue
            old_rank = int(prev.get("rank_pos") or 999)
            new_rank = cur_top.index(row) + 1
            delta = old_rank - new_rank
            if abs(delta) >= 3:
                rank_changes.append({
                    "item_key": row["item_key"],
                    "label": row.get("label") or row["item_key"],
                    "old_rank": old_rank,
                    "new_rank": new_rank,
                    "delta": delta,
                })

        boards_out[board] = {
            "new_entrants": new_entrants[:top],
            "cooled": cooled[:top],
            "rank_changes": sorted(rank_changes, key=lambda r: abs(r["delta"]), reverse=True)[:top],
        }

    return {
        "previous_week_id": prev_week,
        "has_baseline": True,
        "boards": boards_out,
    }


def compute_emerging_gap_opportunities(
    focus: str | None = None,
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    min_recent: int | None = None,
    limit: int | None = None,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Find sparse, task-bridged method-to-disease transfer candidates."""
    from analysis.binding_enrichment import actionability_bump, enrich_method_disease_rows
    from analysis.focus_filter import focus_sql_clause, normalize_focus
    from analysis.study_type_signals import annotate_study_type_rows
    from analysis.task_quality import classify_task_quality
    from extractor.entity_normalize import normalize_entity_name

    role_map = load_method_roles()
    data = payload or compute_weekly_hotspots(
        window_days=window_days,
        prior_days=prior_days,
        min_recent=min_recent,
    )
    # Prefer 新苗头 board; never use established methods (LLM/SVM/…) as transfer heat.
    heat_rows = data.get("emerging_methods") or []
    if not heat_rows:
        heat_rows = [
            row
            for row in (data.get("active_methods") or [])
            if row.get("method_maturity") != "established"
        ]
    method_stats = {
        resolve_method_canonical(str(row["name"])): row
        for row in heat_rows[:20]
        if row.get("method_maturity") != "established"
    }
    method_counts: dict[str, int] | None = None
    hot_methods = set(method_stats)
    hot_diseases = {
        str(row["name"]) for row in data.get("heating_diseases", [])[:20]
    }
    if not hot_methods:
        return []

    active_edges = _q(
        """
        SELECT r.source_pmid, r.relation, e.name, e.type
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        WHERE COALESCE(r.status, 'active') = 'active'
          AND (
              (r.relation = 'APPLIES_METHOD' AND e.type = 'Method')
              OR (r.relation = 'TARGETS_DISEASE' AND e.type = 'Disease')
              OR (r.relation = 'PERFORMS_TASK' AND e.type = 'Task')
          )
        """
    )
    by_pmid: dict[str, dict[str, set[str]]] = {}
    for edge in active_edges:
        bucket = by_pmid.setdefault(
            str(edge["source_pmid"]),
            {"Method": set(), "Disease": set(), "Task": set()},
        )
        name = str(edge["name"])
        if edge["type"] == "Method":
            if is_low_value_method(name):
                continue
            name = resolve_method_canonical(name)
            if is_low_value_method(name):
                continue
        if edge["type"] == "Task":
            name = normalize_entity_name(name, "Task")
        bucket[str(edge["type"])].add(name)

    method_diseases: dict[str, set[str]] = {}
    method_tasks: dict[str, dict[str, set[str]]] = {}
    disease_tasks: dict[str, dict[str, set[str]]] = {}
    pair_pmids: dict[tuple[str, str], set[str]] = {}
    same_paper_tasks: dict[tuple[str, str, str], set[str]] = {}
    for pmid, entities in by_pmid.items():
        methods = entities["Method"]
        diseases = entities["Disease"]
        ok_tasks = {
            task for task in entities["Task"]
            if classify_task_quality(task) == "ok"
        }
        for method in methods:
            method_diseases.setdefault(method, set()).update(diseases)
            task_pmids = method_tasks.setdefault(method, {})
            for task in ok_tasks:
                task_pmids.setdefault(task, set()).add(pmid)
            for disease in diseases:
                pair_pmids.setdefault((method, disease), set()).add(pmid)
                for task in ok_tasks:
                    same_paper_tasks.setdefault((method, disease, task), set()).add(pmid)
        for disease in diseases:
            task_pmids = disease_tasks.setdefault(disease, {})
            for task in ok_tasks:
                task_pmids.setdefault(task, set()).add(pmid)

    if normalize_focus(focus):
        # Focus filters targets to focus-matched diseases only (not a union with
        # the full heating board, which floods non-focus diseases into viz).
        focus_diseases = _q(
            "SELECT name FROM entities e WHERE e.type = 'Disease'"
            + focus_sql_clause("e.name", focus)
        )
        hot_diseases = {str(row["name"]) for row in focus_diseases}
        if not hot_diseases:
            return []

    rows: list[dict[str, Any]] = []
    for method in hot_methods:
        support = method_diseases.get(method, set())
        if not support:
            continue
        for disease in hot_diseases:
            paper_cnt = len(pair_pmids.get((method, disease), set()))
            if paper_cnt > 2:
                continue
            support_diseases = sorted(support - {disease})
            if not support_diseases:
                continue
            shared_tasks = set(method_tasks.get(method, {})) & set(
                disease_tasks.get(disease, {})
            )
            if not shared_tasks:
                continue

            def task_rank(task: str) -> tuple[int, int, str]:
                same = bool(same_paper_tasks.get((method, disease, task)))
                support_count = (
                    len(method_tasks[method][task]) + len(disease_tasks[disease][task])
                )
                return (int(same), support_count, task)

            bridge_task = max(shared_tasks, key=task_rank)
            bridge_mode = (
                "same_paper"
                if same_paper_tasks.get((method, disease, bridge_task))
                else "cross_paper"
            )
            bridge_bonus = (
                _BRIDGE_BONUS_SAME
                if bridge_mode == "same_paper"
                else _BRIDGE_BONUS_CROSS
            )
            literature_gap = "unexplored" if paper_cnt == 0 else "minimal"
            stats = method_stats[method]
            hot_score = float(stats.get("emerging_score") or 0)
            maturity = stats.get("method_maturity")
            if not maturity or "corpus_paper_cnt" not in stats:
                if method_counts is None:
                    method_counts = corpus_applies_method_counts_canonical()
                maturity = classify_method_maturity(
                    method,
                    int(stats.get("corpus_paper_cnt") or method_counts.get(method, 0)),
                )
            novelty = context_novelty_bonus(paper_cnt)
            penalty = maturity_penalty(maturity)
            nascent = nascent_bonus(maturity)
            rows.append({
                "method": method,
                "disease": disease,
                "method_maturity": maturity,
                "context_novelty_bonus": novelty,
                "maturity_penalty": penalty,
                "literature_gap": literature_gap,
                "literature_paper_cnt": paper_cnt,
                "bridge_task": bridge_task,
                "bridge_quality": "ok",
                "bridge_mode": bridge_mode,
                "support_diseases": ", ".join(support_diseases[:5]),
                "recent_hot_cnt": stats.get("recent_cnt", 0),
                "velocity": stats.get("velocity"),
                "emerging_score": hot_score,
                "opportunity_score": round(
                    hot_score
                    + literature_gap_points(literature_gap)
                    + bridge_bonus
                    + novelty
                    - penalty
                    + nascent,
                    2,
                ),
            })

    rows = enrich_method_disease_rows(rows)
    for row in rows:
        row["opportunity_score"] = round(
            float(row["opportunity_score"])
            + actionability_bump(
                int(row.get("binding_paper_cnt") or 0),
                int(row.get("public_dataset_cnt") or 0),
            ),
            2,
        )
    for row in rows:
        row["gap_kind"] = "applied"
    rows = annotate_study_type_rows(rows)
    rows.sort(
        key=lambda r: (
            -float(r["opportunity_score"]),
            0 if r.get("method_maturity") != "established" else 1,
            -int(r.get("surveys_method_paper_cnt") or 0),
        )
    )
    top_n = limit if limit is not None else min(20, config.HOTSPOT_TOP_N)
    rows = rows[:top_n]
    annotate_method_role(rows, name_key="method", role_by_name=role_map)
    return rows


def tool_emerging_gap_opportunities(focus: str | None = None) -> dict[str, Any]:
    window = int(config.HOTSPOT_TRANSFER_WINDOW_DAYS)
    rows = compute_emerging_gap_opportunities(focus=focus, window_days=window)
    desc = (
        "Sparse method×disease transfer candidates from non-established (新苗头) methods "
        "requiring an ok Task bridge "
        "(opportunity_score = emerging_score + literature gap tier + bridge bonus "
        "+ context novelty + nascent bonus − maturity penalty "
        "+ optional binding actionability bump; established methods like LLM/SVM excluded; "
        f"window_days={window})"
    )
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "data": rows}


def _format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "_No data in this window._\n"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, sep]
    for row in rows:
        lines.append(
            "| " + " | ".join(str(row.get(c, ""))[:80] for c in columns) + " |"
        )
    return "\n".join(lines) + "\n"


def _format_wow_section(wow: dict[str, Any]) -> list[str]:
    lines = ["## Week-over-Week", ""]
    if not wow.get("has_baseline"):
        prev = wow.get("previous_week_id", "?")
        lines.append(
            f"_No snapshot for **{prev}** yet. Run `hotspot-report` weekly to enable comparison._"
        )
        lines.append("")
        return lines

    lines.append(f"Compared with **{wow['previous_week_id']}** (persisted snapshot).")
    lines.append(
        "> Method-board comparisons can label previously established methods as dropped for "
        "one transition week after novelty gating; this is reclassification, not necessarily cooling."
    )
    lines.append("")
    board_titles = {
        "method": "Methods",
        "disease": "Diseases",
        "combo": "Method×Disease",
    }
    for board, title in board_titles.items():
        data = wow.get("boards", {}).get(board, {})
        lines.append(f"### {title}")
        lines.append("")
        if data.get("new_entrants"):
            lines.append("**New in top ranks:** " + ", ".join(
                f"{r['label']} (score={r.get('emerging_score')})" for r in data["new_entrants"][:5]
            ))
        else:
            lines.append("**New in top ranks:** _none_")
        if data.get("cooled"):
            lines.append("**Dropped from top ranks:** " + ", ".join(
                r["label"] for r in data["cooled"][:5]
            ))
        else:
            lines.append("**Dropped from top ranks:** _none_")
        if data.get("rank_changes"):
            lines.append("")
            lines.append("| item | old_rank | new_rank | delta |")
            lines.append("| --- | --- | --- | --- |")
            for r in data["rank_changes"][:5]:
                lines.append(
                    f"| {r['label'][:60]} | {r['old_rank']} | {r['new_rank']} | {r['delta']:+d} |"
                )
        lines.append("")
    return lines


def generate_hotspot_report(
    payload: dict[str, Any] | None = None,
    *,
    wow: dict[str, Any] | None = None,
) -> str:
    """Render markdown report from compute_weekly_hotspots() payload."""
    data = payload or compute_weekly_hotspots()
    comparison = wow if wow is not None else compare_with_previous_week(data)
    established = [
        row
        for row in data.get("active_methods", [])
        if row.get("method_maturity") == "established"
    ][:5]
    lines = [
        f"# Weekly Hotspot Report — {data['week_id']}",
        "",
        f"_Generated: {data['generated_at']}_",
        "",
        "## Window",
        "",
        f"- Publication window: **{data['window_days']} days** (`papers.pub_date`)",
        f"- Min recent papers (entity boards): "
        f"**{data.get('min_recent_papers', config.HOTSPOT_MIN_RECENT_PAPERS)}**",
        f"- Eligible date precision: **{', '.join(data.get('eligible_precision') or ['day', 'month'])}** "
        "(year/unknown excluded from main boards)",
        f"- Prior comparison window: **{data['prior_window_days']} days**",
        f"- Papers in window: **{data.get('papers_in_window', data.get('papers_ingested', 0))}**",
        f"- Excluded (year/unknown in window): **{data.get('papers_excluded_low_precision', 0)}**",
        f"- Excluded (future pub_date in window): "
        f"**{data.get('papers_excluded_future_pub_date', 0)}**",
        "",
        "> Velocity = (recent_cnt − prior_cnt) / max(prior_cnt, 1). "
        "Week-over-week uses **persisted snapshots**, not publication windows alone.",
        "> Hotspot boards use **`pub_date`** (not PubMed EDAT). "
        "EDAT=0 with non-zero pub_date window is normal when papers were indexed earlier.",
        "",
    ]
    lines.extend(_format_wow_section(comparison))
    lines.extend([
        "## New Methods This Window (本周新方法)",
        "",
        "_Nascent only (corpus ≤2); fixed min_recent=1; not cut by heat Top-N._",
        "",
    ])
    new_methods = data.get("new_methods") or []
    if new_methods:
        lines.extend([
            _format_table(
                new_methods,
                [
                    "name",
                    "method_role",
                    "corpus_paper_cnt",
                    "recent_cnt",
                    "prior_cnt",
                    "velocity",
                    "emerging_score",
                    "top_pmids",
                ],
            ),
        ])
    else:
        lines.extend(["None", ""])
    lines.extend([
        "## Emerging Methods (新苗头)",
        "",
        _format_table(
            data["emerging_methods"],
            [
                "name",
                "method_maturity",
                "corpus_paper_cnt",
                "recent_cnt",
                "prior_cnt",
                "velocity",
                "emerging_score",
                "avg_cite",
                "top_pmids",
            ],
        ),
    ])
    if data.get("method_families"):
        lines.extend([
            "## Emerging Method Families",
            "",
            f"_Active taxonomy release: {data.get('method_family_release_id')}_",
            "",
            _format_table(
                data["method_families"],
                ["family_id", "family_name_zh", "method_count", "methods", "recent_cnt", "prior_cnt", "emerging_score"],
            ),
        ])
    if established:
        lines.extend([
            "### Established Methods (active this window)",
            "",
            *[
                f"- {row['name']} (corpus papers: {row.get('corpus_paper_cnt', 0)})"
                for row in established
            ],
            "",
        ])
    lines.extend([
        "## Heating Diseases",
        "",
        _format_table(
            data["heating_diseases"],
            ["name", "recent_cnt", "prior_cnt", "velocity", "emerging_score", "avg_cite", "top_pmids"],
        ),
        "## Emerging Tasks",
        "",
        _format_table(
            data["emerging_tasks"],
            ["name", "recent_cnt", "prior_cnt", "velocity", "emerging_score", "avg_cite", "top_pmids"],
        ),
        "## Hot Method×Disease Combos",
        "",
        "> Grouped by method (diseases listed together). Pair-level detail retained in snapshots.",
        "",
        _format_table(
            data.get("hot_combos_by_method")
            or group_hot_combos_by_method(data.get("hot_combos") or []),
            [
                "method",
                "method_maturity",
                "corpus_paper_cnt",
                "disease_cnt",
                "diseases",
                "recent_cnt",
                "prior_cnt",
                "velocity",
                "gap_phase",
                "emerging_score",
            ],
        ),
        "## New Limitations (recent publication window)",
        "",
        _format_table(
            data["new_limitations"],
            ["limitation", "recent_cnt", "avg_cite"],
        ),
    ])
    if data.get("emerging_gap_opportunities"):
        lines.extend([
            "## Transferable Candidates (task-bridged)",
            "",
            _format_table(
                data["emerging_gap_opportunities"],
                [
                    "method",
                    "disease",
                    "bridge_task",
                    "bridge_quality",
                    "bridge_mode",
                    "literature_gap",
                    "literature_paper_cnt",
                    "support_diseases",
                    "recent_hot_cnt",
                    "velocity",
                    "emerging_score",
                    "opportunity_score",
                ],
            ),
        ])
    return "\n".join(lines)


def save_hotspot_report(
    path: str | None = None,
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    min_recent: int | None = None,
    persist: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Compute hotspots, write markdown, optionally persist snapshot."""
    payload = compute_weekly_hotspots(
        window_days=window_days,
        prior_days=prior_days,
        min_recent=min_recent,
    )
    wow = compare_with_previous_week(payload)
    payload["week_over_week"] = wow
    payload["emerging_gap_opportunities"] = compute_emerging_gap_opportunities(
        window_days=window_days,
        prior_days=prior_days,
        payload=payload,
    )
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out = path or os.path.join(
        config.OUTPUT_DIR,
        f"weekly_hotspot_{payload['week_id']}.md",
    )
    report = generate_hotspot_report(payload, wow=wow)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    if persist:
        n = persist_hotspot_snapshot(payload, report_path=out)
        payload["snapshot_rows"] = n
        try:
            from analysis.ops_memory import link_hotspot_week

            link_hotspot_week(payload["week_id"], focus_key="__all__", source="hotspot")
        except Exception as exc:
            print(f"[Hotspot] ops memory link skipped: {exc}", flush=True)
    return out, payload
