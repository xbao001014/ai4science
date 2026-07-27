"""Unit tests for fulltext reconcile assemble/parse helpers."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_assemble_prefers_core_sections_and_truncates():
    from extractor.fulltext_reconcile import assemble_reconcile_text

    sections = [
        {"section_type": "introduction", "content": "INTRO " * 5000},
        {"section_type": "methods", "content": "METHODS " * 100},
        {"section_type": "discussion", "content": "DISC " * 100},
        {"section_type": "limitations", "content": "LIM " * 50},
    ]
    text = assemble_reconcile_text(sections, max_chars=2000)
    assert "METHODS" in text
    assert "LIM" in text
    assert len(text) <= 2000


def test_parse_reconcile_payload_normalizes():
    from extractor.fulltext_reconcile import parse_reconcile_payload

    raw = {
        "datasets": [
            {
                "name": "PubMed",
                "access": "public",
                "action": "drop",
                "reason": "platform",
            }
        ],
        "bindings": [
            {"method": "CNN", "disease": "breast cancer", "dataset": "", "quote": "q"}
        ],
        "limitations": [
            {"canonical": "small sample size", "merges": ["small n"], "quote": "q2"}
        ],
    }
    p = parse_reconcile_payload(raw)
    assert p["datasets"][0]["action"] == "drop"
    assert p["bindings"][0]["dataset"] == ""
    assert p["limitations"][0]["canonical"] == "small sample size"
