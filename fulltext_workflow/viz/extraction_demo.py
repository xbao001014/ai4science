"""Fulltext ↔ extraction demo: payload loader, evidence match, HTML render (Task 2)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import config
from db.schema import get_conn

STUDY_TYPE_LABELS_ZH: dict[str, str] = {
    "ai_algorithm": "算法研究",
    "clinical_study": "临床研究",
    "review": "综述",
    "meta_analysis": "荟萃分析",
    "dataset_benchmark": "数据集基准",
    "foundation_model": "基础模型",
    "multimodal": "多模态",
    "other": "其他",
}

RELATION_LABELS_ZH: dict[str, str] = {
    "APPLIES_METHOD": "应用方法",
    "COMPARES_METHOD": "对比方法",
    "SURVEYS_METHOD": "综述方法",
    "TARGETS_DISEASE": "针对病种",
    "COVERS_DISEASE": "覆盖病种",
    "OPERATES_ON": "操作组织",
    "PERFORMS_TASK": "执行任务",
    "USES_DATASET": "使用数据集",
    "RELEASES_DATASET": "发布数据集",
    "PRETRAINS_ON": "预训练数据",
    "ACHIEVES_METRIC": "达成指标",
    "USES_MODALITY": "使用模态",
    "REPORTS_LIMITATION": "报告局限",
    "RELATED_TO": "相关",
}

OBJECT_TYPE_GROUP_ORDER: list[str] = [
    "Method",
    "Disease",
    "Task",
    "Dataset",
    "Metric",
    "Modality",
    "Limitation",
    "Tissue",
]

_VALID_FULLTEXT_STATUSES = frozenset({"available", "pdf_available"})


class DemoExportError(ValueError):
    """Raised when a PMID is ineligible for demo export."""


def parse_pmid_list(text: str) -> list[str]:
    """Parse PMID list file content; skip blank lines and ``#`` comments."""
    pmids: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" in stripped:
            stripped = stripped.split("#", 1)[0].strip()
        if stripped:
            pmids.append(stripped)
    return pmids


def match_evidence_quote(section_text: str, quote: str) -> tuple[int, int] | None:
    """Locate *quote* in *section_text*: exact → whitespace-flexible → case-insensitive."""
    if not quote or not section_text:
        return None

    idx = section_text.find(quote)
    if idx >= 0:
        return (idx, idx + len(quote))

    parts = quote.split()
    if parts:
        pattern = r"\s+".join(re.escape(p) for p in parts)
        m = re.search(pattern, section_text)
        if m:
            return (m.start(), m.end())
        m = re.search(pattern, section_text, re.IGNORECASE)
        if m:
            return (m.start(), m.end())

    m = re.search(re.escape(quote), section_text, re.IGNORECASE)
    if m:
        return (m.start(), m.end())
    return None


def _object_type_sort_key(object_type: str) -> tuple[int, str]:
    try:
        return (OBJECT_TYPE_GROUP_ORDER.index(object_type), object_type)
    except ValueError:
        return (len(OBJECT_TYPE_GROUP_ORDER), object_type)


def _load_one_paper(conn: Any, pmid: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM papers WHERE pmid = ?",
        (pmid,),
    ).fetchone()
    if row is None:
        raise DemoExportError(f"PMID {pmid} not found in database")

    if row["full_text_status"] not in _VALID_FULLTEXT_STATUSES:
        raise DemoExportError(
            f"PMID {pmid} full_text_status={row['full_text_status']!r} "
            f"(need available or pdf_available)"
        )

    if not row["extraction_done"]:
        raise DemoExportError(f"PMID {pmid} extraction not done")

    paper_id = row["id"]
    section_rows = conn.execute(
        """SELECT section_type, title, content, order_idx
           FROM document_sections
           WHERE paper_id = ?
           ORDER BY order_idx""",
        (paper_id,),
    ).fetchall()
    if not section_rows:
        raise DemoExportError(f"PMID {pmid} has no document sections")

    extraction_rows = conn.execute(
        """SELECT r.id, r.relation, r.metric_value, r.evidence_section,
                  r.evidence_quote, r.confidence, r.extraction_granularity,
                  e.name AS object_name, e.type AS object_type
           FROM relations r
           JOIN entities e ON e.id = r.object_id
           WHERE r.subject_type = 'Paper'
             AND r.subject_id = ?
             AND (r.status = 'active' OR r.status IS NULL)""",
        (paper_id,),
    ).fetchall()
    if not extraction_rows:
        raise DemoExportError(f"PMID {pmid} has no active extractions")

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
                "relation_label_zh": RELATION_LABELS_ZH.get(ext["relation"], ext["relation"]),
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


def load_demo_papers(
    pmids: list[str],
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load demo payload for each PMID; fail fast on first ineligible paper."""
    prev_db_path = config.DB_PATH
    if db_path is not None:
        config.DB_PATH = Path(db_path)
    try:
        with get_conn() as conn:
            return [_load_one_paper(conn, pmid) for pmid in pmids]
    finally:
        config.DB_PATH = prev_db_path


def render_extraction_demo_html(papers: list[dict[str, Any]]) -> str:
    """Render self-contained HTML demo (implemented in Task 2)."""
    raise NotImplementedError
