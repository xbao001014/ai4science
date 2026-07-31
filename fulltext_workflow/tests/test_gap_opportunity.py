"""Unit tests for Visualization opportunity rows (no Streamlit / plotly)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from viz.gap_opportunity import (  # noqa: E402
    apply_debate_overlay,
    assemble_opportunity_view,
    build_opportunity_rows,
    data_support_tier,
    normalize_opportunity_gap,
    primary_viz_gaps,
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


def test_apply_debate_overlay_marks_and_unmatched():
    rows = [
        {"source": "Corpus", "method": "CLAM", "disease": "nasopharyngeal carcinoma", "row_key": "a"},
        {"source": "Corpus", "method": "MIL", "disease": "CRC", "row_key": "b"},
    ]
    titles = [
        "CLAM for nasopharyngeal carcinoma survival",
        "Radiomics habitat imaging leftover",
    ]
    updated, unmatched = apply_debate_overlay(rows, titles)
    assert updated[0]["source"] == "Debate"
    assert updated[1]["source"] == "Corpus"
    assert unmatched == ["Radiomics habitat imaging leftover"]
    # originals untouched
    assert rows[0]["source"] == "Corpus"


def test_assemble_opportunity_view_filters_and_debate():
    gaps = [
        {"method": "CLAM", "disease": "NPC", "paper_cnt": 0, "gap": "unexplored"},
        {"method": "MIL", "disease": "NPC", "paper_cnt": 5, "gap": "active"},
        {"method": "TransMIL", "disease": "CRC", "paper_cnt": 1, "gap": "minimal"},
    ]
    bundle = assemble_opportunity_view(
        gaps=gaps,
        disease_cases={"NPC-1": 500},
        disease_id_by_name={"NPC": "NPC-1", "CRC": None},
        debate_titles=["CLAM NPC survival"],
        scarce_only=True,
        limit=30,
    )
    assert len(bundle["rows"]) == 2  # active filtered out
    assert bundle["rows"][0]["source"] == "Debate"
    assert bundle["debate_matched_count"] == 1
    assert bundle["summary"]["combo_count"] == 2
    assert bundle["unmatched_debate"] == []


def test_normalize_opportunity_gap_maps_transferable_fields():
    g = normalize_opportunity_gap({
        "method": "clam",
        "disease": "npc",
        "literature_gap": "unexplored",
        "literature_paper_cnt": 0,
        "bridge_task": "survival prediction",
        "bridge_mode": "same_paper",
        "bridge_quality": "ok",
        "support_diseases": "crc, brca",
        "opportunity_score": 12.5,
    })
    assert g["gap"] == "unexplored"
    assert g["paper_cnt"] == 0
    assert g["bridge_task"] == "survival prediction"
    assert g["opportunity_score"] == 12.5


def test_build_opportunity_rows_keeps_bridge_columns():
    gaps = [
        normalize_opportunity_gap({
            "method": "CLAM",
            "disease": "NPC",
            "literature_gap": "unexplored",
            "literature_paper_cnt": 0,
            "bridge_task": "survival prediction",
            "bridge_mode": "cross_paper",
            "bridge_quality": "ok",
            "support_diseases": "crc",
            "opportunity_score": 9.0,
        })
    ]
    rows = build_opportunity_rows(gaps, {"NPC-CODE": 600}, {"NPC": "NPC-CODE"})
    assert rows[0]["bridge_task"] == "survival prediction"
    assert rows[0]["bridge_mode"] == "cross_paper"
    assert rows[0]["opportunity_score"] == 9.0
    assert rows[0]["data"] == "high"


def test_sort_opportunity_rows_prefers_opportunity_score():
    rows = [
        {
            "source": "Corpus",
            "gap": "unexplored",
            "data": "high",
            "paper_cnt": 0,
            "method": "B",
            "disease": "X",
            "opportunity_score": 1.0,
        },
        {
            "source": "Corpus",
            "gap": "unexplored",
            "data": "low",
            "paper_cnt": 0,
            "method": "A",
            "disease": "Y",
            "opportunity_score": 10.0,
        },
        {
            "source": "Debate",
            "gap": "minimal",
            "data": "none",
            "paper_cnt": 1,
            "method": "C",
            "disease": "Z",
            "opportunity_score": 2.0,
        },
    ]
    ordered = sort_opportunity_rows(rows)
    assert [r["disease"] for r in ordered] == ["Z", "Y", "X"]


def test_primary_viz_gaps_empty_focus_and_no_combo_fallback(monkeypatch):
    assert primary_viz_gaps(None) == []
    assert primary_viz_gaps("") == []

    called = {"combo": 0, "transfer": 0, "transfer_kwargs": None}

    def fake_transfer(**kwargs):
        called["transfer"] += 1
        called["transfer_kwargs"] = kwargs
        return []

    def fake_combo(**kwargs):
        called["combo"] += 1
        return {"gaps": [{"method": "x", "disease": "y", "gap": "unexplored", "paper_cnt": 0}]}

    monkeypatch.setattr(
        "analysis.weekly_hotspot.compute_emerging_gap_opportunities",
        fake_transfer,
    )
    # If implementation imports combo at module level, also patch that path to prove unused:
    monkeypatch.setattr(
        "analysis.gap_tools.tool_method_disease_combo_gap",
        fake_combo,
        raising=False,
    )
    out = primary_viz_gaps(
        "nasopharyngeal carcinoma",
        limit=37,
        window_days=21,
    )
    assert out == []
    assert called["transfer"] == 1
    assert called["transfer_kwargs"] == {
        "focus": "nasopharyngeal carcinoma",
        "limit": 37,
        "window_days": 21,
        "min_recent": None,
    }
    assert called["combo"] == 0


def test_primary_viz_gaps_forwards_min_recent(monkeypatch):
    called = {}

    def fake_transfer(**kwargs):
        called.update(kwargs)
        return [{"method": "m", "disease": "d"}]

    monkeypatch.setattr(
        "analysis.weekly_hotspot.compute_emerging_gap_opportunities",
        fake_transfer,
    )
    out = primary_viz_gaps(
        "肠癌",
        limit=12,
        window_days=60,
        min_recent=1,
    )
    assert out == [{"method": "m", "disease": "d"}]
    assert called == {
        "focus": "肠癌",
        "limit": 12,
        "window_days": 60,
        "min_recent": 1,
    }


def test_primary_viz_gaps_uses_injected_list():
    rows = [{"method": "a", "disease": "b", "literature_gap": "minimal", "literature_paper_cnt": 1}]
    assert primary_viz_gaps("focus", opportunities=rows) is rows
