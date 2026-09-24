"""Shared synonym-aware query planning and deterministic lexical ranking."""
from __future__ import annotations

import re
from typing import Any

from analysis.disease_synonyms import expand_focus_terms, resolve_disease_concept
from analysis.method_synonyms import find_method_concepts

_STOPWORDS = frozenset({
    "a", "an", "and", "as", "at", "based", "between", "by", "for", "from",
    "in", "into", "of", "on", "or", "over", "the", "through", "to", "under",
    "using", "via", "with",
})

_TOKEN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "cancer": ("cancer", "carcinoma", "neoplasm", "tumor", "tumour"),
    "carcinoma": ("cancer", "carcinoma", "neoplasm", "tumor", "tumour"),
    "neoplasm": ("cancer", "carcinoma", "neoplasm", "tumor", "tumour"),
    "tumor": ("cancer", "carcinoma", "neoplasm", "tumor", "tumour"),
    "tumour": ("cancer", "carcinoma", "neoplasm", "tumor", "tumour"),
    "breast": ("breast", "mammary"),
    "lung": ("lung", "pulmonary"),
    "liver": ("liver", "hepatic", "hepatocellular"),
    "colon": ("colon", "colonic", "colorectal", "rectal"),
    "nasopharyngeal": ("nasopharyngeal", "nasopharynx"),
}


def _surface(text: Any) -> str:
    value = str(text or "").casefold()
    # '+' is identity-bearing in names such as U-Net++ and must not disappear.
    value = re.sub(r"[^a-z0-9+\u3400-\u9fff]+", " ", value)
    return " ".join(value.split())


def _tokens(text: Any) -> list[str]:
    return [
        token for token in _surface(text).split()
        if len(token) >= 2 and token not in _STOPWORDS
    ]


def _contains(text: Any, phrase: str) -> bool:
    haystack = f" {_surface(text)} "
    needle = _surface(phrase)
    if not needle:
        return False
    if re.search(r"[\u3400-\u9fff]", needle):
        return needle in haystack
    return f" {needle} " in haystack


def build_retrieval_plan(query: str) -> dict[str, Any]:
    """Build semantic units so aliases count as one required query dimension."""
    raw = str(query or "").strip()
    units: list[dict[str, Any]] = []
    covered_tokens: set[str] = set()

    disease = resolve_disease_concept(raw)
    if disease:
        expansion = expand_focus_terms(raw)
        surfaces = [
            expansion.get("canonical") or "",
            *(expansion.get("phrases") or []),
            *(expansion.get("abbreviations") or []),
            *(expansion.get("zh") or []),
        ]
        matched = [surface for surface in surfaces if _contains(raw, surface)]
        if matched:
            covered_tokens.update(token for value in matched for token in _tokens(value))
            units.append({
                "id": f"disease:{disease.id}",
                "kind": "disease",
                "canonical": disease.canonical,
                "phrases": sorted({str(value).casefold().strip() for value in surfaces if value}),
            })

    for concept in find_method_concepts(raw):
        aliases = [str(value) for value in concept.get("aliases", [])]
        matched = [surface for surface in aliases if _contains(raw, surface)]
        if not matched:
            continue
        covered_tokens.update(token for value in matched for token in _tokens(value))
        canonical = str(concept["canonical"])
        units.append({
            "id": f"method:{canonical}",
            "kind": "method",
            "canonical": canonical,
            "phrases": sorted({str(value).casefold().strip() for value in aliases if value}),
        })

    seen_tokens: set[str] = set()
    for token in _tokens(raw):
        if token in covered_tokens or token in seen_tokens:
            continue
        seen_tokens.add(token)
        phrases = _TOKEN_SYNONYMS.get(token, (token,))
        units.append({
            "id": f"token:{token}",
            "kind": "token",
            "canonical": token,
            "phrases": list(phrases),
        })

    return {
        "query": raw,
        "normalized_query": _surface(raw),
        "units": units,
        "disease_concept_id": disease.id if disease and any(
            unit["kind"] == "disease" for unit in units
        ) else None,
        "method_concepts": [
            unit["canonical"] for unit in units if unit["kind"] == "method"
        ],
    }


def candidate_phrases(plan: dict[str, Any], *, limit: int = 40) -> list[str]:
    """Flatten query-unit alternatives for a broad SQL candidate prefilter."""
    out: list[str] = []
    seen: set[str] = set()
    for unit in plan.get("units", []):
        for phrase in unit.get("phrases", []):
            value = str(phrase).casefold().strip()
            if value and value not in seen:
                seen.add(value)
                out.append(value)
                if len(out) >= limit:
                    return out
    return out


def minimum_required_units(plan: dict[str, Any]) -> int:
    count = len(plan.get("units", []))
    if count <= 1:
        return count
    if count == 2:
        return 2
    return max(2, (count + 1) // 2)


def score_retrieval_fields(
    plan: dict[str, Any],
    fields: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Score fields by matched semantic units, not duplicate alias surfaces."""
    field_weights = weights or {
        "title": 5.0,
        "entity_names": 4.0,
        "keywords": 3.0,
        "mesh_terms": 2.5,
        "source_queries": 2.0,
        "evidence_quote": 2.0,
        "abstract": 1.0,
    }
    matched_units: set[str] = set()
    matched_by_field: dict[str, list[str]] = {}
    score = 0.0
    # Abstracts and aggregated entity names can be long. Normalize each field
    # once per paper rather than once for every synonym of every query unit.
    surfaces = {
        field: f" {_surface(fields.get(field))} "
        for field in field_weights
        if fields.get(field)
    }
    for field, weight in field_weights.items():
        haystack = surfaces.get(field)
        if not haystack:
            continue
        field_hits: list[str] = []
        for unit in plan.get("units", []):
            if any(
                (needle in haystack if re.search(r"[\u3400-\u9fff]", needle)
                 else f" {needle} " in haystack)
                for needle in (_surface(phrase) for phrase in unit.get("phrases", []))
                if needle
            ):
                unit_id = str(unit["id"])
                matched_units.add(unit_id)
                field_hits.append(str(unit["canonical"]))
                score += float(weight)
        if field_hits:
            matched_by_field[field] = field_hits

    required = minimum_required_units(plan)
    required_concepts = {
        str(unit["id"])
        for unit in plan.get("units", [])
        if unit.get("kind") in {"disease", "method"}
    }
    concepts_matched = required_concepts <= matched_units
    return {
        "score": round(score, 3),
        "matched_unit_count": len(matched_units),
        "required_unit_count": required,
        "matched": concepts_matched and len(matched_units) >= required and score > 0,
        "required_concepts_matched": concepts_matched,
        "matched_units": sorted(matched_units),
        "matched_by_field": matched_by_field,
    }


def full_query_matches(plan: dict[str, Any], *values: Any) -> bool:
    phrase = str(plan.get("normalized_query") or "")
    return bool(phrase) and any(_contains(value, phrase) for value in values)
