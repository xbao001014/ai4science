"""Gap analysis tools for the full-text workflow (SQL + registry for LLM agents)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import config
from analysis.focus_filter import focus_pmid_in_clause, focus_sql_clause, normalize_focus
from analysis.impact_scoring import aggregate_paper_impact
from db.schema import get_conn

REPORT_PATH = f"{config.OUTPUT_DIR}/gap_report.md"


def _q(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _focus_clause(column: str, focus: str | None) -> str:
    return focus_sql_clause(column, focus)


def tool_author_stated_gaps(focus: str | None = None) -> dict:
    fc = _focus_clause("e.name", focus)
    rows = _q(f"""
        SELECT e.name AS limitation,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               GROUP_CONCAT(DISTINCT r.evidence_section) AS sections,
               GROUP_CONCAT(DISTINCT r.evidence_quote) AS quotes
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        WHERE (r.relation IN ('REPORTS_LIMITATION')
           OR (e.type='Limitation' AND r.relation='REPORTS_LIMITATION'))
           {fc}
        GROUP BY e.id
        ORDER BY paper_cnt DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    if not rows:
        rows = _q(f"""
            SELECT e.name AS limitation,
                   COUNT(DISTINCT r.source_pmid) AS paper_cnt,
                   GROUP_CONCAT(DISTINCT r.evidence_section) AS sections,
                   GROUP_CONCAT(DISTINCT r.evidence_quote) AS quotes
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type='Limitation' {fc}
            GROUP BY e.id
            ORDER BY paper_cnt DESC
            LIMIT {config.TOOL_TOP_N}
        """)
    desc = "Author-stated research limitations/gaps from full-text extraction"
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "data": rows}


