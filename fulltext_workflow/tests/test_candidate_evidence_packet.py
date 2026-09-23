from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.candidate_evidence_packet import (  # noqa: E402
    SCHEMA_VERSION,
    build_candidate_evidence_packets,
    coerce_candidate_evidence_packet,
    find_candidate_evidence_packet,
    validate_candidate_evidence_packet,
)
from db.schema import get_conn, init_db  # noqa: E402
from pipeline_utils import parse_gap_sections  # noqa: E402


def _seed_source(tmp_path: Path) -> None:
    config.DB_PATH = str(tmp_path / "packet.db")
    init_db()
    with get_conn() as conn:
        paper_id = conn.execute(
            """INSERT INTO papers (pmid, title, abstract, year, full_text_status)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "1001",
                "Colorectal cancer external validation",
                "The abstract does not contain the target sentence.",
                2024,
                "available",
            ),
        ).lastrowid
        conn.execute(
            """INSERT INTO document_sections
               (paper_id, section_type, title, content, order_idx)
               VALUES (?, ?, ?, ?, ?)""",
            (
                paper_id,
                "discussion",
                "Limitations",
                "Prior work is encouraging. External multi-center validation remains unresolved. "
                "Future studies should address scanner shift and calibration.",
                4,
            ),
        )


def test_builds_candidate_scoped_packet_with_source_context(tmp_path):
    _seed_source(tmp_path)
    report = (
        "# Final\n\n"
        "### Research Gap 1: Multi-center CRC validation\n"
        "**Candidate ID**: G01\n"
        "**Research question**: Can calibration survive scanner shift?\n\n"
        "### Research Gap 2: CRC weak labels\n"
        "**Candidate ID**: G02\n"
    )
    quote = "External multi-center validation remains unresolved."
    ledger = {
        "1": {
            "skeptic": {
                "literature_evidence_search": {
                    "result": {
                        "_evidence_records": [
                            {
                                "evidence_id": "EV-CRC",
                                "text": quote,
                                "source_pmid": "1001",
                                "year": 2024,
                                "kind": "source",
                            },
                            {
                                "evidence_id": "EV-OTHER",
                                "text": "An unrelated candidate needs more work.",
                                "source_pmid": "2002",
                                "year": 2023,
                                "kind": "source",
                            },
                        ]
                    }
                }
            },
            "optimist": {
                "corpus_focus_coverage": {
                    "result": {
                        "global": {"papers": 200},
                        "focus_subset": {"papers": 44, "extracted": 39},
                        "warnings": ["bounded local corpus"],
                    }
                }
            },
        }
    }
    reviewer = {
        "overall_confidence": 8.4,
        "verified_gaps": [
            {
                "candidate_id": "G01",
                "title": "Multi-center CRC validation",
                "rationale": "Directly stated unresolved validation need.",
                "evidence_refs": [
                    {
                        "evidence_id": "EV-CRC",
                        "quote": quote,
                        "stance": "supports_gap",
                    }
                ],
            }
        ],
        "weak_evidence_gaps": [
            {"candidate_id": "G02", "title": "CRC weak labels", "evidence_refs": []}
        ],
    }

    packets = build_candidate_evidence_packets(
        report_text=report,
        reviewer=reviewer,
        evidence_source=ledger,
        focus="colorectal cancer",
        debate_session_id="debate-1",
        validation_status="evidence_checked",
    )

    first = packets["G01"]
    assert first["schema_version"] == SCHEMA_VERSION
    assert first["candidate"]["section_md"].startswith("### Research Gap 1")
    assert first["candidate"]["classification"] == "verified"
    assert first["handoff"]["support_pmids"] == ["1001"]
    assert first["corpus"]["focus_papers"] == 44
    evidence = first["evidence"]["supports"][0]
    assert evidence["context_located"] is True
    assert "Prior work is encouraging" in evidence["context_before"]
    assert "scanner shift" in evidence["context_after"]
    assert "EV-OTHER" not in json.dumps(first, ensure_ascii=False)

    second = find_candidate_evidence_packet(
        packets,
        title="CRC weak labels",
        section_md="### Research Gap 2: CRC weak labels\n**Candidate ID**: G02",
    )
    assert second["candidate"]["classification"] == "needs_evidence"
    assert second["handoff"]["support_pmids"] == []
    assert "candidate_has_no_reviewer_evidence_refs" in second["warnings"]
    assert validate_candidate_evidence_packet(first) == []


def test_legacy_gap_data_is_adapted_to_versioned_contract():
    packet = coerce_candidate_evidence_packet(
        "CRC proposal",
        {
            "support_pmids": ["1", "1", "2"],
            "papers": [{"pmid": "1"}],
            "feasibility_assessment": {"feasibility_score": 0.8},
            "public_dataset_assessment": {"recommended_public": []},
        },
    )
    assert validate_candidate_evidence_packet(packet) == []
    assert packet["schema_version"] == SCHEMA_VERSION
    assert packet["handoff"]["support_pmids"] == ["1", "2"]
    assert packet["handoff"]["linked_papers"] == [{"pmid": "1"}]
    assert packet["warnings"] == ["legacy_gap_data_adapted_to_v1"]


def test_legacy_input_is_adapted_without_losing_proposal_fields():
    packet = coerce_candidate_evidence_packet(
        "CRC proposal",
        {
            "support_pmids": ["1", "1", "2"],
            "papers": [{"pmid": "1"}],
            "feasibility_assessment": {"feasibility_score": 0.8},
            "public_dataset_assessment": {"recommended_public": []},
            "disease_id": "CRC-ID",
        },
    )
    assert packet["schema_version"] == SCHEMA_VERSION
    assert packet["handoff"]["support_pmids"] == ["1", "2"]
    assert packet["handoff"]["linked_papers"] == [{"pmid": "1"}]
    assert packet["handoff"]["feasibility_assessment"]["feasibility_score"] == 0.8
    assert packet["handoff"]["disease_id"] == "CRC-ID"
    assert "legacy_gap_data_adapted_to_v1" in packet["warnings"]


def test_packet_lookup_uses_candidate_id_before_title():
    packet = coerce_candidate_evidence_packet(
        "Old title", {"candidate_id": "G01", "section_md": "old section"}
    )
    found = find_candidate_evidence_packet(
        {"G01": packet},
        title="Rewritten title",
        section_md="### Research Gap 1: Rewritten title\\n**Candidate ID**: G01",
    )
    assert found["candidate"]["candidate_id"] == "G01"
    assert found["candidate"]["section_md"] == "old section"


def test_candidate_gap_heading_keeps_full_section_for_handoff():
    sections = parse_gap_sections(
        "### Candidate gap 1: CRC calibration\n"
        "**Candidate ID**: G01\n**Research question**: Does it generalize?\n\n"
        "## Priority ranking\n| Rank | Gap |"
    )
    assert sections == [
        (
            "CRC calibration",
            "### Candidate gap 1: CRC calibration\n"
            "**Candidate ID**: G01\n**Research question**: Does it generalize?",
        )
    ]
