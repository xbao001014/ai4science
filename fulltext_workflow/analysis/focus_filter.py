"""Shared keyword focus matching for SQL tools."""
from __future__ import annotations

from db.schema import get_conn

_TOKEN_SYNONYMS: dict[str, list[str]] = {
    "cancer": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm", "neoplasms"],
    "carcinoma": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm", "neoplasms"],
    "neoplasm": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm", "neoplasms"],
    "neoplasms": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm", "neoplasms"],
    "tumor": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm", "neoplasms"],
    "tumour": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm", "neoplasms"],
    "breast": ["breast", "mammary"],
    "lung": ["lung", "pulmonary"],
    "liver": ["liver", "hepatic", "hepatocellular"],
    "colon": ["colon", "colorectal", "rectal"],
    "nasopharyngeal": ["nasopharyngeal", "nasopharynx"],
    "npc": ["npc", "nasopharyngeal"],
}

_FOCUS_STOPWORDS = frozenset({"all", "any", "full", "corpus", "entire"})
_KEYWORD_STOPWORDS = _FOCUS_STOPWORDS | frozenset({
    "for", "of", "the", "and", "in", "with", "to", "a", "an", "on", "by",
    "from", "via", "using", "based", "into", "over", "under", "between",
})


def _escape_sql_like(value: str) -> str:
    return value.replace("'", "''")


def normalize_focus(focus: str | None) -> str | None:
    """Treat UI placeholders like 'All' as no focus filter."""
    if not focus or not str(focus).strip():
        return None
    f = str(focus).strip()
    if f.lower() in _FOCUS_STOPWORDS:
        return None
    return f


def focus_sql_clause(column: str, focus: str | None) -> str:
    """SQL AND-clause: disease concept expansion, else phrase + token synonyms."""
    focus = normalize_focus(focus)
    if not focus:
        return ""

    from analysis.disease_synonyms import concept_match_sql_clause, resolve_disease_concept

    concept = resolve_disease_concept(focus)
    if concept:
        return " AND (" + concept_match_sql_clause(column, concept) + ")"

    safe = _escape_sql_like(focus)
    clauses = [f"LOWER({column}) LIKE LOWER('%{safe}%')"]

    tokens = [
        t for t in focus.lower().split()
        if len(t) >= 2 and t not in _KEYWORD_STOPWORDS
    ]
    if len(tokens) >= 2:
        token_parts: list[str] = []
        for token in tokens:
            alts = _TOKEN_SYNONYMS.get(token, [token])
            token_parts.append(
                "("
                + " OR ".join(
                    f"LOWER({column}) LIKE LOWER('%{_escape_sql_like(alt)}%')"
                    for alt in alts
                )
                + ")"
            )
        clauses.append("(" + " AND ".join(token_parts) + ")")

    return " AND (" + " OR ".join(clauses) + ")"


def build_focus_expansion(
    focus: str | None,
    *,
    column: str = "e.name",
    max_phrases: int = 16,
) -> dict | None:
    """Structured synonym card for any focus (concept table or token fallback).

    Used by execute_kg_sql so free-form SQL can reuse the same expansions as
    curated tools — not disease-specific hardcoding.
    """
    focus = normalize_focus(focus)
    if not focus:
        return None

    from analysis.disease_synonyms import expand_focus_terms, resolve_disease_concept

    concept = resolve_disease_concept(focus)
    phrases: list[str] = []
    if concept:
        exp = expand_focus_terms(focus)
        seen: set[str] = set()
        for p in [
            exp.get("canonical") or "",
            *(exp.get("phrases") or []),
            *(exp.get("abbreviations") or []),
            *(exp.get("zh") or []),
        ]:
            key = str(p).strip().lower()
            if key and key not in seen:
                seen.add(key)
                phrases.append(str(p).strip())
        matched = True
        concept_id = exp.get("concept_id")
        canonical = exp.get("canonical")
        mode = "disease_concept"
    else:
        matched = False
        concept_id = None
        canonical = None
        mode = "token_synonyms"
        seen = {focus.lower()}
        phrases = [focus]
        tokens = [
            t for t in focus.lower().split()
            if len(t) >= 2 and t not in _KEYWORD_STOPWORDS
        ]
        for token in tokens:
            for alt in _TOKEN_SYNONYMS.get(token, [token]):
                if alt not in seen:
                    seen.add(alt)
                    phrases.append(alt)

    capped = phrases[: max(1, int(max_phrases))]
    like_parts = [
        f"LOWER({column}) LIKE LOWER('%{_escape_sql_like(p)}%')"
        for p in capped
    ]
    return {
        "raw": focus,
        "mode": mode,
        "matched_concept": matched,
        "concept_id": concept_id,
        "canonical": canonical,
        "phrases": capped,
        "suggested_sql_filter": f"({' OR '.join(like_parts)})" if like_parts else "",
        "usage": (
            "Reuse these phrases / suggested_sql_filter for disease or title filters "
            "instead of a single spelling. Same expansion path as curated focus tools."
        ),
    }


