"""Section-aware triple extraction (Step 2)."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal, Optional

from pydantic import BaseModel, Field
from tqdm import tqdm

import config
from db.schema import (
    get_conn,
    get_paper_sections,
    get_papers_for_extraction,
    insert_relation,
    mark_extraction_done,
    upsert_entity,
)
from extractor.llm_client import llm_call_structured, truncate_input
from extractor.study_classifier import classify_study_type

EntityTypeLiteral = Literal[
    "Disease", "Method", "Task", "Tissue", "Dataset", "Metric", "Modality", "Limitation"
]

RelationLiteral = Literal[
    "APPLIES_METHOD",
    "TARGETS_DISEASE",
    "OPERATES_ON",
    "PERFORMS_TASK",
    "USES_DATASET",
    "ACHIEVES_METRIC",
    "RELATED_TO",
    "REPORTS_LIMITATION",
    "USES_MODALITY",
]

_db_lock = threading.Lock()

_BASE_SYSTEM = """\
You are an expert biomedical knowledge graph builder for pathology AI and radiomics.

Extract structured knowledge triples from the given paper section.

Entity types: Disease, Method, Task, Tissue, Dataset, Metric, Modality, Limitation

Relation types:
  APPLIES_METHOD, TARGETS_DISEASE, OPERATES_ON, PERFORMS_TASK,
  USES_DATASET, ACHIEVES_METRIC, RELATED_TO (Method->Method only),
  REPORTS_LIMITATION (Paper->Limitation), USES_MODALITY (Paper->Modality)

Rules:
  - Extract only facts clearly stated in the section text
  - Normalize entity names concisely
  - Include evidence_quote: short verbatim phrase (max 200 chars)
  - polarity: asserted for confirmed facts, hypothesized for future work
  - Aim for 3-15 triples per section

Respond with JSON:
{"triples": [{"subject": {"name": "...", "type": "Method"}, "relation": "APPLIES_METHOD",
  "object": {"name": "...", "type": "Task"}, "metric_value": null,
  "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"}]}
