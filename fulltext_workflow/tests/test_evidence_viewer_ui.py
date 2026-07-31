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


def test_provenance_row_key_stable_and_distinct():
    from gap_ui import provenance_row_key

    a = provenance_row_key("evidence", "123", "title", "quote one")
    b = provenance_row_key("evidence", "123", "title", "quote two")
    c = provenance_row_key("paper", "123", "Same Title")
    assert a != b
    assert a.startswith("evidence_123_")
    assert c.startswith("paper_123_")
    assert provenance_row_key("evidence", "123", "title", "quote one") == a


def test_partition_provenance_rows_caps_at_30():
    from gap_ui import PROVENANCE_LIST_LIMIT, partition_provenance_rows

    rows = [{"PMID": str(i)} for i in range(35)]
    head, tail = partition_provenance_rows(rows)
    assert len(head) == PROVENANCE_LIST_LIMIT == 30
    assert len(tail) == 5
    assert head[0]["PMID"] == "0"
    assert tail[0]["PMID"] == "30"


def test_extract_evidence_keeps_full_title():
    from gap_ui import extract_evidence

    long_title = "T" * 120
    events = [{
        "type": "tool_result",
        "name": "author_stated_gaps",
        "result": {
            "data": [{
                "source_pmid": "1",
                "title": long_title,
                "evidence_section": "discussion",
                "evidence_quote": "q",
            }]
        },
    }]
    rows = extract_evidence(events)
    assert rows[0]["标题/实体"] == long_title


def test_viewer_load_warning_includes_error_code(monkeypatch):
    import gap_ui

    warnings = []

    class FakeStreamlit:
        session_state = {
            "evidence_viewer": {"pmid": "missing", "focus_quote": None}
        }

        @staticmethod
        def subheader(*_args, **_kwargs):
            pass

        @staticmethod
        def info(*_args, **_kwargs):
            pass

        @staticmethod
        def divider():
            pass

        @staticmethod
        def button(*_args, **_kwargs):
            return False

        @staticmethod
        def warning(message):
            warnings.append(message)

    def raise_load_error(_pmid):
        raise gap_ui.ViewerLoadError("not_found", "论文不在语料中")

    monkeypatch.setattr(gap_ui, "st", FakeStreamlit)
    monkeypatch.setattr(gap_ui, "extract_evidence", lambda _events: [])
    monkeypatch.setattr(
        gap_ui,
        "resolve_evidence_literature_papers",
        lambda _events, _focus, limit: ([], "no_match"),
    )
    monkeypatch.setattr(gap_ui, "load_paper_for_viewer", raise_load_error)

    gap_ui.render_evidence_literature_section([], None)

    assert warnings == ["[not_found] 论文不在语料中"]
