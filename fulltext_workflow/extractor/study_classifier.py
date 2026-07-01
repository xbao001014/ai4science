"""Study type classification (Step 1)."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

import config
from extractor.llm_client import llm_call_structured

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
    rationale: str = ""


_STUDY_TYPE_SYSTEM = """\
You are an expert biomedical literature analyst specializing in pathology AI and radiomics research.
Classify the given paper into exactly ONE study type:
- ai_algorithm: Novel AI/deep learning algorithm development
- clinical_study: Clinical validation or patient outcome study
- review: Narrative or systematic review (not meta-analysis)
- meta_analysis: Quantitative meta-analysis
- dataset_benchmark: Dataset construction or benchmarking
- foundation_model: Large pre-trained or self-supervised model
- multimodal: Multiple data modalities (image + genomics/text/clinical)
- other: Does not fit above

Respond with JSON: {"study_type": "ai_algorithm"}
"""

_STUDY_TYPE_USER = """\
Title: {title}
PubMed Publication Types: {pub_types}
Abstract: {abstract}

Classify the study type.
"""


def classify_study_type_heuristic(pub_types: list[str]) -> str | None:
    """Rule-based study type; None if uncertain."""
    blob = " ".join(pub_types).lower()
    if "meta-analysis" in blob or "meta analysis" in blob:
        return "meta_analysis"
    if "systematic review" in blob or "review" in blob:
        return "review"
    if "clinical trial" in blob or "clinical study" in blob:
        return "clinical_study"
    if "validation study" in blob:
        return "clinical_study"
    return None


def classify_study_type(title: str, abstract: str, pub_types: list[str]) -> str:
    if config.EXTRACT_SKIP_STUDY_LLM:
        hit = classify_study_type_heuristic(pub_types)
        return hit or "ai_algorithm"
    hit = classify_study_type_heuristic(pub_types)
    if hit in ("meta_analysis", "review", "clinical_study"):
        return hit
    user_msg = _STUDY_TYPE_USER.format(
        title=title,
        pub_types=", ".join(pub_types) if pub_types else "N/A",
        abstract=(abstract or "")[:2000],
    )
    raw = llm_call_structured(_STUDY_TYPE_SYSTEM, user_msg)
    try:
        result = StudyTypeResult.model_validate(raw)
        return result.study_type
    except Exception:
        for val in raw.values():
            if isinstance(val, str) and val in config.STUDY_TYPES:
                return val
        return "other"
