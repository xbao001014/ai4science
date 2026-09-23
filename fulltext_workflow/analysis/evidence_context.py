"""Resolve a debate evidence record back to a bounded source-text context.

This module is deliberately read-only.  Missing full text is represented in the
returned record instead of turning a usable debate result into an exception.
"""
from __future__ import annotations

from typing import Any

from db.schema import get_conn, init_db
from extractor.evidence_grounding import locate_quote


def _text(value: Any) -> str:
    return str(value or "").strip()


def _context_slice(
    source: str,
    span: tuple[int, int],
    *,
    before_chars: int,
    after_chars: int,
) -> tuple[str, str, str]:
    start, end = span
    return (
        source[max(0, start - before_chars):start].strip(),
        source[start:end],
        source[end:min(len(source), end + after_chars)].strip(),
    )


def load_evidence_context(
    record: dict[str, Any],
    *,
    before_chars: int = 600,
    after_chars: int = 1000,
) -> dict[str, Any]:
    """Return stable source metadata and literal context for one evidence record."""
    pmid = _text(record.get("source_pmid"))
    quote = _text(record.get("text") or record.get("evidence_quote"))
    result: dict[str, Any] = {
        "source_pmid": pmid or None,
        "title": _text(record.get("title")),
        "year": record.get("year") if isinstance(record.get("year"), int) else None,
        "evidence_section": _text(record.get("evidence_section")),
        "quote": quote,
        "context_before": "",
        "context_after": "",
        "context_located": False,
        "section_title": "",
        "section_type": "",
        "support_status": _text(record.get("support_status")) or "unchecked",
        "evidence_status": _text(record.get("evidence_status")) or "unverified",
        "extraction_granularity": (
            _text(record.get("extraction_granularity")) or "unknown"
        ),
    }
    if not pmid or not quote:
        return result

    init_db()
    with get_conn() as conn:
        paper = conn.execute(
            "SELECT id, title, year, abstract FROM papers WHERE pmid=?",
            (pmid,),
        ).fetchone()
        if not paper:
            return result
        result["title"] = _text(paper["title"]) or result["title"]
        result["year"] = paper["year"] if isinstance(paper["year"], int) else result["year"]

        # Prefer independently stored relation-evidence metadata when available.
        evidence_row = conn.execute(
            """SELECT evidence_section, evidence_quote, evidence_start, evidence_end,
                      evidence_status, support_status, extraction_granularity
               FROM relation_evidence
               WHERE source_pmid=? AND evidence_quote=?
               ORDER BY CASE evidence_status WHEN 'located' THEN 0 ELSE 1 END, id
               LIMIT 1""",
            (pmid, quote),
        ).fetchone()
        if evidence_row:
            for key in (
                "evidence_section",
                "evidence_status",
                "support_status",
                "extraction_granularity",
            ):
                value = evidence_row[key]
                if value not in (None, ""):
                    result[key] = value

        sections = conn.execute(
            """SELECT section_type, title, content, order_idx
               FROM document_sections WHERE paper_id=?
               ORDER BY CASE WHEN LOWER(section_type)=LOWER(?) THEN 0 ELSE 1 END,
                        order_idx""",
            (paper["id"], result["evidence_section"]),
        ).fetchall()

    candidates = [
        (
            _text(row["section_type"]),
            _text(row["title"]),
            str(row["content"] or ""),
        )
        for row in sections
    ]
    abstract = str(paper["abstract"] or "")
    if abstract:
        candidates.append(("abstract", "Abstract", abstract))

    for section_type, section_title, source in candidates:
        span = locate_quote(source, quote)
        if span is None:
            continue
        before, located_quote, after = _context_slice(
            source,
            span,
            before_chars=max(0, int(before_chars)),
            after_chars=max(0, int(after_chars)),
        )
        result.update(
            {
                "quote": located_quote,
                "context_before": before,
                "context_after": after,
                "context_located": True,
                "section_title": section_title,
                "section_type": section_type,
                "evidence_status": "located",
            }
        )
        break
    return result
