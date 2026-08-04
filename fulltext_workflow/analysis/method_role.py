"""Method architecture role for weekly hotspot display (backbone vs aggregator)."""
from __future__ import annotations

import re
from typing import Literal

from analysis.method_synonyms import resolve_method_canonical
from extractor.entity_normalize import _norm_key

MethodRole = Literal["backbone", "aggregator", "unknown"]

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
})

_AGGREGATOR_ALIASES = frozenset({
    # Common MIL framework names assigned to the aggregator role.
    "abmil",
    "clam",
    "dsmil",
    "transmil",
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


def classify_method_role(name: str) -> MethodRole:
    canonical = resolve_method_canonical(name)
    key = _norm_key(canonical)
    # Aggregator aliases before backbone aliases (conflict → aggregator).
    if key in _AGGREGATOR_ALIASES:
        return "aggregator"
    if key in _BACKBONE_ALIASES:
        return "backbone"
    if any(p.search(key) for p in _AGGREGATOR_PATTERNS):
        return "aggregator"
    if any(p.search(key) for p in _BACKBONE_PATTERNS):
        return "backbone"
    return "unknown"


def annotate_method_role(
    rows: list[dict],
    *,
    name_key: str = "name",
) -> list[dict]:
    for row in rows:
        row["method_role"] = classify_method_role(str(row.get(name_key) or ""))
    return rows