def tool_disease_task_coverage(focus: str | None = None) -> dict:
    fc = _focus_clause("e_d.name", focus)
    rows = _q(f"""
        SELECT e_d.name AS disease,
               COUNT(DISTINCT r_d.source_pmid) AS paper_cnt,
               COUNT(DISTINCT e_t.name) AS task_variety,
               GROUP_CONCAT(DISTINCT e_t.name) AS tasks
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id=e_d.id
        LEFT JOIN relations r_t ON r_d.source_pmid=r_t.source_pmid
            AND r_t.relation='PERFORMS_TASK'
        LEFT JOIN entities e_t ON r_t.object_id=e_t.id
        WHERE r_d.relation='TARGETS_DISEASE' AND e_d.type='Disease'
          {fc}
        GROUP BY e_d.id
        HAVING paper_cnt >= 1
        ORDER BY task_variety ASC, paper_cnt DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    desc = "Disease-task coverage (low task_variety = more gaps)"
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "data": rows}


def tool_corpus_focus_coverage(focus: str | None = None) -> dict:
    """Corpus scale for a focus topic vs full KG (call before gap claims)."""
    from db.schema import db_stats

    global_stats = db_stats()
    f = normalize_focus(focus)
    if not f:
        return {
            "description": (
                "Full-corpus statistics (no focus filter). "
                "Provide focus to compare topic subset vs whole KG."
            ),
            "focus": None,
            "global": {
                "papers": global_stats["papers"],
                "extracted": global_stats["extracted"],
                "fulltext_available": global_stats["fulltext_available"],
                "relations_fulltext": global_stats["relations_fulltext"],
            },
            "focus_subset": None,
            "coverage_ratio": None,
            "analysis_ready": False,
            "warnings": ["No focus keyword — subset stats not computed."],
        }

    pmid_clause = focus_pmid_in_clause("p.pmid", f)
    row = _q(f"""
        SELECT COUNT(DISTINCT p.pmid) AS focus_papers,
               SUM(CASE WHEN p.extraction_done = 1 THEN 1 ELSE 0 END) AS focus_extracted
        FROM papers p
        WHERE 1=1 {pmid_clause}
    """)
    counts = row[0] if row else {"focus_papers": 0, "focus_extracted": 0}
    focus_papers = int(counts.get("focus_papers") or 0)
    focus_extracted = int(counts.get("focus_extracted") or 0)

    lim_cnt = _q(f"""
        SELECT COUNT(*) AS cnt FROM relations r
        WHERE r.relation = 'REPORTS_LIMITATION'
        {focus_pmid_in_clause('r.source_pmid', f)}
    """)
    method_cnt = _q(f"""
        SELECT COUNT(DISTINCT e.id) AS cnt
        FROM relations r
        JOIN entities e ON r.object_id = e.id AND e.type = 'Method'
        WHERE r.relation = 'APPLIES_METHOD'
        {focus_pmid_in_clause('r.source_pmid', f)}
    """)
    disease_cnt = _q(f"""
        SELECT COUNT(DISTINCT e.id) AS cnt
        FROM relations r
        JOIN entities e ON r.object_id = e.id AND e.type = 'Disease'
        WHERE r.relation = 'TARGETS_DISEASE'
        {focus_sql_clause('e.name', f)}
    """)
    top_diseases = _q(f"""
        SELECT e.name, COUNT(DISTINCT r.source_pmid) AS paper_cnt
        FROM relations r
        JOIN entities e ON r.object_id = e.id AND e.type = 'Disease'
        WHERE r.relation = 'TARGETS_DISEASE' {focus_sql_clause('e.name', f)}
        GROUP BY e.id
        ORDER BY paper_cnt DESC
        LIMIT 5
    """)

    ratio = round(focus_papers / max(global_stats["papers"], 1), 4)
    warnings: list[str] = []
    if focus_papers < 30:
        warnings.append(
            f"Focus subset has only {focus_papers} papers — "
            "temporal/combo statistics are low-confidence; do not cite corpus-wide totals."
        )
    if focus_papers == 0:
        warnings.append("No papers match this focus — gaps may reflect missing extraction, not true absence.")

    return {
        "description": (
            f"Corpus coverage for focus '{f}' vs full KG. "
            "Use focus_subset counts in gap claims; never substitute global.papers."
        ),
        "focus": f,
        "global": {
            "papers": global_stats["papers"],
            "extracted": global_stats["extracted"],
            "fulltext_available": global_stats["fulltext_available"],
        },
        "focus_subset": {
            "papers": focus_papers,
            "extracted": focus_extracted,
            "limitation_relations": int(lim_cnt[0]["cnt"]) if lim_cnt else 0,
            "method_entities": int(method_cnt[0]["cnt"]) if method_cnt else 0,
            "disease_entities": int(disease_cnt[0]["cnt"]) if disease_cnt else 0,
            "top_diseases": top_diseases,
        },
        "coverage_ratio": ratio,
        "analysis_ready": focus_papers >= 30,
        "warnings": warnings,
    }


def tool_method_disease_combo_gap(focus: str | None = None) -> dict:
    f = normalize_focus(focus)
    df = focus_sql_clause("e.name", f)
    mf = focus_pmid_in_clause("r.source_pmid", f) if f else ""
    top_methods = _q(f"""
        SELECT e.name
        FROM relations r JOIN entities e ON r.object_id=e.id
        WHERE e.type='Method' AND r.relation='APPLIES_METHOD' {mf}
        GROUP BY e.id ORDER BY COUNT(*) DESC LIMIT {config.TOOL_TOP_N}
    """)
    method_names = [r["name"] for r in top_methods]

    top_diseases = _q(f"""
        SELECT e.name
        FROM relations r JOIN entities e ON r.object_id=e.id
        WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE' {df}
        GROUP BY e.id ORDER BY COUNT(*) DESC LIMIT {config.TOOL_TOP_N}
    """)
    disease_names = [r["name"] for r in top_diseases]

    if not method_names or not disease_names:
        return {"description": "Method-disease combination gaps", "gaps": []}

    rows = _q("""
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
        SELECT pm.method, pd.disease, COUNT(*) AS cnt
        FROM pm JOIN pd ON pm.source_pmid=pd.source_pmid
        GROUP BY pm.method, pd.disease
    """)
    existing = {(r["method"], r["disease"]): r["cnt"] for r in rows}
    gaps = []
    for m in method_names:
        for d in disease_names:
            cnt = existing.get((m, d), 0)
            if cnt == 0:
                gaps.append({"method": m, "disease": d, "paper_cnt": 0, "gap": "unexplored"})
            elif cnt <= 2:
                gaps.append({"method": m, "disease": d, "paper_cnt": cnt, "gap": "minimal"})
    desc = "Hot method x hot disease combination gaps"
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "gaps": gaps[:40]}


def tool_metric_evidence_quality(focus: str | None = None) -> dict:
    fc = _focus_clause("e.name", focus)
    rows = _q(f"""
        SELECT e.name AS metric,
               r.metric_value,
               r.evidence_section,
               r.extraction_granularity,
               r.source_pmid,
               r.evidence_quote
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        WHERE r.relation='ACHIEVES_METRIC' AND e.type='Metric'
          AND r.evidence_section='results' {fc}
        ORDER BY r.source_pmid
        LIMIT {config.TOOL_TOP_N}
    """)
    all_metrics = _q(f"""
        SELECT e.name AS metric,
               r.metric_value,
               r.evidence_section,
               r.extraction_granularity,
               r.source_pmid
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        WHERE r.relation='ACHIEVES_METRIC' AND e.type='Metric' {fc}
        LIMIT {config.TOOL_TOP_N}
    """)
    desc = "Results-section backed metrics vs all extracted metrics"
    if focus:
        desc += f" (focus: {focus})"
    return {
        "description": desc,
        "results_backed": rows,
        "all_metrics": all_metrics,
    }


def tool_limitation_temporal_profile(focus: str | None = None) -> dict:
    from analysis.focus_filter import normalize_focus
    from analysis.gap_lifecycle import compute_limitation_temporal_profiles
    from db.schema import get_limitation_temporal_rows

    f = normalize_focus(focus)
    if f:
        rows = compute_limitation_temporal_profiles(focus=f)[: config.TOOL_TOP_N]
    else:
        cached = get_limitation_temporal_rows(focus=None, limit=config.TOOL_TOP_N)
        rows = cached if cached else compute_limitation_temporal_profiles(focus=None)[
            : config.TOOL_TOP_N
        ]
    desc = (
        "Limitation temporal profile: first/last year, recent_ratio, temporal_status "
        "(persistent/emerging/declining/stable)"
    )
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "data": rows}


def tool_combo_gap_temporal(focus: str | None = None) -> dict:
    from analysis.gap_lifecycle import compute_combo_gap_temporal

    rows = compute_combo_gap_temporal(focus=focus)
    desc = (
        "Method×disease combos with first/last paper year and gap_phase "
        "(unexplored/nascent/active/dormant)"
    )
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "data": rows}


def tool_limitation_gap_status(focus: str | None = None) -> dict:
    from analysis.gap_lifecycle import compute_limitation_gap_status

    rows = compute_limitation_gap_status(focus=focus)
    desc = (
        "Limitation temporal profile plus heuristic resolution_signal "
        "(none/weak/moderate follow-up research on shared disease/task/method)"
    )
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "data": rows}


def _paper_impact_join() -> str:
    return """
        LEFT JOIN papers p ON r.source_pmid = p.pmid
        LEFT JOIN journals j ON p.journal_id = j.id
    """


def tool_limitation_impact_rank(focus: str | None = None) -> dict:
    """Author-stated limitations ranked by paper count and citation/IF impact."""
    fc = _focus_clause("e.name", focus)
    rows = _q(f"""
        SELECT e.name AS limitation,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(COALESCE(p.citation_count, 0)), 1) AS avg_cite,
               ROUND(AVG(COALESCE(j.impact_factor, 0)), 2) AS avg_if,
               ROUND(AVG(1.0 * COALESCE(p.citation_count, 0)
                     / MAX(2026 - COALESCE(p.year, {config.SEARCH_YEAR_END}), 1)), 2) AS avg_cite_per_year,
               SUM(CASE WHEN p.study_type != 'review' THEN 1 ELSE 0 END) AS non_review_cnt
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        {_paper_impact_join()}
        WHERE (r.relation = 'REPORTS_LIMITATION'
           OR (e.type = 'Limitation' AND r.relation = 'REPORTS_LIMITATION'))
          {fc}
        GROUP BY e.id
        HAVING paper_cnt >= 1
        ORDER BY paper_cnt * AVG(COALESCE(p.citation_count, 0)) DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    for row in rows:
        score = aggregate_paper_impact([{
            "citation_count": row.get("avg_cite"),
            "year": config.SEARCH_YEAR_END,
            "impact_factor": row.get("avg_if"),
            "quartile": "Q1" if (row.get("avg_if") or 0) >= 5 else "",
        }])
        row["impact_score"] = score["impact_score"]
        row["impact_tier"] = score["impact_tier"]
    desc = "Limitations ranked by frequency × citation impact (S2 + IF when enriched)"
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "data": rows}