"""

_SECTION_HINTS = {
    "methods": "Focus on methods, datasets, tasks, and modalities used.",
    "results": "Focus on metrics with numeric values in metric_value (e.g. AUC=0.92).",
    "discussion": "Focus on limitations, modalities, diseases, and tasks discussed.",
    "limitations": "Extract Limitation entities and REPORTS_LIMITATION relations.",
    "future_work": "Extract hypothesized limitations and future tasks; use polarity=hypothesized.",
    "introduction": "Focus on disease, task, and modality context.",
    "abstract": "Extract core disease, method, task, dataset, metric relations.",
    "other": "Extract any clear pathology AI / radiomics facts.",
}

from extractor.skip_rules import skip_extraction_reason as _skip_extraction_reason


class Entity(BaseModel):
    name: str
    type: EntityTypeLiteral


class Triple(BaseModel):
    subject: Entity
    relation: RelationLiteral
    object: Entity
    metric_value: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_quote: Optional[str] = Field(default=None, max_length=300)
    polarity: Literal["asserted", "hypothesized"] = "asserted"


class ExtractionResult(BaseModel):
    triples: list[Triple] = Field(default_factory=list)


def _section_system(section_type: str) -> str:
    hint = _SECTION_HINTS.get(section_type, _SECTION_HINTS["other"])
    return f"{_BASE_SYSTEM}\n\nSection focus: {hint}"


def _extract_from_text(
    title: str,
    section_type: str,
    section_title: str,
    content: str,
) -> list[Triple]:
    if not content.strip():
        return []
    user_msg = (
        f"Paper title: {title}\n"
        f"Section type: {section_type}\n"
        f"Section title: {section_title}\n"
        f"Section text:\n{truncate_input(content)}\n\n"
        "Extract knowledge triples."
    )
    raw = llm_call_structured(_section_system(section_type), user_msg)
    if not raw:
        return []
    try:
        return ExtractionResult.model_validate(raw).triples
    except Exception:
        valid: list[Triple] = []
        for item in raw.get("triples", []):
            try:
                valid.append(Triple.model_validate(item))
            except Exception:
                pass
        return valid


def _save_triple(
    triple: Triple,
    paper_id: int,
    pmid: str,
    evidence_section: str,
    granularity: str,
) -> None:
    with _db_lock:
        if triple.relation == "RELATED_TO":
            subj_id = upsert_entity(triple.subject.name, triple.subject.type)
            obj_id = upsert_entity(triple.object.name, triple.object.type)
            insert_relation(
                subject_type=triple.subject.type,
                subject_id=subj_id,
                relation=triple.relation,
                object_type=triple.object.type,
                object_id=obj_id,
                source_pmid=pmid,
                confidence=triple.confidence,
                evidence_section=evidence_section,
                evidence_quote=triple.evidence_quote or "",
                extraction_granularity=granularity,
                polarity=triple.polarity,
            )
        else:
            obj_id = upsert_entity(triple.object.name, triple.object.type)
            insert_relation(
                subject_type="Paper",
                subject_id=paper_id,
                relation=triple.relation,
                object_type=triple.object.type,
                object_id=obj_id,
                source_pmid=pmid,
                metric_value=triple.metric_value or "",
                confidence=triple.confidence,
                evidence_section=evidence_section,
                evidence_quote=triple.evidence_quote or "",
                extraction_granularity=granularity,
                polarity=triple.polarity,
            )


def _section_types_for_paper(has_fulltext: bool) -> set[str]:
    if config.EXTRACT_CORE_ONLY:
        types = set(config.SECTIONS_FOR_EXTRACTION.keys())
        if not has_fulltext:
            types.add("abstract")
        return types
    return set(config.SECTIONS_FOR_EXTRACTION.keys()) | {
        "abstract",
        "introduction",
        "other",
    }


def _relation_count(pmid: str) -> int:
    with _db_lock:
        with get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM relations WHERE source_pmid=?",
                (pmid,),
            ).fetchone()[0]


def _extract_fulltext(
    paper: dict, paper_id: int, pmid: str, title: str, granularity: str
) -> int:
    sections = get_paper_sections(paper_id)
    extract_types = _section_types_for_paper(has_fulltext=True)
    jobs = [
        sec
        for sec in sections
        if sec["section_type"] in extract_types and (sec["content"] or "").strip()
    ]
    before = _relation_count(pmid)

    def _run_one(sec) -> None:
        sec_type = sec["section_type"]
        triples = _extract_from_text(
            title,
            sec_type,
            sec["title"] or sec_type,
            sec["content"],
        )
        for triple in triples:
            _save_triple(triple, paper_id, pmid, sec_type, granularity)

    if not jobs:
        abstract_text = (paper.get("abstract") or "").strip()
        if not abstract_text:
            abstract_secs = [
                sec
                for sec in sections
                if sec["section_type"] == "abstract" and (sec["content"] or "").strip()
            ]
            if abstract_secs:
                abstract_text = "\n\n".join(
                    (sec["content"] or "").strip() for sec in abstract_secs
                )
        if abstract_text:
            _extract_abstract_fallback(paper_id, pmid, title, abstract_text)
        return _relation_count(pmid) - before

    workers = max(1, config.EXTRACT_SECTION_WORKERS)
    if workers == 1 or len(jobs) <= 1:
        for sec in jobs:
            _run_one(sec)
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            futures = [pool.submit(_run_one, sec) for sec in jobs]
            for fut in as_completed(futures):
                fut.result()

    return _relation_count(pmid) - before


def _extract_abstract_fallback(paper_id: int, pmid: str, title: str, abstract: str) -> int:
    before = _relation_count(pmid)
    triples = _extract_from_text(title, "abstract", "Abstract", abstract)
    for triple in triples:
        _save_triple(triple, paper_id, pmid, "abstract", "abstract")
    return _relation_count(pmid) - before


def _process_paper(paper) -> None:
    paper_id = paper["id"]
    pmid = paper["pmid"] or ""
    title = paper["title"] or ""
    abstract = paper["abstract"] or ""
    pub_types_raw = paper["pub_types"] or "[]"

    try:
        pub_types = json.loads(pub_types_raw)
    except Exception:
        pub_types = []

    skip = _skip_extraction_reason(title, abstract, pub_types)
    if skip:
        print(f"\n  [Extractor] PMID {pmid}: skip ({skip})")
        mark_extraction_done(paper_id, "other")
        return

    if not abstract.strip() and paper["full_text_status"] not in (
        "available",
        "pdf_available",
    ):
        mark_extraction_done(paper_id, "other")
        return

    try:
        study_type = classify_study_type(title, abstract, pub_types)
        status = paper["full_text_status"]
        added = 0

        if status == "available":
            added = _extract_fulltext(dict(paper), paper_id, pmid, title, "fulltext")
        elif status == "pdf_available":
            added = _extract_fulltext(dict(paper), paper_id, pmid, title, "mineru_pdf")
        else:
            added = _extract_abstract_fallback(paper_id, pmid, title, abstract)

        if added == 0 and abstract.strip() and status in ("available", "pdf_available"):
            print(f"\n  [Extractor] PMID {pmid}: 0 relations from fulltext, trying abstract.")
            added = _extract_abstract_fallback(paper_id, pmid, title, abstract)

        if added == 0:
            print(
                f"\n  [Extractor] PMID {pmid}: no relations extracted "
                f"(extraction_done stays 0 for retry)."
            )
            return

        mark_extraction_done(paper_id, study_type)
    except Exception as e:
        print(f"\n  [Extractor] Error on PMID {pmid}: {e}")


def run_extraction(limit: int | None = None) -> None:
    if limit is None:
        lim = config.DEFAULT_EXTRACT_LIMIT
        papers = get_papers_for_extraction(limit=lim)
    elif limit == 0:
        papers = get_papers_for_extraction(limit=0)
        lim = len(papers)
    else:
        papers = get_papers_for_extraction(limit=limit)
        lim = limit

    mode = "core sections" if config.EXTRACT_CORE_ONLY else "all sections"
    print(
        f"[Extractor] {len(papers)} papers (limit={'all' if limit == 0 else lim}), "
        f"{mode}, section_workers={config.EXTRACT_SECTION_WORKERS}, "
        f"paper_workers={config.EXTRACT_PAPER_WORKERS}."
    )

    paper_workers = max(1, config.EXTRACT_PAPER_WORKERS)
    if paper_workers == 1:
        for paper in tqdm(papers, desc="[Extractor]", unit="paper"):
            _process_paper(paper)
    else:
        with ThreadPoolExecutor(max_workers=paper_workers) as pool:
            futures = {pool.submit(_process_paper, p): p for p in papers}
            for fut in tqdm(as_completed(futures), total=len(futures), desc="[Extractor]", unit="paper"):
                fut.result()

    print("[Extractor] Extraction complete.")
