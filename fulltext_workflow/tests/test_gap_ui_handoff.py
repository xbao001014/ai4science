"""Tests for Gap UI P2 helpers (debate summary, opportunity handoff)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.gap_ui_handoff import (
    DATA_FEAS_VIEW_KEY,
    DATA_VIEW_ADVANCED,
    DATA_VIEW_GAP_CHECK,
    DATA_VIEW_V01,
    apply_opportunity_proposal_handoff,
    apply_opportunity_v01_handoff,
    debate_summary_metrics,
    opportunity_proposal_text,
)


def test_debate_summary_metrics_includes_funnel_and_confidence():
    events = [
        {"type": "optimist_proposal", "content": "### Gap 1: A\n### Gap 2: B\n### Gap 3: C"},
        {
            "type": "skeptic_review",
            "content": (
                '```json\n{"verified_gaps":[{"title":"A"}],'
                '"false_gaps":[{"title":"X"}],'
                '"weak_evidence_gaps":[{"title":"W"}]}\n```'
            ),
        },
    ]
    report = "### Research Gap 1: A"
    m = debate_summary_metrics(events, report, debate_confidence=7.5)
    assert m["scout_candidates"] == 3
    assert m["verified"] == 1
    assert m["false_gaps"] == 1
    assert m["weak_evidence"] == 1
    assert m["final_gaps"] == 1
    assert m["confidence"] == 7.5
    assert m["tool_steps"] == 0


def test_debate_summary_counts_tool_steps():
    events = [
        {"type": "tool_call", "name": "a", "call_id": "1"},
        {"type": "tool_result", "name": "a", "call_id": "1", "result": {}},
        {"type": "tool_call", "name": "b", "call_id": "2"},
    ]
    m = debate_summary_metrics(events, "", debate_confidence=0.0)
    assert m["tool_steps"] == 2


def test_opportunity_proposal_text_includes_method_disease():
    text = opportunity_proposal_text(
        {
            "method": "foundation model",
            "disease": "CRC",
            "bridge_task": "survival prediction",
            "gap": "unexplored",
        }
    )
    assert "foundation model" in text
    assert "CRC" in text
    assert "survival prediction" in text


def test_apply_opportunity_proposal_handoff_sets_manual_gap():
    state: dict = {}
    apply_opportunity_proposal_handoff(
        state,
        {"method": "FM", "disease": "GC", "bridge_task": "grading", "gap": "minimal"},
    )
    assert state["gap_source"] == "手动输入"
    assert "FM" in state["gap_manual"]
    assert "GC" in state["gap_manual"]


def test_apply_opportunity_v01_handoff_sets_view_and_disease():
    state: dict = {}
    apply_opportunity_v01_handoff(
        state,
        {"disease_id": "CRC-ADC", "disease": "colorectal adenocarcinoma"},
    )
    assert state[DATA_FEAS_VIEW_KEY] == DATA_VIEW_V01
    assert state["v01_disease"] == "CRC-ADC"


def test_data_view_defaults():
    assert DATA_VIEW_GAP_CHECK == "从空白快速核查"
    assert DATA_VIEW_V01 == "V-01 可行性"
    assert DATA_VIEW_ADVANCED == "高级 API"
