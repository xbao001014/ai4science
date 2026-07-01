"""Shared LLM extraction from parsed sections (PyMuPDF / MinerU)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config as wf_config  # noqa: E402
from extractor.section_extractor import Triple, _extract_from_text  # noqa: E402


def triple_to_dict(t: Triple) -> dict[str, Any]:
    return {
        "relation": t.relation,
        "object_name": t.object.name,
        "object_type": t.object.type,
        "metric_value": t.metric_value,
        "confidence": t.confidence,
        "evidence_quote": t.evidence_quote,
        "polarity": t.polarity,
    }


def extract_triples_from_sections(
    title: str,
    sections: list[dict[str, Any]],
    *,
    granularity: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run section-aware LLM extraction. Returns (triples, section_stats)."""
    extract_types = set(wf_config.SECTIONS_FOR_EXTRACTION.keys()) | {
        "abstract",
        "introduction",
        "other",
    }
    all_triples: list[dict[str, Any]] = []
    section_stats: list[dict[str, Any]] = []

    for sec in sections:
        sec_type = sec["section_type"]
        if sec_type not in extract_types:
            continue
        triples = _extract_from_text(
            title,
            sec_type,
            sec.get("title") or sec_type,
            sec["content"],
        )
        for t in triples:
            row = triple_to_dict(t)
            row["evidence_section"] = sec_type
            row["extraction_granularity"] = granularity
            all_triples.append(row)
        section_stats.append(
            {
                "section_type": sec_type,
                "title": sec.get("title", ""),
                "char_count": len(sec["content"]),
                "triple_count": len(triples),
            }
        )

    return all_triples, section_stats
