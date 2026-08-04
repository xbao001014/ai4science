"""Method architecture role for weekly hotspot display."""
from __future__ import annotations

import re
from typing import Literal

from analysis.method_synonyms import resolve_method_canonical
from extractor.entity_normalize import _norm_key

MethodRole = Literal["backbone", "aggregator", "classical_ml", "tool", "unknown"]
VALID_METHOD_ROLES = frozenset(
    {"backbone", "aggregator", "classical_ml", "tool", "unknown"}
)

# Exact aliases after _norm_key. If a name appears in both tables, aggregator wins.
_BACKBONE_ALIASES = frozenset({
    "resnet",
    "resnet-18",
    "resnet18",
    "resnet-50",
    "resnet50",
    "resnet-101",
    "resnet101",
    "vit",
    "vision transformer",
    "swin",
    "swin transformer",
    "efficientnet",
    "densenet",
    "densenet-121",
    "densenet121",
    "uni",
    "conch",
    "ctranspath",
    "hibou",
    "virchow",
    "phikon",
    "gigapath",
    "h-optimus",
    "hoptimus",
    "attention u-net",
    "attention-unet",
    "u-net",
    "unet",
    "hover-net",
    "segformer",
    "dinov2",
    "cnn",
    "convolutional neural network",
    "xception",
    "prov-gigapath",
})

_AGGREGATOR_ALIASES = frozenset({
    # Common MIL framework names assigned to the aggregator role.
    "abmil",
    "clam",
    "dsmil",
    "transmil",
})

_CLASSICAL_ML_ALIASES = frozenset({
    "random forest",
    "support vector machine",
    "xgboost",
    "lightgbm",
    "logistic regression",
    "cox proportional hazards regression",
})

_TOOL_ALIASES = frozenset({
    "qupath",
    "seurat",
    "gsva",
    "vosviewer",
})

# Aggregator cues — no bare \battention\b.
_AGGREGATOR_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\baggregator\b",
        r"\bmil\b",
        r"multiple\s+instance\s+learning",
        r"attention\s*pool",
        r"\bpooling\b",
        r"fusion\s+module",
        r"bag[\s\-]?level",
        r"instance[\s\-]?aggregat",
    )
)

_BACKBONE_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bresnet",
        r"\bvit\b",
        r"\bswin",
        r"\befficientnet",
        r"\bdensenet",
        r"\bvgg",
        r"\binception",
        r"\balexnet",
        r"\bmobilenet",
        r"\bconvnext",
        r"\bencoder\b",
        r"\bbackbone\b",
    )
)

_CLASSICAL_ML_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\brandom\s+forest",
        r"\bxgboost\b",
        r"\blightgbm\b",
        r"\bcatboost\b",
        r"\blogistic\s+regression",
        r"\bsupport\s+vector",
        r"\bcox\b",
        r"\bkaplan[\s\-]?meier",
        r"\bnaive\s+bayes",
        r"\belastic\s+net\b",
        r"\bgradient\s+boost",
    )
)

_TOOL_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bqupath\b",
        r"\bseurat\b",
        r"\bvosviewer\b",
        r"\bcitespace\b",
    )
)


def classify_method_role(name: str) -> MethodRole:
    key = _norm_key(resolve_method_canonical(name))
    if key in _AGGREGATOR_ALIASES:
        return "aggregator"
    if key in _BACKBONE_ALIASES:
        return "backbone"
    if key in _CLASSICAL_ML_ALIASES:
        return "classical_ml"
    if key in _TOOL_ALIASES:
        return "tool"
    if any(p.search(key) for p in _AGGREGATOR_PATTERNS):
        return "aggregator"
    if any(p.search(key) for p in _BACKBONE_PATTERNS):
        return "backbone"
    if any(p.search(key) for p in _CLASSICAL_ML_PATTERNS):
        return "classical_ml"
    if any(p.search(key) for p in _TOOL_PATTERNS):
        return "tool"
    return "unknown"


def resolve_method_role(name: str, llm_role: str | None = None) -> MethodRole:
    rule = classify_method_role(name)
    if rule != "unknown":
        return rule
    if isinstance(llm_role, str):
        hint = llm_role.strip().lower()
        if hint in VALID_METHOD_ROLES:
            return hint  # type: ignore[return-value]
    return "unknown"


def annotate_method_role(
    rows: list[dict],
    *,
    name_key: str = "name",
    role_by_name: dict[str, str] | None = None,
) -> list[dict]:
    role_by_name = role_by_name or {}
    for row in rows:
        raw = str(row.get(name_key) or "")
        key = _norm_key(resolve_method_canonical(raw))
        db = role_by_name.get(key) or role_by_name.get(raw)
        db_or_none = db if db in VALID_METHOD_ROLES else None
        row["method_role"] = resolve_method_role(raw, db_or_none)
    return rows
