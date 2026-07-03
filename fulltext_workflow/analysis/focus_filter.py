"""Shared keyword focus matching for SQL tools."""
from __future__ import annotations

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

    tokens = [t for t in focus.lower().split() if len(t) >= 2]
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