def focus_pmid_in_clause(pmid_column: str, focus: str | None) -> str:
    """
    Restrict to PMIDs whose paper targets a matching Disease entity or title.

    Use for limitation/method/task tools when focus is a disease/topic — do not
    filter Limitation or Method entity names with the focus string.
    """
    focus = normalize_focus(focus)
    if not focus:
        return ""

    disease_fc = focus_sql_clause("ed.name", focus)
    title_fc = focus_sql_clause("p.title", focus)
    return f""" AND {pmid_column} IN (
        SELECT DISTINCT rd.source_pmid
        FROM relations rd
        JOIN entities ed ON rd.object_id = ed.id AND ed.type = 'Disease'
        WHERE rd.relation = 'TARGETS_DISEASE'{disease_fc}
        UNION
        SELECT p.pmid FROM papers p WHERE 1=1{title_fc}
    )"""


def focus_like_param(focus: str) -> str:
    f = normalize_focus(focus)
    return f"%{(f or focus).strip()}%"


def meaningful_keyword_tokens(keyword: str) -> list[str]:
    """Drop stopwords; used for multi-token fallback on long gap titles."""
    return [
        t for t in keyword.lower().split()
        if len(t) >= 2 and t not in _KEYWORD_STOPWORDS
    ]


def keyword_bigrams(tokens: list[str]) -> list[str]:
    return [f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)]


def _token_score_expr(column: str, tokens: list[str]) -> str:
    if not tokens:
        return "0"
    parts = [
        f"CASE WHEN LOWER({column}) LIKE LOWER('%{_escape_sql_like(t)}%') THEN 1 ELSE 0 END"
        for t in tokens
    ]
    return "(" + " + ".join(parts) + ")"


