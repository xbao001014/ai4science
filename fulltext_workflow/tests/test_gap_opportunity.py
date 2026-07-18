"""Unit tests for Visualization opportunity rows (no Streamlit / plotly)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from viz.gap_opportunity import data_support_tier, summarize_opportunities  # noqa: E402


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
