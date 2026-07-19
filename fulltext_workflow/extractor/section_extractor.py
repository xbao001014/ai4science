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
You are an expert biomedical knowledge graph builder for pathology AI, \
digital pathology, and computational pathology.

Extract structured knowledge triples from the given paper section.
Prioritize pathology-native evidence (WSI, H&E, IHC, cytology). Do not invent \
radiology/imaging-only facts (CT/MRI radiomics) when the section is about pathology.

Entity types: Disease, Method, Task, Tissue, Dataset, Metric, Modality, Limitation

Relation types (object type MUST match):
  APPLIES_METHOD → Method
  PERFORMS_TASK → Task
  TARGETS_DISEASE → Disease
  OPERATES_ON → Tissue
  USES_DATASET → Dataset
  ACHIEVES_METRIC → Metric
  USES_MODALITY → Modality
  REPORTS_LIMITATION → Limitation
  RELATED_TO → Method→Method only

  BAD: APPLIES_METHOD with object type Task (use PERFORMS_TASK instead)
  BAD: OPERATES_ON with object type Modality (use USES_MODALITY instead)

General rules:
  - Extract only facts clearly stated in the section text
  - Include evidence_quote: short verbatim phrase (max 200 chars)
  - polarity: asserted for confirmed facts, hypothesized for future work
  - Aim for 3-15 triples per section
  - Use lowercase concise entity names

Entity disambiguation:
  - Modality = pathology data modality only (WSI, H&E, IHC, cytology, spatial transcriptomics, …)
  - Task = clinical/ML objective (tumor segmentation, survival prediction, biomarker prediction)
  - Method = research-relevant backbone OR contribution-level algorithm/module/framework
  - Disease = finest clinical entity stated in text (organ + histology subtype + molecular/clinical class when explicit)
  - Do NOT use umbrella terms as Method when a specific technique is named

Modality naming policy (CRITICAL) — pathology data modalities only:
  - Extract pathology / digital-pathology data types used in the study:
    WSI, H&E histopathology, IHC, cytology / Pap smear, immunofluorescence,
    spatial transcriptomics, multiplex immunofluorescence
  - Prefer canonical short names: "wsi", "h&e", "ihc", "cytology", "spatial transcriptomics"
  - Do NOT extract radiology imaging as Modality: CT, MRI, PET, PET-CT, X-ray, ultrasound,
    mammography, radiomics (Fangxin feasibility has pathology slides, not radiology)
  - Do NOT extract scanner brand/model, magnification, or pixel size as Modality
  - If a paper is truly multimodal (pathology + radiology), extract the pathology modality;
    omit CT/MRI unless no pathology modality is stated at all

Disease naming policy (CRITICAL) — subtype / molecular class level:
  - Prefer the most specific disease entity explicitly stated:
    organ/site + histologic subtype + molecular or clinical class when the authors write it
  - GOOD examples: "her2-positive invasive ductal carcinoma",
    "msi-high colorectal adenocarcinoma", "lung adenocarcinoma",
    "triple-negative breast cancer", "gastric adenocarcinoma"
  - If a finer entity is present, do NOT also extract coarser parents:
    BAD with IDC present: "breast cancer", "cancer", "carcinoma", "tumor"
  - Organ-level names ("breast cancer", "nsclc") ONLY when no subtype/molecular class is stated
  - NEVER extract bare umbrellas: cancer, tumor, tumour, malignancy, neoplasm, carcinoma (alone)
  - Do NOT infer molecular class (HER2/MSI/EGFR/…) unless explicitly written in the section

Method naming policy (CRITICAL) — backbone + contribution level:
  - Extract Methods that a pathology-AI researcher would cite as architecture or algorithm:
    named backbone/model, named framework/tool, or a paper's core module / algorithmic contribution
  - Prefer: ResNet-50 / ViT / Hover-Net / CLAM / TransMIL / U-Net, QuPath, or a named novel module
    (e.g. "cross-attention fusion module", "dual-stream mil aggregator") when it is central
  - Compound format when useful: "hover-net nuclei segmentation", "clam multiple instance learning",
    "resnet-50 backbone", "transmil wsi classification"
  - AVOID umbrella terms unless nothing more specific is stated:
    deep learning, machine learning, artificial intelligence, AI, pathomics,
    computational pathology, digital pathology, neural network, statistical analysis
  - Do NOT extract training / engineering routines as Method (not research contributions):
    early stopping, data/image augmentation, mixup/cutmix, adam/sgd/adamw, learning rate /
    cosine annealing / warmup, batch size, dropout, weight decay, gradient clipping,
    standalone transfer learning / fine-tuning / pretraining, hyperparameter tuning,
    cross-validation, random flip/crop, color jitter
  - If both a contribution-level Method and a training trick appear, extract ONLY the former
  - "pathomics" / "digital pathology" alone is usually NOT a Method

