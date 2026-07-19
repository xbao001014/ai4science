"""Weekly research hotspot detection from incrementally ingested papers."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import config
from analysis.impact_scoring import literature_gap_points, norm_if
from db.schema import (
    get_conn,
    get_weekly_hotspot_snapshots,
    list_weekly_hotspot_weeks,
    replace_weekly_hotspot_snapshots,
    upsert_weekly_hotspot_run,
)


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


def count_ingested_papers(window_days: int) -> int:
    recent_start, _, _ = _window_params(window_days, 0)
    row = _q(
        """
        SELECT COUNT(*) AS n FROM papers
        WHERE created_at >= datetime('now', ?)
        """,
        (recent_start,),
    )
    return int(row[0]["n"]) if row else 0


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


def compute_emerging_entities(
    entity_type: str,
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    min_recent: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Entities ranked by velocity in the recent ingest window."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    min_r = min_recent if min_recent is not None else config.HOTSPOT_MIN_RECENT_PAPERS
    top_n = limit if limit is not None else config.HOTSPOT_TOP_N
    recent_start, prior_start, prior_end = _window_params(window, prior)
    # Method heat should reflect techniques applied in papers, not RELATED_TO
    # co-mentions of umbrella terms (deep learning / pathomics / ...).
    relation_filter = (
        "AND r.relation = 'APPLIES_METHOD'" if entity_type == "Method" else ""
    )

    rows = _q(
        f"""
        WITH recent_pmids AS (
            SELECT pmid FROM papers WHERE created_at >= datetime('now', ?)
        ),
        prior_pmids AS (
            SELECT pmid FROM papers
            WHERE created_at >= datetime('now', ?)
              AND created_at < datetime('now', ?)
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
    rows = _q(
        f"""
        SELECT DISTINCT p.pmid
        FROM papers p
        JOIN relations r ON r.source_pmid = p.pmid
        JOIN entities e ON r.object_id = e.id
        WHERE e.name = ? AND e.type = ?
          {relation_filter}
          AND p.created_at >= datetime('now', ?)
        ORDER BY COALESCE(p.citation_count, 0) DESC, p.year DESC
        LIMIT 3
        """,
        (entity_name, entity_type, recent_start),
    )
    return [str(r["pmid"]) for r in rows]


def compute_hot_combos(
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Method×disease pairs active in the recent ingest window."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    top_n = limit if limit is not None else config.HOTSPOT_TOP_N
    recent_start, prior_start, prior_end = _window_params(window, prior)

    rows = _q(
        """
        WITH recent_pmids AS (
            SELECT pmid FROM papers WHERE created_at >= datetime('now', ?)
        ),
        prior_pmids AS (
            SELECT pmid FROM papers
            WHERE created_at >= datetime('now', ?)
              AND created_at < datetime('now', ?)
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
            "method": row["method"],
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
    """Limitations newly reported in the recent ingest window."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    top_n = limit if limit is not None else config.HOTSPOT_TOP_N
    recent_start, _, _ = _window_params(window, 0)

    rows = _q(
        """
        SELECT e.name AS limitation,
               COUNT(DISTINCT r.source_pmid) AS recent_cnt,
               ROUND(AVG(COALESCE(p.citation_count, 0)), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id = e.id AND e.type = 'Limitation'
        JOIN papers p ON r.source_pmid = p.pmid
        WHERE r.relation = 'REPORTS_LIMITATION'
          AND p.created_at >= datetime('now', ?)
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
    ingested = count_ingested_papers(window)

    methods = compute_emerging_entities("Method", window_days=window, prior_days=prior)
    diseases = compute_emerging_entities("Disease", window_days=window, prior_days=prior)
    tasks = compute_emerging_entities("Task", window_days=window, prior_days=prior)
    combos = compute_hot_combos(window_days=window, prior_days=prior)
    limitations = compute_emerging_limitations(window_days=window)

    for section in (methods, diseases, tasks):
        for row in section[:5]:
            row["top_pmids"] = _top_pmids_for_entity(
                row["name"], row["type"], window
            )

    return {
        "week_id": wid,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": window,
        "prior_window_days": prior,
        "papers_ingested": ingested,
        "emerging_methods": methods,
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
    """Cross weekly heating combos with literature gap status (hot ∩ unexplored)."""
    from analysis.gap_tools import tool_method_disease_combo_gap

    data = payload or compute_weekly_hotspots(
        window_days=window_days,
        prior_days=prior_days,
    )
    gaps_result = tool_method_disease_combo_gap(focus=focus)
    gap_index = {
        (g["method"], g["disease"]): g
        for g in gaps_result.get("gaps", [])
    }
    hot_methods = {r["name"] for r in data.get("emerging_methods", [])[:20]}
    hot_diseases = {r["name"] for r in data.get("heating_diseases", [])[:20]}
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []

    def _append(
        method: str,
        disease: str,
        *,
        lit_gap: str,
        paper_cnt: int,
        combo: dict[str, Any],
    ) -> None:
        key = (method, disease)
        if key in seen:
            return
        seen.add(key)
        hot_score = float(combo.get("emerging_score") or 0)
        lit_pts = literature_gap_points(lit_gap) if lit_gap in ("unexplored", "minimal") else 1
        rows.append({
            "method": method,
            "disease": disease,
            "literature_gap": lit_gap,
            "literature_paper_cnt": paper_cnt,
            "recent_hot_cnt": combo.get("recent_cnt", 0),
            "velocity": combo.get("velocity"),
            "gap_phase": combo.get("gap_phase"),
            "emerging_score": hot_score,
            "opportunity_score": round(hot_score + lit_pts, 2),
        })

    for combo in data.get("hot_combos", []):
        method, disease = combo["method"], combo["disease"]
        gap_row = gap_index.get((method, disease))
        lit_gap = gap_row["gap"] if gap_row else "active"
        paper_cnt = int(gap_row.get("paper_cnt", 0) if gap_row else combo.get("recent_cnt", 0))
        heating = combo.get("gap_phase") in ("heating", "nascent")
        if lit_gap in ("unexplored", "minimal") or heating:
            _append(method, disease, lit_gap=lit_gap, paper_cnt=paper_cnt, combo=combo)

    for gap_row in gaps_result.get("gaps", []):
        if gap_row.get("gap") not in ("unexplored", "minimal"):
            continue
        method, disease = gap_row["method"], gap_row["disease"]
        if method not in hot_methods and disease not in hot_diseases:
            continue
        _append(
            method,
            disease,
            lit_gap=gap_row["gap"],
            paper_cnt=int(gap_row.get("paper_cnt", 0)),
            combo={"emerging_score": 0, "recent_cnt": 0, "velocity": 0, "gap_phase": "nascent"},
        )

    rows.sort(key=lambda r: r["opportunity_score"], reverse=True)
    top_n = limit if limit is not None else min(20, config.HOTSPOT_TOP_N)
    return rows[:top_n]


def tool_emerging_gap_opportunities(focus: str | None = None) -> dict[str, Any]:
    rows = compute_emerging_gap_opportunities(focus=focus)
    desc = (
        "Weekly heating method×disease crossed with literature gap "
        "(opportunity_score = emerging_score + gap tier)"
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
    lines = [
        f"# Weekly Hotspot Report — {data['week_id']}",
        "",
        f"_Generated: {data['generated_at']}_",
        "",
        "## Window",
        "",
        f"- Recent ingest window: **{data['window_days']} days** (`papers.created_at`)",
        f"- Prior comparison window: **{data['prior_window_days']} days**",
        f"- Papers ingested in window: **{data['papers_ingested']}**",
        "",
        "> Velocity = (recent_cnt − prior_cnt) / max(prior_cnt, 1). "
        "Week-over-week uses **persisted snapshots**, not ingest windows alone.",
        "",
    ]
    lines.extend(_format_wow_section(comparison))
    lines.extend([
        "## Emerging Methods",
        "",
        _format_table(
            data["emerging_methods"],
            ["name", "recent_cnt", "prior_cnt", "velocity", "emerging_score", "avg_cite", "top_pmids"],
        ),
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
            ["method", "disease", "recent_cnt", "prior_cnt", "velocity", "gap_phase", "emerging_score"],
        ),
        "## New Limitations (recent ingest)",
        "",
        _format_table(
            data["new_limitations"],
            ["limitation", "recent_cnt", "avg_cite"],
        ),
    ])
    if data.get("emerging_gap_opportunities"):
        lines.extend([
            "## Emerging Gap Opportunities (hot × literature gap)",
            "",
            _format_table(
                data["emerging_gap_opportunities"],
                [
                    "method",
                    "disease",
                    "literature_gap",
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