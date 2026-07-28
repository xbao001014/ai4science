"""Controlled action types and recommendation row normalization for Pass 2."""
from __future__ import annotations

import re
from typing import Any

ACTION_TYPES: frozenset[str] = frozenset(
    {
        "external_validation",
        "expand_sample",
        "multicenter",
        "prospective_design",
        "multimodal",
        "method_refinement",
        "dataset_enrichment",
        "other",
    }
)

_GROUNDINGS = frozenset({"author_stated", "synthesized"})

_VAGUE_RE = re.compile(
    r"^\s*(more research is needed|further studies? (are|is) (needed|warranted)|"
    r"future work is needed|additional studies are required)\s*\.?$",
    re.I,
)

MAX_RECOMMENDATIONS_PER_PAPER = 8


def is_vague_suggestion(text: str) -> bool:
    return bool(_VAGUE_RE.match((text or "").strip()))


def parse_recommendation_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action_type") or "").strip()
        if action not in ACTION_TYPES:
            continue
        suggestion = str(raw.get("suggestion") or "").strip()
        if not suggestion or is_vague_suggestion(suggestion):
            continue
        quote = str(raw.get("evidence_quote") or "").strip()
        if not quote:
            continue
        grounding = str(raw.get("grounding") or "synthesized").strip()
        if grounding not in _GROUNDINGS:
            grounding = "synthesized"
        limitation = str(raw.get("limitation") or "").strip()
        try:
            conf = float(raw.get("confidence") if raw.get("confidence") is not None else 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        key = (action, limitation.lower(), suggestion.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "limitation": limitation,
                "action_type": action,
                "suggestion": suggestion,
                "evidence_quote": quote,
                "evidence_section": str(raw.get("evidence_section") or "").strip(),
                "grounding": grounding,
                "confidence": conf,
            }
        )
        if len(out) >= MAX_RECOMMENDATIONS_PER_PAPER:
            break
    return out
