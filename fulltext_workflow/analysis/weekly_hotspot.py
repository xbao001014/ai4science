"""Weekly research hotspot detection from recent publication dates."""
from __future__ import annotations

import json
import math
import os
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
from analysis.method_synonyms import resolve_method_canonical
from db.schema import (
    get_conn,
    get_weekly_hotspot_snapshots,
    list_weekly_hotspot_weeks,
    replace_weekly_hotspot_snapshots,
    upsert_weekly_hotspot_run,
)

# Main boards require at least month-level PubMed dates (折中).
_ELIGIBLE_PRECISION = ("day", "month")

# Task bridges are stronger when a paper demonstrates the full method-disease-task
# combination, rather than only linking the method and disease through task evidence
# in different papers.
_BRIDGE_BONUS_SAME = 2.0
_BRIDGE_BONUS_CROSS = 1.0


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


def count_window_papers(window_days: int) -> int:
    """Count papers with eligible pub_date in the recent publication window."""
    recent_start, _, _ = _window_params(window_days, 0)
    row = _q(
        f"""
        SELECT COUNT(*) AS n FROM papers p
        WHERE {_eligible_pub_predicate('p')}
          AND date(p.pub_date) >= date('now', ?)
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
    eligible = _eligible_pub_predicate("p")
    edge_rows = _q(
        f"""
        WITH recent_pmids AS (
            SELECT pmid FROM papers p
            WHERE {eligible}
              AND date(p.pub_date) >= date('now', ?)
        ),
        prior_pmids AS (
            SELECT pmid FROM papers p
            WHERE {eligible}
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
        JOIN papers p ON r.source_pmid = p.pmid
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
        canonical = resolve_method_canonical(str(edge["name"]))
        bucket = buckets.setdefault(
            canonical,
            {"recent_pmids": set(), "prior_pmids": set(), "aliases": set(), "metrics": {}},
        )
        bucket["aliases"].add(str(edge["name"]))
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
        aliases = sorted(bucket["aliases"])
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
        })
    return _enrich_entity_rows(rows)[:limit]


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
    eligible = _eligible_pub_predicate("p")

    rows = _q(
        f"""
        WITH recent_pmids AS (
            SELECT pmid FROM papers p
            WHERE {eligible}
              AND date(p.pub_date) >= date('now', ?)
        ),
        prior_pmids AS (
            SELECT pmid FROM papers p
            WHERE {eligible}
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
        JOIN papers p ON r.source_pmid = p.pmid
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
    eligible = _eligible_pub_predicate("p")
    rows = _q(
        f"""
        SELECT DISTINCT p.pmid, e.name
        FROM papers p
        JOIN relations r ON r.source_pmid = p.pmid
        JOIN entities e ON r.object_id = e.id
        WHERE e.type = ?
          {relation_filter}
          AND {eligible}
          AND date(p.pub_date) >= date('now', ?)
        ORDER BY COALESCE(p.citation_count, 0) DESC, p.year DESC
        """,
        (entity_type, recent_start),
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


def compute_hot_combos(
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Method×disease pairs active in the recent publication window."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    top_n = limit if limit is not None else config.HOTSPOT_TOP_N
    recent_start, prior_start, prior_end = _window_params(window, prior)
    eligible = _eligible_pub_predicate("p")

    rows = _q(
        f"""
        WITH recent_pmids AS (
            SELECT pmid FROM papers p
            WHERE {eligible}
              AND date(p.pub_date) >= date('now', ?)
        ),
        prior_pmids AS (
            SELECT pmid FROM papers p
            WHERE {eligible}
              AND date(p.pub_date) >= date('now', ?)
              AND date(p.pub_date) < date('now', ?)
        ),
        combo AS (
            SELECT em.name AS method,
                   ed.name AS disease,
                   COUNT(DISTINCT CASE
                       WHEN p.pmid IN (SELECT pmid FROM recent_pmids)
                       THEN p.pmid END) AS recent_cnt,
                   COUNT(DISTINCT CASE
                       WHEN p.pmid IN (SELECT pmid FROM prior_pmids)
                       THEN p.pmid END) AS prior_cnt
            FROM papers p
            JOIN relations rm ON rm.source_pmid = p.pmid
                AND rm.relation = 'APPLIES_METHOD'
            JOIN entities em ON rm.object_id = em.id AND em.type = 'Method'
            JOIN relations rd ON rd.source_pmid = p.pmid
                AND rd.relation = 'TARGETS_DISEASE'
            JOIN entities ed ON rd.object_id = ed.id AND ed.type = 'Disease'
            GROUP BY em.id, ed.id
        )
        SELECT method, disease, recent_cnt, prior_cnt
        FROM combo
        WHERE recent_cnt >= 1
        ORDER BY recent_cnt DESC, prior_cnt ASC
        """,
        (recent_start, prior_start, prior_end),
    )

    out: list[dict[str, Any]] = []
    for row in rows[: top_n * 2]:
        recent = int(row["recent_cnt"] or 0)
        prior = int(row["prior_cnt"] or 0)
        if recent <= 0:
            continue
        if prior == 0 and recent <= 2:
            phase = "nascent"
        elif recent > prior:
            phase = "heating"
        elif recent >= 2:
            phase = "active"
        else:
            phase = "stable"
        out.append({
            "method": resolve_method_canonical(str(row["method"])),
            "disease": row["disease"],
            "recent_cnt": recent,
            "prior_cnt": prior,
            "velocity": round((recent - prior) / max(prior, 1), 2),
            "gap_phase": phase,
            "emerging_score": emerging_score(recent, prior, 0, 0, 0),
        })
    out.sort(key=lambda r: r["emerging_score"], reverse=True)
    return out[:top_n]


def compute_emerging_limitations(
    *,
    window_days: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Limitations newly reported in the recent publication window."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    top_n = limit if limit is not None else config.HOTSPOT_TOP_N
    recent_start, _, _ = _window_params(window, 0)
    eligible = _eligible_pub_predicate("p")

    rows = _q(
        f"""
        SELECT e.name AS limitation,
               COUNT(DISTINCT r.source_pmid) AS recent_cnt,
               ROUND(AVG(COALESCE(p.citation_count, 0)), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id = e.id AND e.type = 'Limitation'
        JOIN papers p ON r.source_pmid = p.pmid
        WHERE r.relation = 'REPORTS_LIMITATION'
          AND COALESCE(r.status, 'active') = 'active'
          AND {eligible}
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
) -> dict[str, Any]:
    """Aggregate all weekly hotspot leaderboards."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    wid = week_id()
    in_window = count_window_papers(window)
    excluded = count_excluded_low_precision(window)

    methods = compute_emerging_entities("Method", window_days=window, prior_days=prior)
    diseases = compute_emerging_entities("Disease", window_days=window, prior_days=prior)
    tasks = compute_emerging_entities("Task", window_days=window, prior_days=prior)
    combos = compute_hot_combos(window_days=window, prior_days=prior)
    limitations = compute_emerging_limitations(window_days=window)
    counts = corpus_applies_method_counts_canonical()
    annotate_method_rows(methods, counts=counts)
    active_methods = list(methods)
    emerging_methods = [
        row for row in methods if row.get("method_maturity") != "established"
    ]
    annotate_method_rows(combos, name_key="method", counts=counts)
    combos.sort(
        key=lambda row: (
            0 if row.get("method_maturity") != "established" else 1,
            -float(row.get("emerging_score") or 0),
        )
    )

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
        "time_axis": "pub_date",
        "eligible_precision": list(_ELIGIBLE_PRECISION),
        "papers_in_window": in_window,
        # Persist column / older callers still use papers_ingested.
        "papers_ingested": in_window,
        "papers_excluded_low_precision": excluded,
        "emerging_methods": emerging_methods,
        "active_methods": active_methods,
        "heating_diseases": diseases,
        "emerging_tasks": tasks,
        "hot_combos": combos,
        "new_limitations": limitations,
    }


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
    limit: int | None = None,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Find sparse, task-bridged method-to-disease transfer candidates."""
    from analysis.binding_enrichment import actionability_bump, enrich_method_disease_rows
    from analysis.focus_filter import focus_sql_clause, normalize_focus
    from analysis.study_type_signals import annotate_study_type_rows
    from analysis.task_quality import classify_task_quality
    from extractor.entity_normalize import normalize_entity_name

    data = payload or compute_weekly_hotspots(
        window_days=window_days,
        prior_days=prior_days,
    )
    method_stats = {
        resolve_method_canonical(str(row["name"])): row
        for row in (data.get("active_methods") or data.get("emerging_methods", []))[:20]
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
            name = resolve_method_canonical(name)
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
        focus_diseases = _q(
            "SELECT name FROM entities e WHERE e.type = 'Disease'"
            + focus_sql_clause("e.name", focus)
        )
        hot_diseases.update(str(row["name"]) for row in focus_diseases)

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
    return rows[:top_n]


def tool_emerging_gap_opportunities(focus: str | None = None) -> dict[str, Any]:
    rows = compute_emerging_gap_opportunities(focus=focus)
    desc = (
        "Sparse method×disease transfer candidates requiring an ok Task bridge "
        "(opportunity_score = emerging_score + literature gap tier + bridge bonus "
        "+ context novelty + nascent bonus − maturity penalty "
        "+ optional binding actionability bump)"
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
        f"- Eligible date precision: **{', '.join(data.get('eligible_precision') or ['day', 'month'])}** "
        "(year/unknown excluded from main boards)",
        f"- Prior comparison window: **{data['prior_window_days']} days**",
        f"- Papers in window: **{data.get('papers_in_window', data.get('papers_ingested', 0))}**",
        f"- Excluded (year/unknown in window): **{data.get('papers_excluded_low_precision', 0)}**",
        "",
        "> Velocity = (recent_cnt − prior_cnt) / max(prior_cnt, 1). "
        "Week-over-week uses **persisted snapshots**, not publication windows alone.",
        "",
    ]
    lines.extend(_format_wow_section(comparison))
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
        _format_table(
            data["hot_combos"],
            [
                "method",
                "method_maturity",
                "corpus_paper_cnt",
                "disease",
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
    persist: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Compute hotspots, write markdown, optionally persist snapshot."""
    payload = compute_weekly_hotspots(
        window_days=window_days,
        prior_days=prior_days,
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