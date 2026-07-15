"""Shared keyword focus matching for SQL tools."""
from __future__ import annotations

from db.schema import get_conn

_TOKEN_SYNONYMS: dict[str, list[str]] = {
    "cancer": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm"],
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
    """SQL AND-clause: full phrase OR token synonyms (e.g. breast + cancer|carcinoma)."""
    focus = normalize_focus(focus)
    if not focus:
        return ""

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


def resolve_topic_pmids(keyword: str) -> tuple[list[str], str]:
    """
    Multi-level topic match: full phrase → token score → key bigrams.

    Returns (pmid list, strategy label).
    """
    kw = (keyword or "").strip()
    if not kw:
        return [], "empty"

    pmids = _pmids_full_phrase(kw)
    if pmids:
        return pmids, "full_phrase"

    tokens = meaningful_keyword_tokens(kw)
    if len(tokens) >= 2:
        pmids = _pmids_token_scored(tokens)
        if pmids:
            return pmids, f"token_score({','.join(tokens)})"
        bigrams = keyword_bigrams(tokens)
        if bigrams:
            pmids = _pmids_phrase_or(bigrams)
            if pmids:
                shown = "; ".join(bigrams[:3])
                if len(bigrams) > 3:
                    shown += "..."
                return pmids, f"key_phrases({shown})"

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
    pmids, strategy = resolve_topic_pmids(keyword)
    if not pmids:
        return [], strategy

    quoted = ", ".join(f"'{_escape_sql_like(p)}'" for p in pmids)
    order_by = "p.year DESC"
    score_select = ""

    if strategy.startswith("token_score"):
        tokens = meaningful_keyword_tokens(keyword)
        title_score = _token_score_expr("p.title", tokens)
        entity_score = _token_score_expr("e.name", tokens)
        score_select = f""",
            ({title_score} + COALESCE((
                SELECT MAX({entity_score}) FROM relations r
                JOIN entities e ON r.object_id = e.id
                WHERE r.source_pmid = p.pmid
            ), 0)) AS match_score"""
        order_by = "match_score DESC, p.year DESC"

    sql = f"""
        SELECT DISTINCT {select_columns}{score_select}
        FROM papers p
        WHERE p.pmid IN ({quoted}){extra_where}
        ORDER BY {order_by}
        LIMIT {limit}
    """
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows], strategy


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
