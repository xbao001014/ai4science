"""Hotspot brief must not invent transfer candidates when opportunities are empty."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.hotspot_brief import (  # noqa: E402
    _build_brief_context,
    format_transfer_candidates_section,
    generate_hotspot_brief,
)


def test_brief_context_omits_hot_combos():
    payload = {
        "week_id": "2026-W35",
        "emerging_methods": [{"name": "foo", "recent_cnt": 1}],
        "heating_diseases": [],
        "hot_combos": [{"method": "bar", "disease": "baz"}],
        "emerging_gap_opportunities": [],
    }
    ctx = json.loads(_build_brief_context(payload))
    assert "top_combos" not in ctx
    assert ctx["transfer_candidates_available"] is False


def test_empty_transfer_section_is_deterministic():
    text = format_transfer_candidates_section([])
    assert "无满足证据门槛" in text
    assert "method×disease" in text


def test_nonempty_transfer_section_uses_opportunities_only():
    text = format_transfer_candidates_section(
        [
            {
                "method": "LadderMIL",
                "disease": "breast cancer",
                "bridge_task": "classification",
                "bridge_mode": "same_paper",
                "opportunity_score": 1.23,
            }
        ]
    )
    assert "LadderMIL" in text
    assert "classification" in text


def test_generate_hotspot_brief_empty_opportunities_appends_deterministic(monkeypatch):
    class _Msg:
        content = "**本周概览**\n\n测试概览。\n\n**风险提示**\n\n注意样本量。"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    assert "Do NOT write a 可迁移候选" in kwargs["messages"][0]["content"]
                    return _Resp()

    monkeypatch.setattr("analysis.hotspot_brief._client", lambda: _Client())
    payload = {
        "week_id": "2026-W35",
        "emerging_methods": [],
        "heating_diseases": [],
        "emerging_gap_opportunities": [],
        "week_over_week": {"has_baseline": False},
    }
    text = generate_hotspot_brief(payload)
    assert "无满足证据门槛" in text
    assert "bar" not in text.lower() or "method×disease" in text
