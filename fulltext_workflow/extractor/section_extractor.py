"""Section-aware triple extraction (Step 2)."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
from extractor.entity_normalize import postprocess_triples
from extractor.llm_client import configure_concurrency, llm_call_structured, truncate_input
from extractor.skip_rules import skip_extraction_reason as _skip_extraction_reason
from extractor.study_classifier import classify_study_type
from extractor.triple_models import Entity, ExtractionResult, RelationLiteral, Triple

_db_lock = threading.Lock()

_BASE_SYSTEM = """\
You are an expert biomedical knowledge graph builder for pathology AI and radiomics.

Extract structured knowledge triples from the given paper section.

Entity types: Disease, Method, Task, Tissue, Dataset, Metric, Modality, Limitation

Relation types:
  APPLIES_METHOD, TARGETS_DISEASE, OPERATES_ON, PERFORMS_TASK,
  USES_DATASET, ACHIEVES_METRIC, RELATED_TO (Method->Method only),
  REPORTS_LIMITATION (Paper->Limitation), USES_MODALITY (Paper->Modality)

General rules:
  - Extract only facts clearly stated in the section text
  - Include evidence_quote: short verbatim phrase (max 200 chars)
  - polarity: asserted for confirmed facts, hypothesized for future work
  - Aim for 3-15 triples per section
  - Use lowercase concise entity names

Entity disambiguation:
  - Modality = imaging/data type (CT, MRI, WSI, H&E histopathology)
  - Task = clinical/ML objective (tumor segmentation, survival prediction)
  - Method = HOW the task is solved (resnet-50, lasso feature selection, grad-cam)
  - Do NOT use umbrella terms as Method when a specific technique is named

Method naming policy (CRITICAL):
  - Extract the MOST SPECIFIC implementable technique this paper uses or evaluates
  - Prefer: model architecture, named algorithm, software tool, feature-selection procedure
  - AVOID standalone umbrella terms unless no more specific method is stated:
    deep learning, machine learning, artificial intelligence, AI, radiomics,
    neural network, statistical analysis
  - If both umbrella and specific names appear, extract ONLY the specific one
  - Compound format: "resnet-50 transfer learning", "pyradiomics lasso selection",
    "u-net segmentation", "federated xgboost classification"
  - "radiomics" alone is usually NOT a Method; use the named tool/procedure instead

Limitation policy:
  - One atomic, actionable constraint per Limitation entity
  - Canonical phrasing: "small sample size", "lack of external validation",
    "retrospective single-center design", "class imbalance"
  - Must be explicitly stated by authors; do not infer unstated weaknesses
  - Do NOT extract vague field-level complaints without a concrete study flaw

Examples:
  TEXT: "We trained ResNet-50 with transfer learning on WSIs."
  GOOD: Method="resnet-50 transfer learning", Task="classification", Modality="WSI"
  BAD: Method="deep learning", Method="machine learning"

  TEXT: "Radiomics features were extracted with PyRadiomics and selected via LASSO."
  GOOD: Method="pyradiomics feature extraction", Method="lasso feature selection"
  BAD: Method="radiomics"

  TEXT: "Limitations include retrospective single-center design with 87 patients."
  GOOD: Limitation="retrospective single-center design", Limitation="small sample size"
  BAD: Limitation="study limitations"

Respond with JSON:
{"triples": [{"subject": {"name": "...", "type": "Method"}, "relation": "APPLIES_METHOD",
  "object": {"name": "...", "type": "Task"}, "metric_value": null,
  "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"}]}
"""

_SECTION_HINTS = {
    "methods": (
        "Focus on methods, datasets, tasks, and modalities used IN THIS STUDY. "
        "APPLIES_METHOD only for techniques implemented or evaluated here."
    ),
    "results": (
        "Focus on metrics with numeric values in metric_value (e.g. AUC=0.92). "
        "APPLIES_METHOD only for models/algorithms whose performance is reported."
    ),
    "discussion": (
        "Focus on Limitation, Disease, Task, Modality. "
        "Do NOT emit APPLIES_METHOD — generic ML/DL mentions here are not this paper's methods."
    ),
    "limitations": (
        "Extract Limitation entities and REPORTS_LIMITATION relations only. "
        "Use canonical limitation phrasing; one flaw per entity."
    ),
    "future_work": (
        "Extract hypothesized Limitation and Task entities; use polarity=hypothesized. "
        "Do NOT emit APPLIES_METHOD unless authors name a concrete new algorithm."
    ),
    "introduction": (
        "Focus on Disease, Task, Modality context. "
        "Do NOT emit APPLIES_METHOD."
    ),
    "abstract": (
        "Extract core Disease, Method, Task, Dataset, Metric relations. "
        "Prefer specific methods over umbrella terms."
    ),
    "other": "Extract any clear pathology AI / radiomics facts; prefer specific methods.",
}


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
        triples = ExtractionResult.model_validate(raw).triples
    except Exception:
        triples = []
        for item in raw.get("triples", []):
            try:
                triples.append(Triple.model_validate(item))
            except Exception:
                pass
    return postprocess_triples(triples, section_type)


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


from extractor.section_utils import merge_sections_by_type
def _extract_fulltext(
    paper: dict, paper_id: int, pmid: str, title: str, granularity: str
) -> int:
    sections = get_paper_sections(paper_id)
    extract_types = _section_types_for_paper(has_fulltext=True)
    jobs = merge_sections_by_type(
        sec for sec in sections if sec["section_type"] in extract_types
    )
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

    llm_parallel = max(
        config.LLM_MAX_CONCURRENT,
        config.EXTRACT_SECTION_WORKERS * config.EXTRACT_PAPER_WORKERS,
    )
    configure_concurrency(llm_parallel)

    mode = "core sections" if config.EXTRACT_CORE_ONLY else "all sections"
    print(
        f"[Extractor] {len(papers)} papers (limit={'all' if limit == 0 else lim}), "
        f"{mode}, section_workers={config.EXTRACT_SECTION_WORKERS}, "
        f"paper_workers={config.EXTRACT_PAPER_WORKERS}, "
        f"llm_max_concurrent={llm_parallel}."
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
