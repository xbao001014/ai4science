"""Pure helpers for evidence-tab viewer selection (no Streamlit)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_evidence_viewer_selection_payload():
    from gap_ui import make_evidence_viewer_selection

    assert make_evidence_viewer_selection("123", "quote A") == {
        "pmid": "123",
        "focus_quote": "quote A",
    }
    assert make_evidence_viewer_selection("123", None) == {
        "pmid": "123",
        "focus_quote": None,
    }
    assert make_evidence_viewer_selection("  ", "x") is None
    assert make_evidence_viewer_selection("", None) is None


def test_extract_evidence_keeps_longer_quote():
    from gap_ui import extract_evidence

    events = [{
        "type": "tool_result",
        "name": "author_stated_gaps",
        "result": {
            "data": [{
                "source_pmid": "999",
                "title": "Gap entity",
                "evidence_section": "discussion",
                "evidence_quote": "A" * 200,
            }]
        },
    }]
    rows = extract_evidence(events)
    assert len(rows) == 1
    assert len(rows[0]["摘录"]) == 200  # was 120; now allow up to 240 or full if shorter