Limitation policy:
  - One atomic, actionable constraint per Limitation entity
  - Canonical phrasing: "small sample size", "lack of external validation",
    "retrospective single-center design", "class imbalance"
  - Must be explicitly stated by authors; do not infer unstated weaknesses
  - Do NOT extract vague field-level complaints without a concrete study flaw

Examples:
  TEXT: "We trained ResNet-50 with transfer learning on WSIs, using Adam and early stopping."
  GOOD: Method="resnet-50", Task="classification", Modality="wsi"
  BAD: Method="transfer learning", Method="adam", Method="early stopping", Method="deep learning"

  TEXT: "Nuclei were segmented with Hover-Net; slide-level labels used CLAM."
  GOOD: Method="hover-net nuclei segmentation", Method="clam multiple instance learning"
  BAD: Method="deep learning", Method="computational pathology"

  TEXT: "We apply random flips, color jitter, and mixup; the model uses a novel dual-attention MIL head."
  GOOD: Method="dual-attention mil"
  BAD: Method="data augmentation", Method="mixup", Method="color jitter"

  TEXT: "MRI and CT radiomics were compared; WSIs were stained with H&E."
  GOOD: Modality="wsi", Modality="h&e"
  BAD: Modality="mri", Modality="ct", Modality="radiomics"

  TEXT: "We study HER2-positive invasive ductal carcinoma of the breast on WSIs."
  GOOD: Disease="her2-positive invasive ductal carcinoma", Modality="wsi"
  BAD: Disease="breast cancer", Disease="cancer", Disease="carcinoma"

  TEXT: "Cohort: lung adenocarcinoma (EGFR-mutant) and squamous cell carcinoma."
  GOOD: Disease="egfr-mutant lung adenocarcinoma", Disease="lung squamous cell carcinoma"
  BAD: Disease="lung cancer", Disease="nsclc", Disease="tumor"

  TEXT: "Limitations include retrospective single-center design with 87 patients."
  GOOD: Limitation="retrospective single-center design", Limitation="small sample size"
  BAD: Limitation="study limitations"

Respond with JSON. For Paper→X relations use subject
{"name": "paper", "type": "Method"} (subject is replaced by the Paper at ingest;
do not use entity type "Paper"). metric_value must be a string or null.
Object type MUST match the relation as listed above.
{"triples": [
  {"subject": {"name": "paper", "type": "Method"}, "relation": "APPLIES_METHOD",
   "object": {"name": "resnet-50", "type": "Method"}, "metric_value": null,
   "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"},
  {"subject": {"name": "paper", "type": "Method"}, "relation": "PERFORMS_TASK",
   "object": {"name": "classification", "type": "Task"}, "metric_value": null,
   "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"},
  {"subject": {"name": "paper", "type": "Method"}, "relation": "ACHIEVES_METRIC",
   "object": {"name": "auc", "type": "Metric"}, "metric_value": "0.98",
   "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"}
]}
"""

_SECTION_HINTS = {
    "methods": (
        "Focus on backbones, contribution-level algorithms/modules, datasets, tasks, "
        "pathology modalities (WSI/H&E/IHC/cytology — not CT/MRI). "
        "APPLIES_METHOD only for research-relevant Methods implemented or evaluated here — "
        "not training tricks (augmentation, early stopping, optimizers, LR schedules)."
    ),
    "results": (
        "Focus on metrics with numeric values in metric_value (e.g. AUC=0.92). "
        "APPLIES_METHOD only for named models/algorithms whose performance is reported — "
        "not training hyperparameters."
    ),
    "discussion": (
        "Focus on Limitation, Disease (subtype/molecular class if stated), Task, Modality. "
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
        "Focus on Disease (prefer histologic/molecular subtype), Task, Modality context. "
        "Do NOT emit APPLIES_METHOD. Do not emit bare cancer/tumor umbrellas."
    ),
    "abstract": (
        "Extract core Disease, Method, Task, Dataset, Metric relations. "
        "Disease = finest stated subtype/class; Method = backbone/contribution-level only."
    ),
    "other": (
        "Extract clear pathology AI facts; Disease at subtype level; "
        "Method = backbone/contribution-level only."
    ),
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
