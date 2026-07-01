"""
extractor/triple_extractor.py
LLM-based structured extraction from paper abstracts.

Two-step approach per abstract:
  Step 1 — Classify study_type (single enum value, cheap)
  Step 2 — Extract entity+relation triples (structured Pydantic output)

Uses OpenAI-compatible API (Qwen / any compatible endpoint).
Pydantic v2 is used for schema definition and validation.
Supports resume: skips papers with extraction_done=1.
"""
from __future__ import annotations

import json
import time
from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field
from tqdm import tqdm

import config
from llm_utils import llm_extra_body, truncate_for_llm
from utils.db import (
    get_unprocessed_papers,
    mark_extraction_done,
    upsert_entity,
    insert_relation,
)

# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible client
# ─────────────────────────────────────────────────────────────────────────────
_client = OpenAI(
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_API_BASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

StudyTypeLiteral = Literal[
    "ai_algorithm",
    "clinical_study",
    "review",
    "meta_analysis",
    "dataset_benchmark",
    "foundation_model",
    "multimodal",
    "other",
]


class StudyTypeResult(BaseModel):
    study_type: StudyTypeLiteral
    rationale: str = Field(default="", description="Brief reason for classification")


class Entity(BaseModel):
    name: str = Field(description="Entity name, concise and normalized")
    type: Literal["Disease", "Method", "Task", "Tissue", "Dataset", "Metric"]


class Triple(BaseModel):
    subject: Entity
    relation: Literal[
        "APPLIES_METHOD",
        "TARGETS_DISEASE",
        "OPERATES_ON",
        "PERFORMS_TASK",
        "USES_DATASET",
        "ACHIEVES_METRIC",
        "RELATED_TO",
    ]
    object: Entity
    metric_value: Optional[str] = Field(
        default=None,
        description="Numeric result if relation is ACHIEVES_METRIC, e.g. 'AUC=0.95'"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    triples: list[Triple] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

_STUDY_TYPE_SYSTEM = """\
You are an expert biomedical literature analyst specializing in pathology AI research.
Classify the given paper abstract into exactly ONE study type from this list:
- ai_algorithm: Novel AI/deep learning algorithm development or improvement
- clinical_study: Clinical validation, deployment, or patient outcome study
- review: Narrative or systematic review (not meta-analysis)
- meta_analysis: Quantitative meta-analysis with pooled statistics
- dataset_benchmark: Dataset construction, annotation, or benchmarking
- foundation_model: Large pre-trained model, self-supervised or contrastive learning for pathology
- multimodal: Study integrating multiple data modalities (image + genomics/text/clinical)
- other: Does not fit above categories

You MUST respond with this exact JSON structure:
{"study_type": "ai_algorithm"}
"""

_STUDY_TYPE_USER = """\
Title: {title}
PubMed Publication Types: {pub_types}
Abstract: {abstract}

Classify the study type.
"""

_TRIPLE_SYSTEM = """\
You are an expert biomedical knowledge graph builder specializing in pathology AI.

Extract structured knowledge triples from the paper abstract.

Entity types (use EXACTLY these strings):
  Disease  — cancer/pathological conditions (e.g. "breast carcinoma", "colorectal cancer")
  Method   — AI/computational methods (e.g. "ResNet-50", "U-Net", "contrastive learning")
  Task     — computational tasks (e.g. "tumor segmentation", "survival prediction", "grading")
  Tissue   — anatomical tissue/organ (e.g. "lung", "prostate", "colon")
  Dataset  — datasets (e.g. "TCGA-LUAD", "Camelyon16", "PAIP")
  Metric   — performance metrics (e.g. "AUC", "F1-score", "accuracy")

Relation types (use EXACTLY these strings):
  APPLIES_METHOD   — paper uses this AI method
  TARGETS_DISEASE  — paper studies this disease
  OPERATES_ON      — paper processes this tissue type
  PERFORMS_TASK    — paper addresses this computational task
  USES_DATASET     — paper evaluates on this dataset
  ACHIEVES_METRIC  — paper reports this metric (put value like "AUC=0.95" in metric_value)
  RELATED_TO       — connects two Methods that are closely related/compared

Rules:
  - Extract only facts clearly stated in the abstract
  - Normalize entity names: concise, use standard terminology
  - Aim for 5-20 triples per abstract
  - Do not hallucinate

You MUST respond with this exact JSON structure:
{
  "triples": [
    {
      "subject": {"name": "entity name", "type": "Method"},
      "relation": "APPLIES_METHOD",
      "object": {"name": "entity name", "type": "Task"},
      "metric_value": null
    }
  ]
}
"""

_TRIPLE_USER = """\
Title: {title}
Abstract: {abstract}

Extract knowledge triples.
"""


# ─────────────────────────────────────────────────────────────────────────────
# LLM call with retry
# ─────────────────────────────────────────────────────────────────────────────

def _parse_llm_json(content: str) -> dict:
    """Parse LLM JSON response robustly.
    - Strips markdown code fences
    - Auto-wraps bare arrays as {"triples": [...]}
    """
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            ln for ln in lines if not ln.strip().startswith("```")
        ).strip()
    parsed = json.loads(content)
    if isinstance(parsed, list):
        return {"triples": parsed}
    return parsed


def _llm_call_structured(system: str, user: str, response_schema: type[BaseModel]) -> dict:
    """Call LLM with json_object format and return parsed dict.
    Uses json_object (works with Qwen/DashScope); no json_schema attempt.
    """
    for attempt in range(config.LLM_RETRY_ATTEMPTS):
        try:
            response = _client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=config.LLM_MAX_TOKENS,
                temperature=config.LLM_TEMPERATURE,
                response_format={"type": "json_object"},
                extra_body=llm_extra_body(config.OPENAI_API_BASE),
            )
            content = response.choices[0].message.content or "{}"
            return _parse_llm_json(content)
        except Exception as e:
            if attempt < config.LLM_RETRY_ATTEMPTS - 1:
                wait = config.LLM_RETRY_DELAY * (attempt + 1)
                print(f"  [LLM] Attempt {attempt+1} error: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [LLM] All retries failed: {e}")
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Per-paper extraction
# ─────────────────────────────────────────────────────────────────────────────

