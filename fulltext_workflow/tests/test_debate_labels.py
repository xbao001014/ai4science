"""Tests for gap-report display helpers (role labels + markdown fence unwrap)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from debate_labels import humanize_debate_report, unwrap_outer_markdown_fence


def test_unwrap_markdown_fence_for_ui_preview():
    raw = (
        "```markdown\n"
        "# Pathomics Research Gap Report\n\n"
        "## Research gap analysis\n\n"
        "### Research gap 1: Example direction\n"
        "**Research question**: Does X help?\n"
        "```"
    )
    out = unwrap_outer_markdown_fence(raw)
    assert not out.strip().startswith("```")
    assert out.startswith("# Pathomics Research Gap Report")
    assert "### Research gap 1: Example direction" in out


def test_unwrap_bare_fence_and_md_alias():
    assert unwrap_outer_markdown_fence("```\n## Title\n```") == "## Title"
    assert unwrap_outer_markdown_fence("```md\n## Title\n```") == "## Title"


def test_unwrap_leaves_plain_markdown_and_json_fence():
    plain = "## Research gap analysis\n\n### Research gap 1: A"
    assert unwrap_outer_markdown_fence(plain) == plain
    json_block = '```json\n{"accept": true}\n```'
    assert unwrap_outer_markdown_fence(json_block) == json_block


def test_humanize_debate_report_unwraps_fence_then_replaces_roles():
    raw = (
        "```markdown\n"
        "## Review process summary\n"
        "Opportunity Scout proposed; Evidence Reviewer verified.\n"
        "```"
    )
    out = humanize_debate_report(raw)
    assert not out.strip().startswith("```")
    assert "机会侦察" in out
    assert "证据审阅" in out
    assert "Opportunity Scout" not in out
