"""Tests for fulltext ↔ extraction demo export payload."""
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


def _seed_paper(pmid: str, study_type: str = "ai_algorithm") -> int:
    pid = upsert_paper(
        {
            "pmid": pmid,
            "title": f"Title for {pmid}",
            "year": 2025,
            "journal_name": "Demo Journal",
        }
    )
    mark_fulltext_status(pid, "available")
    mark_extraction_done(pid, study_type)
    insert_sections(
        pid,
        [
            {
                "section_type": "abstract",
                "title": "",
                "content": "We apply ResNet on Camelyon16.",
                "order_idx": 0,
            },
            {
                "section_type": "methods",
                "title": "Methods",
                "content": "We apply ResNet on Camelyon16 with AUC 0.91.",
                "order_idx": 1,
            },
        ],
    )
    mid = upsert_entity("resnet", "Method")
    did = upsert_entity("camelyon16", "Dataset")
    insert_relation(
        "Paper",
        pid,
        "APPLIES_METHOD",
        "Method",
        mid,
        source_pmid=pmid,
        evidence_section="methods",
        evidence_quote="We apply ResNet",
        extraction_granularity="fulltext",
        confidence=0.9,
    )
    insert_relation(
        "Paper",
        pid,
        "USES_DATASET",
        "Dataset",
        did,
        source_pmid=pmid,
        evidence_section="methods",
        evidence_quote="Camelyon16 with AUC",
        extraction_granularity="fulltext",
    )
    lim = upsert_entity("small cohort", "Limitation")
    insert_relation(
        "Paper",
        pid,
        "REPORTS_LIMITATION",
        "Limitation",
        lim,
        source_pmid=pmid,
        evidence_section="discussion",
        evidence_quote="small cohort",
        status="superseded",
    )
    return pid


def test_parse_pmid_list_skips_comments_and_blanks():
    from viz.extraction_demo import parse_pmid_list

    text = "# trio\n42351909\n\n42200024  # review\n42306089\n"
    assert parse_pmid_list(text) == ["42351909", "42200024", "42306089"]


def test_match_evidence_quote_whitespace_and_case():
    from viz.extraction_demo import match_evidence_quote

    text = "We apply ResNet on Camelyon16."
    assert match_evidence_quote(text, "We apply ResNet") == (0, 15)
    assert match_evidence_quote(text, "we   apply   resnet") is not None
    assert match_evidence_quote(text, "missing quote xyz") is None


def test_load_demo_papers_payload_shape(monkeypatch):
    from viz.extraction_demo import load_demo_papers

    _tmp_db(monkeypatch)
    _seed_paper("900001")
    papers = load_demo_papers(["900001"])
    assert len(papers) == 1
    p = papers[0]
    assert p["pmid"] == "900001"
    assert p["study_type"] == "ai_algorithm"
    assert p["study_type_label_zh"]
    assert len(p["sections"]) == 2
    assert {e["relation"] for e in p["extractions"]} == {
        "APPLIES_METHOD",
        "USES_DATASET",
    }
    method = next(e for e in p["extractions"] if e["relation"] == "APPLIES_METHOD")
    assert method["object_name"] == "resnet"
    assert method["object_type"] == "Method"
    assert method["relation_label_zh"]
    assert method["evidence_quote"] == "We apply ResNet"


def test_load_demo_papers_fail_fast_missing(monkeypatch):
    from viz.extraction_demo import DemoExportError, load_demo_papers

    _tmp_db(monkeypatch)
    with pytest.raises(DemoExportError, match="900999"):
        load_demo_papers(["900999"])


def test_load_demo_papers_fail_fast_no_extractions(monkeypatch):
    from viz.extraction_demo import DemoExportError, load_demo_papers

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "900002", "title": "Empty"})
    mark_fulltext_status(pid, "available")
    mark_extraction_done(pid, "review")
    insert_sections(
        pid,
        [{"section_type": "abstract", "content": "Only abstract.", "order_idx": 0}],
    )
    with pytest.raises(DemoExportError, match="900002"):
        load_demo_papers(["900002"])


def test_load_demo_papers_fail_fast_no_sections(monkeypatch):
    from viz.extraction_demo import DemoExportError, load_demo_papers

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "900003", "title": "No sections"})
    mark_fulltext_status(pid, "available")
    mark_extraction_done(pid, "ai_algorithm")
    with pytest.raises(DemoExportError, match="no document sections"):
        load_demo_papers(["900003"])


def test_load_demo_papers_fail_fast_bad_fulltext_status(monkeypatch):
    from viz.extraction_demo import DemoExportError, load_demo_papers

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "900004", "title": "Pending fulltext"})
    mark_fulltext_status(pid, "pending")
    mark_extraction_done(pid, "ai_algorithm")
    insert_sections(
        pid,
        [{"section_type": "abstract", "content": "Abstract only.", "order_idx": 0}],
    )
    with pytest.raises(DemoExportError, match="full_text_status"):
        load_demo_papers(["900004"])


def test_load_demo_papers_fail_fast_extraction_not_done(monkeypatch):
    from viz.extraction_demo import DemoExportError, load_demo_papers

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "900005", "title": "Not extracted"})
    mark_fulltext_status(pid, "available")
    insert_sections(
        pid,
        [{"section_type": "abstract", "content": "Abstract only.", "order_idx": 0}],
    )
    with pytest.raises(DemoExportError, match="extraction not done"):
        load_demo_papers(["900005"])


def test_load_demo_papers_db_path_restores_config(monkeypatch):
    from viz.extraction_demo import load_demo_papers

    default_path = _tmp_db(monkeypatch)
    alt = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    alt.close()
    alt_path = Path(alt.name)
    monkeypatch.setattr(config, "DB_PATH", alt_path)
    init_db()
    _seed_paper("900010")
    monkeypatch.setattr(config, "DB_PATH", default_path)

    assert config.DB_PATH == default_path
    papers = load_demo_papers(["900010"], db_path=alt_path)
    assert config.DB_PATH == default_path
    assert len(papers) == 1
    assert papers[0]["pmid"] == "900010"


def test_render_html_embeds_papers_and_controls(monkeypatch):
    from viz.extraction_demo import load_demo_papers, render_extraction_demo_html

    _tmp_db(monkeypatch)
    _seed_paper("900001", "ai_algorithm")
    _seed_paper("900003", "review")
    html = render_extraction_demo_html(load_demo_papers(["900001", "900003"]))
    assert "<!DOCTYPE html>" in html
    assert "window.DEMO_PAPERS" in html
    assert "900001" in html and "900003" in html
    assert 'id="fulltext-pane"' in html
    assert 'id="extraction-pane"' in html
    assert "matchEvidenceQuote" in html
    assert "证据未精确匹配" in html
