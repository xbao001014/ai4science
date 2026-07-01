"""Load JATS-channel extraction results from main DB (read-only)."""
from __future__ import annotations

import sqlite3
from typing import Any

from compare_test.config import MAIN_DB_PATH


def get_extracted_papers(limit: int = 30, fulltext_only: bool = True) -> list[dict[str, Any]]:
    """Papers already extracted in main workflow (same order as extraction queue)."""
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        sql = """
            SELECT id, pmid, doi, title, abstract, full_text_status, pmc_id, study_type
            FROM papers
            WHERE extraction_done = 1
              AND abstract IS NOT NULL AND abstract != ''
        """
        if fulltext_only:
            sql += " AND full_text_status = 'available'"
        sql += """
            ORDER BY year DESC, id
            LIMIT ?
        """
        return [dict(r) for r in conn.execute(sql, (limit,)).fetchall()]


def load_jats_triples(pmid: str) -> list[dict[str, Any]]:
    """Relations extracted via JATS/XML channel for one paper."""
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT r.relation, r.metric_value, r.evidence_section, r.evidence_quote,
                   r.extraction_granularity, r.polarity,
                   e.name AS object_name, e.type AS object_type
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE r.source_pmid = ?
            ORDER BY r.relation, e.type, e.name
            """,
            (pmid,),
        ).fetchall()
    return [dict(r) for r in rows]


def summarize_triples(triples: list[dict[str, Any]]) -> dict[str, Any]:
    rel_counts: dict[str, int] = {}
    section_counts: dict[str, int] = {}
    entities: set[tuple[str, str]] = set()
    limitations = 0
    with_quote = 0

    for t in triples:
        rel = t.get("relation", "")
        rel_counts[rel] = rel_counts.get(rel, 0) + 1
        sec = t.get("evidence_section") or "unknown"
        section_counts[sec] = section_counts.get(sec, 0) + 1
        entities.add((t.get("object_name", "").lower(), t.get("object_type", "")))
        if rel == "REPORTS_LIMITATION":
            limitations += 1
        if t.get("evidence_quote"):
            with_quote += 1

    return {
        "triple_count": len(triples),
        "entity_count": len(entities),
        "limitation_count": limitations,
        "with_evidence_quote": with_quote,
        "relation_counts": rel_counts,
        "section_counts": section_counts,
        "entities": sorted(entities),
    }
