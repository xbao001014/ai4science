"""Section-aware triple extraction (Step 2)."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

import config
from db.schema import (
    clear_paper_kg_extractions,
    get_conn,
    get_paper_sections,
    get_papers_by_pmids,
    get_papers_for_extraction,
    insert_relation,
    mark_extraction_done,
    upsert_entity,
)
from extractor.dataset_access import normalize_dataset_name, resolve_dataset_access
from extractor.entity_normalize import postprocess_triples
from extractor.llm_client import configure_concurrency, llm_call_structured, truncate_input
from extractor.skip_rules import skip_extraction_reason as _skip_extraction_reason
from extractor.skip_rules import skip_nonsubstantive_fulltext as _skip_nonsubstantive_fulltext
from extractor.section_utils import merge_sections_by_type

from extractor.study_classifier import classify_study_type
from extractor.study_prompts import build_section_system
from extractor.triple_models import Entity, ExtractionResult, RelationLiteral, Triple

_db_lock = threading.Lock()


def _section_system(section_type: str, study_type: str | None = None) -> str:
    return build_section_system(section_type, study_type)


def _extract_from_text(
    title: str,
    section_type: str,
    section_title: str,
    content: str,
    *,
    study_type: str | None = None,
) -> list[Triple]:
    if not content.strip():
        return []
    user_msg = (
        f"Paper title: {title}\n"
        f"Study type: {study_type or 'unknown'}\n"
        f"Section type: {section_type}\n"
        f"Section title: {section_title}\n"
        f"Section text:\n{truncate_input(content)}\n\n"
        "Extract knowledge triples."
    )
    raw = llm_call_structured(_section_system(section_type, study_type), user_msg)
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
    return postprocess_triples(triples, section_type, study_type=study_type)


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
            obj_id = upsert_entity(
                triple.object.name,
                triple.object.type,
                method_role=(
                    triple.method_role_hint
                    if triple.object.type == "Method"
                    else None
                ),
            )
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
                extraction_pass="section",
                status="active",
            )
        else:
            obj_name = triple.object.name
            access_class = None
            if triple.object.type == "Dataset" or triple.relation in (
                "USES_DATASET",
                "RELEASES_DATASET",
                "PRETRAINS_ON",
            ):
                obj_name = normalize_dataset_name(obj_name)
                access_class = resolve_dataset_access(
                    obj_name,
                    evidence_quote=triple.evidence_quote,
                    access_hint=triple.access_hint,
                )
            obj_id = upsert_entity(
                obj_name,
                triple.object.type,
                access_class=access_class,
                method_role=(
                    triple.method_role_hint
                    if triple.object.type == "Method"
                    else None
                ),
            )
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
                extraction_pass="section",
                status="active",
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


def _other_as_discussion_job(sections) -> dict | None:
    """Promote long `other` body to discussion when core sections are missing/empty."""
    min_chars = config.EXTRACT_OTHER_FALLBACK_MIN_CHARS
    other_secs = [sec for sec in sections if sec["section_type"] == "other"]
    merged = merge_sections_by_type(other_secs)
    if not merged:
        return None
    job = merged[0]
    if len((job.get("content") or "").strip()) < min_chars:
        return None
    return {
        "section_type": "discussion",
        "title": job.get("title") or "discussion (from other)",
        "content": job["content"],
    }


def _extract_fulltext(
    paper: dict, paper_id: int, pmid: str, title: str, granularity: str,
    *,
    study_type: str | None = None,
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
            study_type=study_type,
        )
        for triple in triples:
            _save_triple(triple, paper_id, pmid, sec_type, granularity)

    # Core-only with no methods/results/… : try long `other` as discussion
    if not jobs and config.EXTRACT_CORE_ONLY:
        promo = _other_as_discussion_job(sections)
        if promo:
            print(
                f"\n  [Extractor] PMID {pmid}: no core sections; "
                f"extracting other as discussion ({len(promo['content'])} chars)."
            )
            jobs = [promo]

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
            _extract_abstract_fallback(
                paper_id, pmid, title, abstract_text, study_type=study_type
            )
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

    added = _relation_count(pmid) - before
    # Core ran but yielded nothing — salvage long `other` once
    if added == 0 and config.EXTRACT_CORE_ONLY and "other" not in extract_types:
        promo = _other_as_discussion_job(sections)
        if promo and not any(
            (j.get("title") or "").startswith("discussion (from other)") for j in jobs
        ):
            print(
                f"\n  [Extractor] PMID {pmid}: 0 from core; "
                f"retrying other as discussion ({len(promo['content'])} chars)."
            )
            _run_one(promo)
            added = _relation_count(pmid) - before

    return added


def _extract_abstract_fallback(
    paper_id: int,
    pmid: str,
    title: str,
    abstract: str,
    *,
    study_type: str | None = None,
) -> int:
    before = _relation_count(pmid)
    triples = _extract_from_text(
        title, "abstract", "Abstract", abstract, study_type=study_type
    )
    for triple in triples:
        _save_triple(triple, paper_id, pmid, "abstract", "abstract")
    return _relation_count(pmid) - before


def _run_reconcile_for_paper(
    paper, paper_id: int, pmid: str, *, study_type: str | None = None
) -> None:
    from db.schema import set_paper_reconcile_status
    from extractor.fulltext_reconcile import (
        apply_reconcile_payload,
        assemble_reconcile_text,
        call_reconcile_llm,
        summarize_pass1_entities,
    )

    if not config.RECONCILE_ENABLED:
        return
    status = paper["full_text_status"]
    if status not in ("available", "pdf_available"):
        set_paper_reconcile_status(paper_id, "skipped_no_ft")
        return
    sections = get_paper_sections(paper_id)
    sec_dicts = [
        {"section_type": s["section_type"], "content": s["content"] or ""}
        for s in sections
    ]
    if not any((s["content"] or "").strip() for s in sec_dicts):
        set_paper_reconcile_status(paper_id, "skipped_no_ft")
        return
    if study_type is None and "study_type" in paper.keys():
        study_type = paper["study_type"]
    try:
        text = assemble_reconcile_text(sec_dicts, max_chars=config.RECONCILE_MAX_CHARS)
        summary = summarize_pass1_entities(pmid)
        payload = call_reconcile_llm(text, summary, study_type=study_type)
        apply_reconcile_payload(paper_id, pmid, payload, study_type=study_type)
        set_paper_reconcile_status(paper_id, "done")
    except Exception as e:
        print(f"\n  [Reconcile] PMID {pmid}: failed: {e}")
        set_paper_reconcile_status(paper_id, "failed")


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

        if status in ("available", "pdf_available"):
            sections = get_paper_sections(paper_id)
            sec_dicts = [
                {
                    "section_type": s["section_type"],
                    "content": s["content"] or "",
                }
                for s in sections
            ]
            thin = _skip_nonsubstantive_fulltext(abstract, sec_dicts)
            if thin:
                print(f"\n  [Extractor] PMID {pmid}: skip ({thin})")
                mark_extraction_done(paper_id, "other")
                return

        if status == "available":
            added = _extract_fulltext(
                dict(paper), paper_id, pmid, title, "fulltext", study_type=study_type
            )
        elif status == "pdf_available":
            added = _extract_fulltext(
                dict(paper), paper_id, pmid, title, "mineru_pdf", study_type=study_type
            )
        else:
            added = _extract_abstract_fallback(
                paper_id, pmid, title, abstract, study_type=study_type
            )

        if added == 0 and abstract.strip() and status in ("available", "pdf_available"):
            print(f"\n  [Extractor] PMID {pmid}: 0 relations from fulltext, trying abstract.")
            added = _extract_abstract_fallback(
                paper_id, pmid, title, abstract, study_type=study_type
            )

        if added == 0:
            print(
                f"\n  [Extractor] PMID {pmid}: no relations extracted "
                f"(extraction_done stays 0 for retry)."
            )
            return

        mark_extraction_done(paper_id, study_type)
        _run_reconcile_for_paper(paper, paper_id, pmid, study_type=study_type)
    except Exception as e:
        print(f"\n  [Extractor] Error on PMID {pmid}: {e}")


def run_extraction(
    limit: int | None = None,
    *,
    pmids: list[str] | None = None,
    force_reextract: bool = False,
) -> None:
    if pmids:
        if force_reextract:
            for pmid in pmids:
                clear_paper_kg_extractions(pmid)
        papers = get_papers_by_pmids(pmids)
        lim = len(papers)
    elif limit is None:
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
