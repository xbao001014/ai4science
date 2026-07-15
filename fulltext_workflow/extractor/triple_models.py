"""Pydantic models for knowledge-graph triple extraction."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

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
