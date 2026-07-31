"""Tests for single-paper evidence viewer load + focus resolve."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    init_db,
    insert_relation,
    insert_sections,
    mark_extraction_done,
    mark_fulltext_status,
    upsert_entity,
    upsert_paper,
)


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def _seed_full(pmid: str = "1001") -> int:
    pid = upsert_paper(
        {"pmid": pmid, "title": f"Title {pmid}", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(pid, "available")
    mark_extraction_done(pid, "ai_algorithm")
    insert_sections(
        pid,
        [
            {
                "section_type": "methods",
                "title": "Methods",
                "content": "We apply ResNet on Camelyon16 with AUC 0.91.",
                "order_idx": 0,
            }
        ],
    )
    mid = upsert_entity("resnet", "Method")
    did = upsert_entity("camelyon16", "Dataset")
    insert_relation(
        "Paper", pid, "APPLIES_METHOD", "Method", mid,
        source_pmid=pmid, evidence_section="methods",
        evidence_quote="We apply ResNet", extraction_granularity="fulltext",
        confidence=0.9,
    )
    insert_relation(
        "Paper", pid, "USES_DATASET", "Dataset", did,
        source_pmid=pmid, evidence_section="methods",
        evidence_quote="Camelyon16 with AUC", extraction_granularity="fulltext",
        confidence=0.8,
    )
    return pid


def test_load_paper_for_viewer_ok(monkeypatch):
    from viz.evidence_viewer import load_paper_for_viewer

    _tmp_db(monkeypatch)
    _seed_full("1001")
    paper = load_paper_for_viewer("1001")
    assert paper["pmid"] == "1001"
    assert len(paper["sections"]) == 1
    assert len(paper["extractions"]) == 2
    assert paper["extractions"][0]["object_type"] == "Method"


def test_load_paper_not_found(monkeypatch):
    from viz.evidence_viewer import ViewerLoadError, load_paper_for_viewer

    _tmp_db(monkeypatch)
    with pytest.raises(ViewerLoadError) as ei:
        load_paper_for_viewer("missing")
    assert ei.value.code == "not_found"
    assert "语料" in ei.value.message_zh or "不在" in ei.value.message_zh


def test_load_paper_no_fulltext(monkeypatch):
    from viz.evidence_viewer import ViewerLoadError, load_paper_for_viewer

    _tmp_db(monkeypatch)
    upsert_paper({"pmid": "1002", "title": "T", "year": 2025, "journal_name": "J"})
    with pytest.raises(ViewerLoadError) as ei:
        load_paper_for_viewer("1002")
    assert ei.value.code == "no_fulltext"


def test_load_paper_no_sections(monkeypatch):
    from viz.evidence_viewer import ViewerLoadError, load_paper_for_viewer

    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {"pmid": "1004", "title": "T", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(pid, "available")

    with pytest.raises(ViewerLoadError) as ei:
        load_paper_for_viewer("1004")

    assert ei.value.code == "no_sections"


def test_load_paper_allows_empty_extractions(monkeypatch):
    from viz.evidence_viewer import load_paper_for_viewer

    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {"pmid": "1003", "title": "T", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(pid, "available")
    insert_sections(
        pid,
        [{"section_type": "abstract", "title": "", "content": "Hello world.", "order_idx": 0}],
    )
    paper = load_paper_for_viewer("1003")
    assert paper["extractions"] == []
    assert paper["sections"][0]["content"] == "Hello world."


def test_resolve_focus_extraction_exact_and_none():
    from viz.evidence_viewer import resolve_focus_extraction

    paper = {
        "extractions": [
            {"evidence_quote": "We apply ResNet"},
            {"evidence_quote": "Camelyon16 with AUC"},
        ]
    }
    assert resolve_focus_extraction(paper, "Camelyon16 with AUC") == 1
    assert resolve_focus_extraction(paper, "We apply ResNet") == 0
    assert resolve_focus_extraction(paper, None) is None
    assert resolve_focus_extraction(paper, "totally unrelated xyz") is None


def test_resolve_focus_extraction_ignores_short_non_exact_overlap():
    from viz.evidence_viewer import resolve_focus_extraction

    paper = {
        "extractions": [
            {"evidence_quote": "AUC was measured"},
            {"evidence_quote": "short"},
        ]
    }

    assert resolve_focus_extraction(paper, "AUC") is None
    assert resolve_focus_extraction(paper, "short") == 1


def test_viewer_reuses_demo_sort_and_status_helpers():
    from viz import evidence_viewer, extraction_demo

    assert (
        evidence_viewer._object_type_sort_key
        is extraction_demo._object_type_sort_key
    )
    assert (
        evidence_viewer._VALID_FULLTEXT_STATUSES
        is extraction_demo._VALID_FULLTEXT_STATUSES
    )


def test_render_html_single_paper_no_tabs(monkeypatch):
    from viz.evidence_viewer import load_paper_for_viewer, render_evidence_viewer_html

    _tmp_db(monkeypatch)
    _seed_full("2001")
    paper = load_paper_for_viewer("2001")
    html = render_evidence_viewer_html(paper, initial_extraction_index=0)
    assert "paper-tabs" not in html
    assert "window.VIEWER_PAPER = " in html
    assert "We apply ResNet" in html
    assert "window.INITIAL_EXTRACTION_INDEX = 0;" in html
    assert "window.UNMATCHED_FOCUS = false;" in html
    assert "window.FOCUS_QUOTE = null;" in html
    assert "__PAPER_JSON__" not in html
    assert "__INIT_IDX__" not in html
    assert "__FOCUS_QUOTE__" not in html
    assert "__UNMATCHED__" not in html
    assert "highlightEvidence" in html


def test_render_html_empty_extractions_and_focus_quote(monkeypatch):
    from viz.evidence_viewer import load_paper_for_viewer, render_evidence_viewer_html

    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {"pmid": "2002", "title": "T", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(pid, "available")
    insert_sections(
        pid,
        [{
            "section_type": "abstract",
            "title": "",
            "content": "UniqueFocusQuoteXYZ appears here.",
            "order_idx": 0,
        }],
    )
    paper = load_paper_for_viewer("2002")
    html = render_evidence_viewer_html(
        paper, focus_quote="UniqueFocusQuoteXYZ", unmatched_focus=True
    )
    assert "暂无抽取" in html or "没有可展示的抽取" in html
    assert 'window.FOCUS_QUOTE = "UniqueFocusQuoteXYZ";' in html
    assert "window.UNMATCHED_FOCUS = true;" in html
    assert "window.INITIAL_EXTRACTION_INDEX = null;" in html
    assert "__PAPER_JSON__" not in html
    assert "__INIT_IDX__" not in html
    assert "__FOCUS_QUOTE__" not in html
    assert "__UNMATCHED__" not in html
    assert "证据未精确匹配到抽取卡" in html


def test_render_html_substitutes_paper_payload_last():
    from viz.evidence_viewer import render_evidence_viewer_html

    paper = {
        "pmid": "placeholder-collision",
        "title": "__INIT_IDX__ __FOCUS_QUOTE__ __UNMATCHED__",
        "sections": [],
        "extractions": [],
    }

    html = render_evidence_viewer_html(
        paper,
        initial_extraction_index=7,
        focus_quote="focus",
        unmatched_focus=True,
    )

    assert '"title": "__INIT_IDX__ __FOCUS_QUOTE__ __UNMATCHED__"' in html
    assert "window.INITIAL_EXTRACTION_INDEX = 7;" in html
    assert 'window.FOCUS_QUOTE = "focus";' in html
    assert "window.UNMATCHED_FOCUS = true;" in html