def tool_hotspot_entities(focus: str | None = None) -> dict:
    fc = _focus_clause("e.name", focus)
    rows = _q(f"""
        SELECT e.name, e.type,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(COALESCE(p.citation_count, 0)), 1) AS avg_cite,
               ROUND(AVG(COALESCE(j.impact_factor, 0)), 2) AS avg_if,
               ROUND(COUNT(DISTINCT r.source_pmid) * AVG(COALESCE(p.citation_count, 0)), 0) AS heat_score
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        LEFT JOIN papers p ON r.source_pmid = p.pmid
        LEFT JOIN journals j ON p.journal_id = j.id
        WHERE 1=1 {fc}
        GROUP BY e.id
        HAVING paper_cnt >= 2
        ORDER BY heat_score DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    desc = "Hot entities: paper_cnt × avg_citation (requires enrich-s2)"
    if focus:
        desc += f" (focus: {focus})"
    return {"description": desc, "data": rows}


def tool_recent_highcite_papers(focus: str | None = None) -> dict:
    focus_sql = ""
    if focus:
        focus_sql = f"""
        AND p.pmid IN (
            SELECT DISTINCT r.source_pmid FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE LOWER(e.name) LIKE LOWER('%{focus}%')
        )"""
    rows = _q(f"""
        SELECT p.title, p.year, p.study_type, p.citation_count,
               p.journal_name, j.impact_factor, j.quartile,
               ROUND(1.0 * COALESCE(p.citation_count, 0)
                     / MAX(2026 - COALESCE(p.year, {config.SEARCH_YEAR_END}), 1), 1) AS cite_per_year
        FROM papers p
        LEFT JOIN journals j ON p.journal_id = j.id
        WHERE p.year >= {config.SEARCH_YEAR_START}
          AND COALESCE(p.citation_count, 0) >= 0 {focus_sql}
        ORDER BY cite_per_year DESC, p.citation_count DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "Recent papers ranked by cite_per_year (frontier anchors)", "data": rows}


