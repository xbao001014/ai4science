"""Unit tests for gap debate visualizations (no plotly required)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from viz.gap_viz import (  # noqa: E402
    build_molecular_bar,
    build_subtype_bar,
    count_scout_candidates,
    debate_funnel_stats,
    extract_skeptic_breakdown,
    tool_category_stats,
)


def test_count_scout_candidates_from_headings():
    text = "### Research Gap 1: radiomics NSCLC\n### Research Gap 2: deep learning CRC"
    assert count_scout_candidates(text) == 2


def test_debate_funnel_stats_from_events():
    events = [
        {"type": "optimist_proposal", "content": "### Gap 1: A\n### Gap 2: B\n### Gap 3: C"},
        {
            "type": "skeptic_review",
            "content": '```json\n{"verified_gaps":[{"title":"A"}],"false_gaps":[{"title":"X"}],"weak_evidence_gaps":[]}\n```',
        },
    ]
    report = "### Research Gap 1: A\n### Research Gap 2: B"
    stats = debate_funnel_stats(events, report)
    assert stats["scout_candidates"] == 3
    assert stats["verified"] == 1
    assert stats["false_gaps"] == 1
    assert stats["final_gaps"] == 2


def test_extract_skeptic_breakdown_uses_latest_round():
    events = [
        {
            "type": "skeptic_review",
            "content": '```json\n{"verified_gaps":[],"false_gaps":[],"weak_evidence_gaps":[]}\n```',
        },
        {
            "type": "skeptic_review",
            "content": '```json\n{"verified_gaps":[{"title":"v"}],"false_gaps":[],"weak_evidence_gaps":[{"title":"w"}]}\n```',
        },
    ]
    b = extract_skeptic_breakdown(events)
    assert b == {"verified": 1, "false": 0, "weak": 1}


def test_tool_category_stats():
    events = [
        {
            "type": "tool_result",
            "name": "hotspot_entities",
            "result": {"data": [{"x": 1}, {"x": 2}]},
        },
    ]
    meta = {"hotspot_entities": {"label": "Hotspot", "category": "Impact"}}
    rows = tool_category_stats(events, meta)
    assert rows[0]["records"] == 2
    assert rows[0]["category"] == "Impact"


def test_subtype_bar_empty_returns_none():
    assert build_subtype_bar([]) is None


def test_molecular_bar_empty_returns_none():
    assert build_molecular_bar([]) is None
