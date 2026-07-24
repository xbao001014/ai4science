"""Resolve Dataset access_class: public | private | unknown.

Precedence when merging: public > private > unknown.
Public curated aliases win over LLM hints and private cues.
"""
from __future__ import annotations

import re
from typing import Literal

AccessClass = Literal["public", "private", "unknown"]

_ACCESS_RANK: dict[str, int] = {"unknown": 0, "private": 1, "public": 2}

# Canonical public pathology / computational-pathology benchmarks (extend as needed).
PUBLIC_DATASET_ALIASES: dict[str, str] = {
    "camelyon16": "camelyon16",
    "camelyon17": "camelyon17",
    "camelyon 16": "camelyon16",
    "camelyon 17": "camelyon17",
    "camelyon": "camelyon16",
    "tcga": "tcga",
    "the cancer genome atlas": "tcga",
    "panda": "panda",
    "panda challenge": "panda",
    "breakhis": "breakhis",
    "breakhis dataset": "breakhis",
    "cptac": "cptac",
    "bach": "bach",
    "bach dataset": "bach",
    "digestpath": "digestpath",
    "digestpath2019": "digestpath",
    "midog": "midog",
    "midog2021": "midog",
    "midog2022": "midog",
    "tulip": "tulip",
    "sicapv2": "sicapv2",
    "sicap": "sicapv2",
    "panda dataset": "panda",
    "tcga-brca": "tcga",
    "tcga brca": "tcga",
    "tcga-luad": "tcga",
    "tcga-lusc": "tcga",
    "tcga-prad": "tcga",
    "tcga-coad": "tcga",
    "tcga-stad": "tcga",
    "kiwi": "kiwi",
    "kiwi challenge": "kiwi",
    "panda prostate": "panda",
    "camelyon16 dataset": "camelyon16",
    "camelyon17 dataset": "camelyon17",
}

_PRIVATE_CUES = re.compile(
    r"\b("
    r"in[\s-]?house|institutional|our\s+hospital|our\s+institution|"
    r"private\s+cohort|private\s+dataset|internal\s+cohort|"
    r"single[\s-]center\s+cohort|locally\s+collected|"
    r"proprietary\s+dataset|confidential\s+cohort"
    r")\b",
    re.I,
)


def _norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def normalize_dataset_name(name: str) -> str:
    key = _norm_key(name)
    return PUBLIC_DATASET_ALIASES.get(key, key)


def stronger_access(a: str | None, b: str | None) -> AccessClass:
    """Return the stronger of two access classes."""
    ra = _ACCESS_RANK.get((a or "unknown").lower(), 0)
    rb = _ACCESS_RANK.get((b or "unknown").lower(), 0)
    winner = a if ra >= rb else b
    w = (winner or "unknown").lower()
    if w in ("public", "private", "unknown"):
        return w  # type: ignore[return-value]
    return "unknown"


def resolve_dataset_access(
    name: str,
    *,
    evidence_quote: str | None = None,
    access_hint: str | None = None,
) -> AccessClass:
    """Resolve access_class for a dataset mention.

    Order: public alias list → private cues (name/evidence) → LLM hint → unknown.
    """
    key = _norm_key(name)
    if key in PUBLIC_DATASET_ALIASES or any(
        key == canon or key.startswith(canon + " ") or canon in key
        for canon in set(PUBLIC_DATASET_ALIASES.values())
    ):
        # Prefer exact alias / known canonical token in name
        if key in PUBLIC_DATASET_ALIASES:
            return "public"
        for canon in set(PUBLIC_DATASET_ALIASES.values()):
            if re.search(rf"(^|[^a-z0-9]){re.escape(canon)}([^a-z0-9]|$)", key):
                return "public"

    blob = f"{key} {(evidence_quote or '').lower()}"
    if _PRIVATE_CUES.search(blob):
        return "private"

    hint = (access_hint or "").strip().lower()
    if hint in ("public", "private", "unknown"):
        # Never let hint override a public alias (already returned); private/unknown ok
        if hint == "public":
            # Unlisted "public" from LLM — trust with caution; keep as public
            return "public"
        return hint  # type: ignore[return-value]

    return "unknown"
