"""P0 quality contracts for support status, empty routing and evidence storage."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "evals")]

from extractor.evidence_support import assess_evidence_support
from extractor.triple_models import Triple
from p0_cases import EVIDENCE_SUPPORT


def _triple(case):
    return Triple.model_validate(case["triple"])


def test_support_fixture_matches_advisory_classifier():
    for case in EVIDENCE_SUPPORT:
        status, _ = assess_evidence_support(_triple(case), case["quote"])
        assert status == case["expected"], case["id"]


def test_grounding_annotates_but_does_not_drop_non_supporting_quote():
    from extractor.evidence_grounding import ground_triples

    case = next(row for row in EVIDENCE_SUPPORT if row["expected"] == "mentioned_only")
    kept, rejected = ground_triples([_triple(case)], case["quote"])
    assert not rejected and len(kept) == 1
    assert kept[0].evidence_status == "located"
    assert kept[0].evidence_support_status == "mentioned_only"


def test_review_empty_gets_one_p0_recheck(monkeypatch):
    from extractor import section_extractor as se

    case = next(row for row in EVIDENCE_SUPPORT if row["id"] == "S03")
    responses = iter([{"triples": []}, {"triples": [case["triple"]]}])
    calls = []

    def fake(*args):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(se, "llm_call_structured", fake)
    audit = {}
    got = se._extract_from_text(
        "Review",
        "methods",
        "Methods",
        case["quote"],
        study_type="review",
        audit=audit,
    )
    assert len(calls) == 2 and len(got) == 1
    assert audit["recall_check_reason"] == "explicit_review_scope"
    assert audit["outcome"] == "retained"


def test_phase2_policy_reproduces_review_empty_gap(monkeypatch):
    from extractor import section_extractor as se

    calls = []
    monkeypatch.setattr(se, "llm_call_structured", lambda *args: calls.append(args) or {"triples": []})
    audit = {}
    got = se._extract_from_text(
        "Review",
        "methods",
        "Methods",
        "This review surveys CLAM and TransMIL.",
        study_type="review",
        audit=audit,
        recall_policy="phase2",
    )
    assert not got and len(calls) == 1
    assert audit["outcome"] == "model_empty"


def test_unresolved_empty_has_explicit_reason(monkeypatch):
    from extractor import section_extractor as se

    monkeypatch.setattr(se, "llm_call_structured", lambda *args: {})
    audit = {}
    assert not se._extract_from_text(
        "Study", "methods", "Methods", "We use CLAM.", study_type="ai_algorithm", audit=audit
    )
    assert audit["outcome"] == "unresolved_empty"
    assert audit["empty_reason"] == "transport_parse_or_empty_object"


def test_relation_evidence_persists_offsets_and_support(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db, insert_relation, insert_relation_evidence, upsert_entity

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "quality.sqlite"))
    init_db()
    obj_id = upsert_entity("clam", "Method")
    relation_id = insert_relation(
        "Paper", 1, "APPLIES_METHOD", "Method", obj_id, source_pmid="P0-TEST"
    )
    evidence_id = insert_relation_evidence(
        relation_id,
        source_pmid="P0-TEST",
        evidence_section="methods",
        evidence_quote="We use CLAM.",
        evidence_start=0,
        evidence_end=12,
        evidence_status="located",
        support_status="supported",
        support_reason="object_and_relation_cue",
        extraction_granularity="fulltext",
    )
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM relation_evidence WHERE id=?", (evidence_id,)).fetchone()
    assert dict(row)["evidence_start"] == 0
    assert dict(row)["support_status"] == "supported"


def test_pending_expert_package_cannot_be_sealed(tmp_path):
    from expert_holdout import init_package, seal_package

    root = tmp_path / "holdout"
    status = init_package(root, papers_per_type=1, gaps_per_label=1)
    assert status["paper_rows"] == 8 and status["gap_rows"] == 3
    assert not status["ready_to_seal"]
    try:
        seal_package(root, tmp_path / "seal.json")
    except ValueError as exc:
        assert "not sealable" in str(exc)
    else:
        raise AssertionError("pending labels must never be sealed as gold")