def _classify_study_type(title: str, abstract: str, pub_types: list[str]) -> str:
    """Step 1: classify study_type."""
    user_msg = _STUDY_TYPE_USER.format(
        title=title,
        pub_types=", ".join(pub_types) if pub_types else "N/A",
        abstract=truncate_for_llm(abstract, config.LLM_MAX_INPUT_CHARS),
    )
    raw = _llm_call_structured(_STUDY_TYPE_SYSTEM, user_msg, StudyTypeResult)
    try:
        result = StudyTypeResult.model_validate(raw)
        return result.study_type
    except Exception:
        # If LLM returned a plain string value somewhere in the dict, try to salvage it
        for val in raw.values():
            if isinstance(val, str) and val in config.STUDY_TYPES:
                return val
        return "other"


def _extract_triples(
    title: str,
    abstract: str,
    paper_id: int,
    pmid: str,
) -> list[Triple]:
    """Step 2: extract entity-relation triples."""
    user_msg = _TRIPLE_USER.format(
        title=title,
        abstract=truncate_for_llm(abstract, config.LLM_MAX_INPUT_CHARS),
    )
    raw = _llm_call_structured(_TRIPLE_SYSTEM, user_msg, ExtractionResult)
    if not raw:
        return []
    try:
        result = ExtractionResult.model_validate(raw)
        return result.triples
    except Exception:
        # Try to salvage valid triples from a partially-malformed response
        raw_list = raw.get("triples", [])
        if not isinstance(raw_list, list):
            return []
        valid: list[Triple] = []
        for item in raw_list:
            try:
                valid.append(Triple.model_validate(item))
            except Exception:
                pass
        if valid:
            return valid
        print(f"  [LLM] Could not parse any triples for PMID {pmid}. Raw keys: {list(raw.keys())}")
        return []


def _save_triples(triples: list[Triple], paper_id: int, pmid: str) -> None:
    """Upsert entities and insert relation rows into DB."""
    for triple in triples:
        subj = triple.subject
        obj = triple.object

        # Subject: always the paper itself for paper-centric relations
        # But RELATED_TO is entity → entity
        if triple.relation == "RELATED_TO":
            subj_id = upsert_entity(subj.name, subj.type)
            obj_id = upsert_entity(obj.name, obj.type)
            insert_relation(
                subject_type=subj.type,
                subject_id=subj_id,
                relation=triple.relation,
                object_type=obj.type,
                object_id=obj_id,
                source_pmid=pmid,
                confidence=triple.confidence,
            )
        else:
            # subject is the Paper, object is the entity
            obj_id = upsert_entity(obj.name, obj.type)
            insert_relation(
                subject_type="Paper",
                subject_id=paper_id,
                relation=triple.relation,
                object_type=obj.type,
                object_id=obj_id,
                source_pmid=pmid,
                metric_value=triple.metric_value or "",
                confidence=triple.confidence,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction loop
# ─────────────────────────────────────────────────────────────────────────────

def run_extraction(limit: int = 0) -> None:
    """
    Process all unextracted papers.
    limit=0 means process all. Set limit=N for testing.
    """
    papers = get_unprocessed_papers(limit=limit)
    print(f"[Extractor] {len(papers)} papers to process.")

    for paper in tqdm(papers, desc="[Extractor] Processing", unit="paper"):
        paper_id = paper["id"]
        pmid = paper["pmid"] or ""
        title = paper["title"] or ""
        abstract = paper["abstract"] or ""
        pub_types_raw = paper["pub_types"] or "[]"

        try:
            pub_types = json.loads(pub_types_raw)
        except Exception:
            pub_types = []

        if not abstract.strip():
            mark_extraction_done(paper_id, "other")
            continue

        try:
            # Step 1: study type
            study_type = _classify_study_type(title, abstract, pub_types)

            # Step 2: triples
            triples = _extract_triples(title, abstract, paper_id, pmid)
            _save_triples(triples, paper_id, pmid)

            mark_extraction_done(paper_id, study_type)

        except Exception as e:
            print(f"\n  [Extractor] Error on PMID {pmid}: {e}")
            mark_extraction_done(paper_id, "other")

    print("[Extractor] Extraction complete.")


if __name__ == "__main__":
    from utils.db import init_db
    init_db()
    run_extraction(limit=10)  # test with 10 papers