def _keyword_min_hits(token_count: int) -> int:
    if token_count <= 1:
        return 1
    if token_count == 2:
        return 2
    return max(2, (token_count + 1) // 2)


def _phrase_or_expr(column: str, phrases: list[str]) -> str:
    if not phrases:
        return "0=1"
    parts = [
        f"LOWER({column}) LIKE LOWER('%{_escape_sql_like(p)}%')"
        for p in phrases
    ]
    return "(" + " OR ".join(parts) + ")"


def _q_pmids(sql: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [str(r[0]) for r in rows if r[0]]


def _pmids_full_phrase(keyword: str) -> list[str]:
    safe = _escape_sql_like(keyword.strip())
    return _q_pmids(f"""
        SELECT DISTINCT pmid FROM (
            SELECT p.pmid FROM papers p
            WHERE LOWER(p.title) LIKE LOWER('%{safe}%')
            UNION
            SELECT r.source_pmid AS pmid FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE LOWER(e.name) LIKE LOWER('%{safe}%')
        )
    """)


def _pmids_token_scored(tokens: list[str]) -> list[str]:
    min_hits = _keyword_min_hits(len(tokens))
    title_score = _token_score_expr("p.title", tokens)
    entity_score = _token_score_expr("e.name", tokens)
    return _q_pmids(f"""
        SELECT pmid FROM (
            SELECT p.pmid,
                {title_score} + COALESCE((
                    SELECT MAX({entity_score})
                    FROM relations r
                    JOIN entities e ON r.object_id = e.id
                    WHERE r.source_pmid = p.pmid
                ), 0) AS match_score
            FROM papers p
        )
        WHERE match_score >= {min_hits}
        ORDER BY match_score DESC
    """)


def _pmids_phrase_or(phrases: list[str]) -> list[str]:
    title_fc = _phrase_or_expr("p.title", phrases)
    entity_fc = _phrase_or_expr("e.name", phrases)
    return _q_pmids(f"""
        SELECT DISTINCT pmid FROM (
            SELECT p.pmid FROM papers p WHERE {title_fc}
            UNION
            SELECT r.source_pmid AS pmid FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE {entity_fc}
        )
    """)


def _pmids_disease_or_title(phrases: list[str]) -> list[str]:
    """Match title or TARGETS_DISEASE only — ignore Dataset/Task/Method names."""
    title_fc = _phrase_or_expr("p.title", phrases)
    disease_fc = _phrase_or_expr("e.name", phrases)
    return _q_pmids(f"""
        SELECT DISTINCT pmid FROM (
            SELECT p.pmid FROM papers p WHERE {title_fc}
            UNION
            SELECT r.source_pmid AS pmid FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type = 'Disease'
              AND r.relation = 'TARGETS_DISEASE'
              AND COALESCE(r.status, 'active') = 'active'
              AND {disease_fc}
        )
    """)


def _pmids_full_phrase_disease_or_title(keyword: str) -> list[str]:
    safe = _escape_sql_like(keyword.strip())
    return _q_pmids(f"""
        SELECT DISTINCT pmid FROM (
            SELECT p.pmid FROM papers p
            WHERE LOWER(p.title) LIKE LOWER('%{safe}%')
            UNION
            SELECT r.source_pmid AS pmid FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type = 'Disease'
              AND r.relation = 'TARGETS_DISEASE'
              AND COALESCE(r.status, 'active') = 'active'
              AND LOWER(e.name) LIKE LOWER('%{safe}%')
        )
    """)


def _pmids_token_scored_disease_or_title(tokens: list[str]) -> list[str]:
    min_hits = _keyword_min_hits(len(tokens))
    title_score = _token_score_expr("p.title", tokens)
    disease_score = _token_score_expr("e.name", tokens)
    return _q_pmids(f"""
        SELECT pmid FROM (
            SELECT p.pmid,
                {title_score} + COALESCE((
                    SELECT MAX({disease_score})
                    FROM relations r
                    JOIN entities e ON r.object_id = e.id
                    WHERE r.source_pmid = p.pmid
                      AND e.type = 'Disease'
                      AND r.relation = 'TARGETS_DISEASE'
                      AND COALESCE(r.status, 'active') = 'active'
                ), 0) AS match_score
            FROM papers p
        )
        WHERE match_score >= {min_hits}
        ORDER BY match_score DESC
    """)


def resolve_topic_pmids(keyword: str) -> tuple[list[str], str]:
    """
    Multi-level topic match: concept phrases → full phrase → token score → key bigrams.

    Returns (pmid list, strategy label).
    """
    kw = (keyword or "").strip()
    if not kw:
        return [], "empty"

    ranked, strategy = _rank_topic_papers(kw)
    return [row["pmid"] for row in ranked], strategy


def _rank_topic_papers(keyword: str) -> tuple[list[dict], str]:
    """Rank corpus papers across metadata and extracted entities.

    A recognized disease is one query unit rather than a short-circuit. Thus
    ``breast cancer segmentation`` must match both the disease and at least one
    technique/task term instead of returning every breast-cancer paper.
    """
    from analysis.retrieval import (
        build_retrieval_plan,
        candidate_phrases,
        full_query_matches,
        score_retrieval_fields,
    )

    plan = build_retrieval_plan(keyword)
    if not plan["units"]:
        return [], "no_match"
    # Use non-disease dimensions to narrow mixed queries. A disease concept can
    # have many aliases and otherwise turns the expensive entity aggregation
    # back into a near-full-corpus scan.
    method_units = [unit for unit in plan["units"] if unit["kind"] == "method"]
    candidate_units = method_units or [
        unit for unit in plan["units"] if unit["kind"] != "disease"
    ]
    candidate_plan = {"units": candidate_units or plan["units"]}
    phrases = candidate_phrases(candidate_plan)
    paper_text = """LOWER(
        COALESCE(p.title, '') || ' ' || COALESCE(p.abstract, '') || ' ' ||
        COALESCE(p.keywords, '') || ' ' || COALESCE(p.mesh_terms, '') || ' ' ||
        COALESCE(p.source_queries, ''))"""
    entity_text = "LOWER(COALESCE(e2.name, '') || ' ' || COALESCE(e2.aliases, ''))"
    paper_parts = [f"{paper_text} LIKE ?" for _ in phrases]
    entity_parts = [f"{entity_text} LIKE ?" for _ in phrases]
    params = tuple(f"%{phrase}%" for phrase in phrases) * 2
    with get_conn() as conn:
        rows = [dict(row) for row in conn.execute(
            f"""
            WITH candidate_pmids AS (
                SELECT p.pmid
                FROM papers p
                WHERE {" OR ".join(paper_parts)}
                UNION
                SELECT r2.source_pmid AS pmid
                FROM relations r2
                JOIN entities e2 ON e2.id = r2.object_id
                WHERE COALESCE(r2.status, 'active') = 'active'
                  AND ({" OR ".join(entity_parts)})
            )
            SELECT p.pmid, p.title, p.abstract, p.keywords, p.mesh_terms,
                   p.source_queries, p.year,
                   COALESCE((
                       SELECT GROUP_CONCAT(e.name || ' ' || COALESCE(e.aliases, ''), ' ')
                       FROM relations r
                       JOIN entities e ON e.id = r.object_id
                       WHERE r.source_pmid = p.pmid
                         AND COALESCE(r.status, 'active') = 'active'
                   ), '') AS entity_names
            FROM candidate_pmids c
            JOIN papers p ON p.pmid = c.pmid
            WHERE p.pmid IS NOT NULL
            """,
            params,
        ).fetchall()]

    ranked: list[dict] = []
    has_full_phrase = False
    for row in rows:
        detail = score_retrieval_fields(plan, row)
        if not detail["matched"]:
            continue
        row["retrieval_score"] = detail["score"]
        row["matched_query_units"] = detail["matched_units"]
        row["matched_fields"] = detail["matched_by_field"]
        row["full_phrase_match"] = full_query_matches(
            plan,
            row.get("title"), row.get("abstract"), row.get("keywords"),
            row.get("mesh_terms"), row.get("entity_names"),
        )
        has_full_phrase = has_full_phrase or row["full_phrase_match"]
        ranked.append(row)
    ranked.sort(key=lambda row: (
        -float(row["retrieval_score"]),
        -int(row.get("year") or 0),
        str(row["pmid"]),
    ))

    units = plan["units"]
    if (
        has_full_phrase
        and len(units) <= 4
        and all(unit["kind"] == "token" for unit in units)
    ):
        strategy = "full_phrase"
    elif len(units) == 1 and units[0]["kind"] == "disease":
        strategy = f"concept({plan['disease_concept_id']})"
    elif len(units) == 1 and units[0]["kind"] == "method":
        strategy = f"method_concept({units[0]['canonical']})"
    elif any(unit["kind"] in {"disease", "method"} for unit in units):
        strategy = "hybrid_score(" + ",".join(unit["canonical"] for unit in units) + ")"
    else:
        strategy = "token_score(" + ",".join(unit["canonical"] for unit in units) + ")"
    return ranked, strategy


def resolve_v03_topic_pmids(keyword: str) -> tuple[list[str], str]:
    """
    V-03 topic match: same fallback ladder as resolve_topic_pmids, but only via
    paper title or TARGETS_DISEASE (never Dataset/Task/Method entity names).
    """
    kw = (keyword or "").strip()
    if not kw:
        return [], "empty"

    from analysis.disease_synonyms import expand_focus_terms, resolve_disease_concept

    concept = resolve_disease_concept(kw)
    if concept:
        exp = expand_focus_terms(kw)
        phrases = exp.get("phrases") or []
        if phrases:
            pmids = _pmids_disease_or_title(phrases)
            if pmids:
                return pmids, f"disease_or_title_concept({exp['concept_id']})"

    pmids = _pmids_full_phrase_disease_or_title(kw)
    if pmids:
        return pmids, "disease_or_title_full_phrase"

    tokens = meaningful_keyword_tokens(kw)
    if len(tokens) >= 2:
        pmids = _pmids_token_scored_disease_or_title(tokens)
        if pmids:
            return pmids, f"disease_or_title_token_score({','.join(tokens)})"
        bigrams = keyword_bigrams(tokens)
        if bigrams:
            pmids = _pmids_disease_or_title(bigrams)
            if pmids:
                shown = "; ".join(bigrams[:3])
                if len(bigrams) > 3:
                    shown += "..."
                return pmids, f"disease_or_title_key_phrases({shown})"

    return [], "no_match"


def topic_keyword_pmid_in_clause(pmid_column: str, keyword: str) -> str:
    """Restrict a query to papers matching keyword (with fallback strategies)."""
    pmids, _ = resolve_topic_pmids(keyword)
    if not pmids:
        return " AND 0=1"
    quoted = ", ".join(f"'{_escape_sql_like(p)}'" for p in pmids)
    return f" AND {pmid_column} IN ({quoted})"


_DEFAULT_PAPER_COLUMNS = (
    "p.title, p.year, p.journal_name, p.study_type, "
    "p.abstract, p.full_text_status, p.pmid"
)


def search_papers_for_topic(
    keyword: str,
    *,
    extra_where: str = "",
    limit: int = 30,
    select_columns: str = _DEFAULT_PAPER_COLUMNS,
) -> tuple[list[dict], str]:
    """Return papers for a gap keyword; falls back when the full title matches nothing."""
    ranked, strategy = _rank_topic_papers(keyword)
    if not ranked:
        return [], strategy

    pmids = [str(row["pmid"]) for row in ranked]
    score_by_pmid = {str(row["pmid"]): row for row in ranked}
    quoted = ", ".join(f"'{_escape_sql_like(p)}'" for p in pmids)

    sql = f"""
        SELECT DISTINCT {select_columns}
        FROM papers p
        WHERE p.pmid IN ({quoted}){extra_where}
    """
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    out = [dict(r) for r in rows]
    rank_by_pmid = {pmid: index for index, pmid in enumerate(pmids)}
    out.sort(key=lambda row: rank_by_pmid.get(str(row.get("pmid")), len(pmids)))
    out = out[:limit]
    for row in out:
        detail = score_by_pmid.get(str(row.get("pmid")), {})
        row["retrieval_score"] = detail.get("retrieval_score", 0)
        row["matched_query_units"] = detail.get("matched_query_units", [])
        row["matched_fields"] = detail.get("matched_fields", {})
    return out, strategy


def debate_or_corpus_papers(
    debate_rows: list[dict],
    focus: str | None,
    *,
    limit: int = 50,
) -> tuple[list[dict], str]:
    """
    Prefer paper rows already harvested from debate tool results.

    When those are empty (common: gap tools return aggregates without titles),
    fall back to corpus search for the sidebar/research focus so Literature
    is not stuck at 0 while focus_subset.papers > 0.
    """
    if debate_rows:
        return debate_rows[:limit], "debate_tools"
    foc = normalize_focus(focus)
    if not foc:
        return [], "empty"
    rows, strategy = search_papers_for_topic(foc, limit=limit)
    if not rows:
        return [], f"corpus_{strategy}"
    return rows, f"corpus_{strategy}"
