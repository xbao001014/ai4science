from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _paper(pmid: str, title: str, abstract: str, year: int) -> dict:
    return {
        "pmid": pmid,
        "doi": "",
        "pmc_id": None,
        "title": title,
        "abstract": abstract,
        "pub_date": f"{year}-01-01",
        "year": year,
        "date_precision": "day",
        "journal_name": "Eval Journal",
        "journal_abbr": "EJ",
        "issn": None,
        "pub_types": [],
        "mesh_terms": [],
        "keywords": [],
        "source_queries": ["p1-eval"],
        "full_text_status": "available",
    }


def test_section_audit_exposes_truncation(monkeypatch):
    import config
    from extractor import section_extractor as se

    monkeypatch.setattr(config, "EXTRACT_MAX_SECTION_CHARS", 24)
    monkeypatch.setattr(se, "llm_call_structured", lambda *_: {"triples": []})
    audit = {}
    text = "We use CLAM for breast cancer classification."
    se._extract_from_text(
        "Study", "methods", "Methods", text,
        study_type="ai_algorithm", audit=audit,
    )
    assert audit["source_chars"] == len(text)
    assert audit["sent_chars"] == 24
    assert audit["truncated"] is True


def test_fulltext_pipeline_persists_section_audit(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db, insert_sections, upsert_paper
    from extractor import section_extractor as se

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "p1.sqlite"))
    monkeypatch.setattr(config, "EXTRACT_SECTION_WORKERS", 1)
    init_db()
    paper_id = upsert_paper(_paper("10001", "Breast study", "Abstract.", 2023))
    insert_sections(paper_id, [
        {"section_type": "methods", "title": "Methods", "content": "We use CLAM.", "order_idx": 0},
        {"section_type": "results", "title": "Results", "content": "CLAM achieved AUC 0.91.", "order_idx": 1},
    ])

    def fake_extract(title, section_type, section_title, content, **kwargs):
        audit = kwargs.get("audit")
        if audit is not None:
            audit.update(
                outcome="retained", source_chars=len(content), sent_chars=len(content),
                truncated=False, parsed=1, postprocessed=1, retained=1,
                empty_recheck=False, recall_check_reason=None, rejected=[],
            )
        return []

    monkeypatch.setattr(se, "_extract_from_text", fake_extract)
    paper = {"abstract": "Abstract."}
    se._extract_fulltext(paper, paper_id, "10001", "Breast study", "fulltext", study_type="ai_algorithm")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT section_type, outcome, source_chars, sent_chars FROM extraction_audits ORDER BY id"
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("methods", "retained", 12, 12),
        ("results", "retained", 23, 23),
    ]


def test_reconcile_filters_unlocated_quotes_and_labels_sections():
    from extractor.fulltext_reconcile import ground_reconcile_payload

    payload = {
        "surveyed_methods": [
            {"name": "CLAM", "quote": "We review CLAM."},
            {"name": "InventedNet", "quote": "This sentence is absent."},
        ],
        "covered_diseases": [],
        "limitations": [],
        "bindings": [],
        "recommendations": [],
        "datasets": [],
    }
    sections = [{"section_type": "introduction", "content": "We review CLAM."}]
    grounded, audit = ground_reconcile_payload(payload, sections)
    assert [r["name"] for r in grounded["surveyed_methods"]] == ["CLAM"]
    assert grounded["surveyed_methods"][0]["evidence_section"] == "introduction"
    assert audit["checked"] == 2 and audit["rejected"] == 1


def test_literature_search_is_cutoff_focus_and_source_record_safe(tmp_path, monkeypatch):
    import config
    from db.schema import init_db, insert_relation, upsert_entity, upsert_paper
    from analysis.gap_tools import tool_literature_evidence_search

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "retrieval.sqlite"))
    init_db()
    rows = [
        ("11001", "Breast cancer segmentation validation", "breast cancer pathology", 2022,
         "External validation for breast segmentation remains limited."),
        ("11002", "Breast cancer segmentation multicenter", "breast cancer pathology", 2027,
         "We completed multicenter breast segmentation validation."),
        ("11003", "Lung segmentation validation", "lung pathology", 2021,
         "External validation for lung segmentation remains limited."),
    ]
    for pmid, title, abstract, year, quote in rows:
        paper_id = upsert_paper(_paper(pmid, title, abstract, year))
        lim_id = upsert_entity(f"limitation-{pmid}", "Limitation")
        insert_relation(
            "Paper", paper_id, "REPORTS_LIMITATION", "Limitation", lim_id,
            source_pmid=pmid, evidence_section="discussion", evidence_quote=quote,
            extraction_granularity="fulltext",
        )
    result = tool_literature_evidence_search(
        query="breast segmentation external validation",
        focus="breast", top_k=5, cutoff_year=2024,
    )
    assert [r["source_pmid"] for r in result["source_records"]] == ["11001"]
    assert result["retrieval_metadata"]["cutoff_year"] == 2024
    assert result["retrieval_metadata"]["absence_scope"] == "in_corpus_only"
    assert all(r["evidence_quote"] and r["source_pmid"] for r in result["source_records"])


def test_moderator_handoff_blocks_repromotion_and_missing_ids():
    from analysis.research_quality import enforce_moderator_handoff, validate_moderator_handoff

    review = {
        "verified_gaps": [{"candidate_id": "G01"}],
        "false_gaps": [{"candidate_id": "G02"}],
        "weak_evidence_gaps": [{"candidate_id": "G03"}],
    }
    report = """## Research gap analysis
### Research gap 1: Supported
**Candidate ID**: G01
### Research gap 2: Re-promoted
**Candidate ID**: G02
### Research gap 3: Missing identity
No candidate identifier here.
"""
    audit = validate_moderator_handoff(report, review)
    assert audit["status"] == "needs_verification"
    assert "promoted_unverified_candidate:G02" in audit["issues"]
    assert "missing_candidate_id:Research gap 3" in audit["issues"]
    filtered, enforcement = enforce_moderator_handoff(report, review)
    assert "Candidate ID**: G01" in filtered
    assert "Candidate ID**: G02" not in filtered
    assert "Missing identity" not in filtered
    assert enforcement["removed_candidate_ids"] == ["G02"]
    assert validate_moderator_handoff(filtered, review)["status"] == "handoff_checked"