def _combo_support_papers(method: str, disease: str) -> list[dict]:
    return _q(
        """
        WITH pm AS (
            SELECT r.source_pmid FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type = 'Method' AND e.name = ? AND r.relation = 'APPLIES_METHOD'
        ),
        pd AS (
            SELECT r.source_pmid FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type = 'Disease' AND e.name = ? AND r.relation = 'TARGETS_DISEASE'
        )
        SELECT p.pmid, p.year, p.citation_count, j.impact_factor, j.quartile
        FROM papers p
        JOIN pm ON p.pmid = pm.source_pmid
        JOIN pd ON p.pmid = pd.source_pmid
        LEFT JOIN journals j ON p.journal_id = j.id
        """,
        (method, disease),
    )


def tool_literature_impact_priority_matrix(focus: str | None = None) -> dict:
    """Literature gap × citation/IF impact (no mock data dimension)."""
    combo = tool_method_disease_combo_gap(focus=focus)
    rows: list[dict] = []
    for gap in combo.get("gaps", [])[:30]:
        method = gap.get("method", "")
        disease = gap.get("disease", "")
        support = _combo_support_papers(method, disease) if gap.get("paper_cnt", 0) > 0 else []
        impact = aggregate_paper_impact(support)
        lit = gap.get("gap", "")
        rows.append({
            "method": method,
            "disease": disease,
            "literature_gap": lit,
            "literature_paper_cnt": gap.get("paper_cnt", 0),
            **impact,
            "gap_priority_score": round(
                (3 if lit == "unexplored" else 2 if lit == "minimal" else 1)
                + impact["impact_score"],
                2,
            ),
        })
    rows.sort(key=lambda r: r["gap_priority_score"], reverse=True)
    return {
        "description": "Method×disease gaps weighted by supporting-paper citations/IF",
        "data": rows,
    }


