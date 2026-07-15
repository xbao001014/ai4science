"""Post-processing for extracted Method / Limitation entities."""
from __future__ import annotations

import re

from extractor.triple_models import Triple

_GENERIC_METHODS = frozenset(
    {
        "ai",
        "artificial intelligence",
        "deep learning",
        "dl",
        "machine learning",
        "machine learning algorithms",
        "ml",
        "radiomics",
        "neural network",
        "neural networks",
        "statistical analysis",
        "statistical methods",
    }
)

_NO_APPLIES_METHOD_SECTIONS = frozenset({"discussion", "future_work", "introduction"})

_LIMITATION_ALIASES: dict[str, str] = {
    "limited sample size": "small sample size",
    "small dataset size": "small sample size",
    "limited dataset size": "small sample size",
    "small cohort size": "small sample size",
    "small sample sizes": "small sample size",
    "retrospective study design": "retrospective design",
    "retrospective nature": "retrospective design",
    "retrospective single-center design": "retrospective single-center design",
    "retrospective single-center study": "retrospective single-center design",
    "single-center retrospective design": "retrospective single-center design",
    "need for external validation": "lack of external validation",
    "need for prospective validation": "lack of prospective validation",
    "need for further validation in larger cohorts": "lack of external validation",
    "limited generalizability": "limited generalizability",
    "limited interpretability": "lack of interpretability",
    "lack of interpretability": "lack of interpretability",
}


def _norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def is_generic_method(name: str) -> bool:
    return _norm_key(name) in _GENERIC_METHODS


def normalize_entity_name(name: str, entity_type: str) -> str:
    key = _norm_key(name)
    if entity_type == "Limitation":
        return _LIMITATION_ALIASES.get(key, key)
    return key


def postprocess_triples(triples: list[Triple], section_type: str) -> list[Triple]:
    """Filter low-value methods and normalize entity names."""
    specific_methods = {
        _norm_key(t.object.name)
        for t in triples
        if t.relation == "APPLIES_METHOD"
        and t.object.type == "Method"
        and not is_generic_method(t.object.name)
    }

    out: list[Triple] = []
    for triple in triples:
        if (
            triple.relation == "APPLIES_METHOD"
            and section_type in _NO_APPLIES_METHOD_SECTIONS
        ):
            continue

        obj_name = triple.object.name
        obj_type = triple.object.type
        if obj_type in ("Method", "Limitation"):
            obj_name = normalize_entity_name(obj_name, obj_type)

        if (
            triple.relation == "APPLIES_METHOD"
            and obj_type == "Method"
            and specific_methods
            and is_generic_method(obj_name)
        ):
            continue

        subj = triple.subject
        if triple.relation == "RELATED_TO" and subj.type == "Method":
            subj_name = normalize_entity_name(subj.name, "Method")
            subj = subj.model_copy(update={"name": subj_name})

        confidence = triple.confidence
        if triple.relation == "APPLIES_METHOD" and obj_type == "Method":
            if is_generic_method(obj_name):
                confidence = min(confidence, 0.5)

        obj = triple.object.model_copy(update={"name": obj_name})
        out.append(
            triple.model_copy(
                update={
                    "subject": subj,
                    "object": obj,
                    "confidence": confidence,
                }
            )
        )
    return out
