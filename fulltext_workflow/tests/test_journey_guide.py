"""Tests for Gap UI recommended journey + post-debate tab landing."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.journey_guide import (
    POST_DEBATE_TAB_SLUG,
    format_journey_line,
    journey_status,
    next_step_hint,
)


def test_post_debate_lands_on_gap_report():
    assert POST_DEBATE_TAB_SLUG == "gap-report"


def test_journey_before_focus_points_at_focus_or_browse():
    status = journey_status(has_focus=False, has_report=False, has_proposal=False)
    assert status["current_slug"] in {"weekly-hotspot", "focus"}
    assert status["current_label"] in {"浏览热点", "设焦点"}
    assert "焦点" in next_step_hint(status)


def test_journey_with_focus_no_report_points_at_debate():
    status = journey_status(has_focus=True, has_report=False, has_proposal=False)
    assert status["current_slug"] == "debate-process"
    assert "辩论" in next_step_hint(status)


def test_journey_after_report_points_at_verify_or_proposal():
    status = journey_status(has_focus=True, has_report=True, has_proposal=False)
    assert status["current_slug"] == "gap-report"
    hint = next_step_hint(status)
    assert "方信" in hint or "提案" in hint


def test_journey_after_proposal_marks_complete():
    status = journey_status(has_focus=True, has_report=True, has_proposal=True)
    assert status["complete"] is True
    assert "完成" in next_step_hint(status) or "下载" in next_step_hint(status)


def test_format_journey_line_includes_all_steps():
    line = format_journey_line(
        journey_status(has_focus=True, has_report=False, has_proposal=False)
    )
    for label in ("浏览热点", "设焦点", "运行辩论", "看报告", "查看方信数据", "生成提案"):
        assert label in line
    assert "运行辩论" in line
