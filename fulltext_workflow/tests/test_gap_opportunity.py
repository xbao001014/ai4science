"""Unit tests for Visualization opportunity rows (no Streamlit / plotly)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from viz.gap_opportunity import (  # noqa: E402
    build_opportunity_rows,
    data_support_tier,
    sort_opportunity_rows,
    summarize_opportunities,
)


def test_data_support_tier_boundaries():
    assert data_support_tier(None, mapped=False) == "none"
    assert data_support_tier(999, mapped=False) == "none"
    assert data_support_tier(None, mapped=True) == "none"
    assert data_support_tier(0, mapped=True) == "low"
    assert data_support_tier(199, mapped=True) == "low"
    assert data_support_tier(200, mapped=True) == "medium"
    assert data_support_tier(499, mapped=True) == "medium"
    assert data_support_tier(500, mapped=True) == "high"


def test_summarize_opportunities():
    rows = [
        {"gap": "unexplored", "disease_id": "A", "data": "high"},
        {"gap": "minimal", "disease_id": "B", "data": "low"},
        {"gap": "active", "disease_id": None, "data": "none"},
    ]
    s = summarize_opportunities(rows)
    assert s["combo_count"] == 3
    assert s["scarce_count"] == 2
    assert s["mapped_count"] == 2
    assert s["high_share"] == 100 * 1 / 3


def test_sort_opportunity_rows_priority():
    rows = [
        {"source": "Corpus", "gap": "minimal", "data": "high", "paper_cnt": 0, "method": "B", "disease": "X"},
        {"source": "Debate", "gap": "unexplored", "data": "low", "paper_cnt": 5, "method": "A", "disease": "Y"},
        {"source": "Corpus", "gap": "unexplored", "data": "medium", "paper_cnt": 1, "method": "A", "disease": "Z"},
        {"source": "Corpus", "gap": "unexplored", "data": "medium", "paper_cnt": 0, "method": "A", "disease": "W"},
    ]
    ordered = sort_opportunity_rows(rows)
    assert [r["disease"] for r in ordered] == ["Y", "W", "Z", "X"]


def test_build_opportunity_rows_tiers_and_keys():
    gaps = [
        {"method": "CLAM", "disease": "NPC", "paper_cnt": 0, "gap": "unexplored"},
        {"method": "MIL", "disease": "UnknownCa", "paper_cnt": 1, "gap": "minimal"},
    ]
    cases = {"NPC-CODE": 600}
    ids = {"NPC": "NPC-CODE", "UnknownCa": None}
    rows = build_opportunity_rows(gaps, cases, ids)
    assert rows[0]["row_key"] == "CLAM||NPC"
    assert rows[0]["disease_id"] == "NPC-CODE"
    assert rows[0]["data"] == "high"
    assert rows[0]["source"] == "Corpus"
    assert rows[1]["disease_id"] is None
    assert rows[1]["data"] == "none"
