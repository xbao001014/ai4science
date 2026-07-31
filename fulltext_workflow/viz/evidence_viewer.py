"""Single-paper fulltext ↔ extraction viewer for gap_ui embed."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from db.schema import get_conn
from viz.extraction_demo import (
    OBJECT_TYPE_GROUP_ORDER,
    RELATION_LABELS_ZH,
    STUDY_TYPE_LABELS_ZH,
    match_evidence_quote,
)

_VALID_FULLTEXT_STATUSES = frozenset({"available", "pdf_available"})


class ViewerLoadError(Exception):
    def __init__(self, code: str, message_zh: str):
        self.code = code
        self.message_zh = message_zh
        super().__init__(message_zh)


def _object_type_sort_key(object_type: str) -> tuple[int, str]:
    try:
        return (OBJECT_TYPE_GROUP_ORDER.index(object_type), object_type)
    except ValueError:
        return (len(OBJECT_TYPE_GROUP_ORDER), object_type)


def load_paper_for_viewer(
    pmid: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    prev = config.DB_PATH
    if db_path is not None:
        config.DB_PATH = Path(db_path)
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE pmid = ?", (pmid,)
            ).fetchone()
            if row is None:
                raise ViewerLoadError("not_found", f"PMID {pmid} 不在语料中")
            if row["full_text_status"] not in _VALID_FULLTEXT_STATUSES:
                raise ViewerLoadError(
                    "no_fulltext",
                    f"PMID {pmid} 无可用全文，无法溯源到正文",
                )
            paper_id = row["id"]
            section_rows = conn.execute(
                """SELECT section_type, title, content, order_idx
                   FROM document_sections
                   WHERE paper_id = ?
                   ORDER BY order_idx""",
                (paper_id,),
            ).fetchall()
            if not section_rows:
                raise ViewerLoadError(
                    "no_sections",
                    f"PMID {pmid} 无分节正文，无法溯源到正文",
                )
            extraction_rows = conn.execute(
                """SELECT r.id, r.relation, r.metric_value, r.evidence_section,
                          r.evidence_quote, r.confidence, r.extraction_granularity,
                          e.name AS object_name, e.type AS object_type
                   FROM relations r
                   JOIN entities e ON e.id = r.object_id
                   WHERE r.subject_type = 'Paper'
                     AND r.subject_id = ?
                     AND (r.status = 'active' OR r.status IS NULL)
                   ORDER BY r.id""",
                (paper_id,),
            ).fetchall()
            study_type = row["study_type"] or "other"
            sections = [
                {
                    "section_type": sec["section_type"],
                    "title": sec["title"] or None,
                    "content": sec["content"],
                    "order_idx": sec["order_idx"],
                }
                for sec in section_rows
            ]
            extractions = sorted(
                [
                    {
                        "id": ext["id"],
                        "relation": ext["relation"],
                        "relation_label_zh": RELATION_LABELS_ZH.get(
                            ext["relation"], ext["relation"]
                        ),
                        "object_name": ext["object_name"],
                        "object_type": ext["object_type"],
                        "metric_value": ext["metric_value"] or None,
                        "evidence_section": ext["evidence_section"],
                        "evidence_quote": ext["evidence_quote"],
                        "confidence": ext["confidence"],
                        "extraction_granularity": ext["extraction_granularity"],
                    }
                    for ext in extraction_rows
                ],
                key=lambda e: _object_type_sort_key(e["object_type"]),
            )
            return {
                "pmid": pmid,
                "title": row["title"],
                "study_type": study_type,
                "study_type_label_zh": STUDY_TYPE_LABELS_ZH.get(study_type, study_type),
                "full_text_status": row["full_text_status"],
                "journal_name": row["journal_name"],
                "year": row["year"],
                "sections": sections,
                "extractions": extractions,
            }
    finally:
        config.DB_PATH = prev


def resolve_focus_extraction(
    paper: dict[str, Any],
    focus_quote: str | None,
) -> int | None:
    if not focus_quote or not str(focus_quote).strip():
        return None
    q = str(focus_quote).strip()
    best_i: int | None = None
    best_score = 0
    for i, ext in enumerate(paper.get("extractions") or []):
        eq = str(ext.get("evidence_quote") or "").strip()
        if not eq:
            continue
        if eq == q:
            return i
        score = 0
        if q in eq or eq in q:
            score = min(len(q), len(eq))
        else:
            hit = match_evidence_quote(eq, q) or match_evidence_quote(q, eq)
            if hit:
                score = hit[1] - hit[0]
        if score > best_score:
            best_score = score
            best_i = i
    return best_i if best_score > 0 else None