# ── Tool registry for LLM agents ─────────────────────────────────────────────

SQL_TOOLS: dict[str, Callable[..., dict]] = {
    "corpus_focus_coverage": tool_corpus_focus_coverage,
    "author_stated_gaps": tool_author_stated_gaps,
    "limitation_impact_rank": tool_limitation_impact_rank,
    "limitation_temporal_profile": tool_limitation_temporal_profile,
    "combo_gap_temporal": tool_combo_gap_temporal,
    "limitation_gap_status": tool_limitation_gap_status,
    "hotspot_entities": tool_hotspot_entities,
    "recent_highcite_papers": tool_recent_highcite_papers,
    "literature_impact_priority_matrix": tool_literature_impact_priority_matrix,
    "disease_task_coverage": tool_disease_task_coverage,
    "method_disease_combo_gap": tool_method_disease_combo_gap,
    "metric_evidence_quality": tool_metric_evidence_quality,
}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "corpus_focus_coverage",
            "description": (
                "Compare focus-topic paper counts vs full KG. "
                "Call FIRST when a focus is set — never cite global.papers for topic-specific claims."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "Disease/topic keyword"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "author_stated_gaps",
            "description": (
                "Retrieve author-stated limitations/gaps from full-text extraction "
                "(REPORTS_LIMITATION relations with evidence_section and evidence_quote)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "Optional keyword filter"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "limitation_impact_rank",
            "description": (
                "Author-stated limitations with paper_cnt, avg_cite, avg_if, impact_score/tier. "
                "Use for high-consensus gaps backed by influential papers."
            ),
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "limitation_temporal_profile",
            "description": (
                "Limitation temporal profile with first_year, last_year, recent_ratio, "
                "temporal_status (persistent/emerging/declining/stable), impact_tier."
            ),
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "combo_gap_temporal",
            "description": (
                "Method×disease combination gaps with first/last paper year and "
                "gap_phase (unexplored/nascent/active/dormant)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "limitation_gap_status",
            "description": (
                "Limitation temporal profile plus resolution_signal (none/weak/moderate) "
                "based on later papers sharing disease/task/method themes."
            ),
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hotspot_entities",
            "description": (
                "Entities ranked by heat_score = paper_cnt × avg_citation. "
                "Requires enrich-s2 for citation_count."
            ),
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_highcite_papers",
            "description": "Recent corpus papers ranked by cite_per_year (frontier references).",
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "literature_impact_priority_matrix",
            "description": (
                "Method×disease gaps with citation/IF impact_score and gap_priority_score."
            ),
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disease_task_coverage",
            "description": (
                "Disease-task coverage matrix. Low task_variety relative to paper_cnt "
                "indicates under-explored task space for a disease."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "Optional disease keyword"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "method_disease_combo_gap",
            "description": (
                "Hot method x hot disease combination gaps. "
                "paper_cnt=0 means unexplored; <=2 means minimal research."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "Optional method/disease keyword"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "metric_evidence_quality",
            "description": (
                "Compare metrics backed by results-section evidence vs all extracted metrics. "
                "Includes evidence_quote for full-text provenance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "Optional metric keyword"},
                },
                "required": [],
            },
        },
    },
]


def _format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "_No data._\n"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, sep]
    for row in rows[:20]:
        lines.append("| " + " | ".join(str(row.get(c, ""))[:80] for c in columns) + " |")
    return "\n".join(lines) + "\n"


