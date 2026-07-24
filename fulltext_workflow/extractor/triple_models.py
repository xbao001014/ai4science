"""Pydantic models for knowledge-graph triple extraction."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

EntityTypeLiteral = Literal[
    "Disease", "Method", "Task", "Tissue", "Dataset", "Metric", "Modality", "Limitation"
]

_ENTITY_TYPES = frozenset(
    ("Disease", "Method", "Task", "Tissue", "Dataset", "Metric", "Modality", "Limitation")
)

RelationLiteral = Literal[
    "APPLIES_METHOD",
    "COMPARES_METHOD",
    "TARGETS_DISEASE",
    "OPERATES_ON",
    "PERFORMS_TASK",
    "USES_DATASET",
    "ACHIEVES_METRIC",
    "RELATED_TO",
    "REPORTS_LIMITATION",
    "USES_MODALITY",
]

# Placeholder subject for Paper→X triples (replaced by real Paper at ingest).
_PAPER_SUBJECT = {"name": "paper", "type": "Method"}


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
    # Dataset-only hint from LLM; resolved to entities.access_class at ingest.
    access_hint: Optional[Literal["public", "private", "unknown"]] = None

    @model_validator(mode="before")
    @classmethod
    def coerce_llm_quirks(cls, data: Any) -> Any:
        """Accept common LLM output that would otherwise fail validation.

        - subject.type \"Paper\" (or unknown): coerced — Paper→X ingest ignores subject
        - metric_value as number: coerced to string
        - access_hint case-normalized
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)
        subj = out.get("subject")
        if isinstance(subj, dict):
            st = subj.get("type")
            if not isinstance(st, str) or st not in _ENTITY_TYPES:
                out["subject"] = {
                    "name": (subj.get("name") or "paper"),
                    "type": _PAPER_SUBJECT["type"],
                }
                if isinstance(st, str) and st.lower() == "paper":
                    out["subject"]["name"] = subj.get("name") or "paper"
        mv = out.get("metric_value")
        if mv is not None and not isinstance(mv, str):
            out["metric_value"] = str(mv)
        hint = out.get("access_hint")
        if isinstance(hint, str):
            h = hint.strip().lower()
            out["access_hint"] = h if h in ("public", "private", "unknown") else None
        return out


class ExtractionResult(BaseModel):
    triples: list[Triple] = Field(default_factory=list)
