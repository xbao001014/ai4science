"""Unit tests for weekly hotspot scoring."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.impact_scoring import literature_gap_points
from analysis.weekly_hotspot import emerging_score, previous_week_id, week_id  # noqa: E402


def test_emerging_score_velocity_boost():
    low = emerging_score(2, 2, 5.0, 1.0, 0.0)
    high = emerging_score(5, 1, 5.0, 1.0, 0.0)
    assert high > low


def test_emerging_score_zero_recent():
    assert emerging_score(0, 5, 10.0, 2.0, 5.0) == 0.0


def test_week_id_format():
    wid = week_id()
    assert "-W" in wid
    assert len(wid) >= 7


def test_previous_week_id():
    assert previous_week_id("2026-W10") == "2026-W09"
    prev = previous_week_id("2026-W02")
    assert "-W" in prev and len(prev) >= 7


def test_opportunity_score_formula():
    hot = emerging_score(5, 1, 10.0, 2.0, 3.0)
    opp = round(hot + literature_gap_points("unexplored"), 2)
    assert opp >= 5.0


if __name__ == "__main__":
    test_emerging_score_velocity_boost()
    test_emerging_score_zero_recent()
    test_week_id_format()
    test_previous_week_id()
    test_opportunity_score_formula()
    print("all ok")