def generate_report() -> str:
    from db.schema import db_stats

    stats = db_stats()
    author_gaps = tool_author_stated_gaps()
    temporal = tool_limitation_temporal_profile()
    gap_status = tool_limitation_gap_status()
    disease_task = tool_disease_task_coverage()
    combo_gap = tool_method_disease_combo_gap()
    combo_temporal = tool_combo_gap_temporal()
    metric_q = tool_metric_evidence_quality()

    persistent_rows = [
        r for r in temporal["data"] if r.get("temporal_status") == "persistent"
    ][:20]
    declining_rows = [
        r for r in temporal["data"] if r.get("temporal_status") == "declining"
    ][:10]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Gap Report — Pathology AI ({config.SEARCH_YEAR_START}-{config.SEARCH_YEAR_END})",
        "",
        f"_Generated: {now}_",
        "",
        "## Corpus Statistics",
        "",
        f"- Papers: {stats['papers']}",
        f"- Full text available: {stats['fulltext_available']}",
        f"- Full text unavailable: {stats['fulltext_unavailable']}",
        f"- Extracted: {stats['extracted']}",
        f"- Relations (fulltext): {stats['relations_fulltext']}",
        f"- Relations (abstract): {stats['relations_abstract']}",
        "",
        "## Author-Stated Gaps (Limitations)",
        "",
        _format_table(
            author_gaps["data"],
            ["limitation", "paper_cnt", "sections"],
        ),
        "## Limitation Temporal Profile (persistent)",
        "",
        _format_table(
            persistent_rows,
            [
                "limitation_name",
                "first_year",
                "last_year",
                "paper_cnt",
                "recent_ratio",
                "temporal_status",
            ],
        ),
        "",
        "### Declining limitations (possibly addressed)",
        "",
        _format_table(
            declining_rows,
            [
                "limitation_name",
                "first_year",
                "last_year",
                "paper_cnt",
                "temporal_status",
            ],
        ),
        "",
        "## Limitation Gap Status (follow-up signal)",
        "",
        _format_table(
            gap_status["data"],
            [
                "limitation_name",
                "temporal_status",
                "resolution_signal",
                "followup_paper_cnt",
                "first_followup_year",
            ],
        ),
        "## Method-Disease Combo Temporal",
        "",
        _format_table(
            combo_temporal["data"],
            [
                "method",
                "disease",
                "paper_cnt",
                "first_paper_year",
                "last_paper_year",
                "gap_phase",
            ],
        ),
        "## Disease-Task Coverage (low variety = gap)",
        "",
        _format_table(
            disease_task["data"],
            ["disease", "paper_cnt", "task_variety", "tasks"],
        ),
        "## Method-Disease Combo Gaps",
        "",
        _format_table(
            combo_gap.get("gaps", []),
            ["method", "disease", "paper_cnt", "gap"],
        ),
        "## Metric Evidence Quality",
        "",
        "### Results-section backed metrics",
        "",
        _format_table(
            metric_q["results_backed"],
            ["metric", "metric_value", "source_pmid", "extraction_granularity"],
        ),
        "",
        "### All extracted metrics",
        "",
        _format_table(
            metric_q["all_metrics"],
            ["metric", "metric_value", "evidence_section", "extraction_granularity"],
        ),
    ]

    import os
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[Analyze] Report written to {REPORT_PATH}")
    return REPORT_PATH


def build_gap_tools_registry() -> tuple[dict[str, Any], list[dict]]:
    """Merge SQL + graph tools after graph_tools is importable."""
    from analysis.graph_tools import GRAPH_TOOLS, GRAPH_TOOL_SCHEMAS

    tools: dict[str, Any] = {**SQL_TOOLS, **GRAPH_TOOLS}
    schemas = TOOL_SCHEMAS + GRAPH_TOOL_SCHEMAS
    return tools, schemas
