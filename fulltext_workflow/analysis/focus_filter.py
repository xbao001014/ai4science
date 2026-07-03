"""Shared keyword focus matching for SQL tools."""
from __future__ import annotations

_TOKEN_SYNONYMS: dict[str, list[str]] = {
    "cancer": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm"],
    "breast": ["breast", "mammary"],
    "lung": ["lung", "pulmonary"],
    "liver": ["liver", "hepatic", "hepatocellular"],
    "colon": ["colon", "colorectal", "rectal"],
}


def _escape_sql_like(value: str) -> str:
    return value.replace("'", "''")


def focus_sql_clause(column: str, focus: str | None) -> str:
    """SQL AND-clause: full phrase OR token synonyms (e.g. breast + cancer|carcinoma)."""
    if not focus:
        return ""
    focus = focus.strip()
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


def focus_like_param(focus: str) -> str:
    return f"%{focus.strip()}%"
