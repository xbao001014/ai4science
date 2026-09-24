"""Grounded paper-local annotations remain separate from global entities."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    get_conn, init_db, insert_relation, insert_relation_evidence,
    upsert_entity, upsert_paper,
)
from extractor.entity_mention_backfill import backfill_paper_mentions  # noqa: E402
from extractor.evidence_grounding import ground_triples  # noqa: E402
from extractor.section_extractor import _save_triple  # noqa: E402
from extractor.triple_models import Triple  # noqa: E402


def test_method_and_disease_mentions_keep_source_annotations(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "mentions.db")
    init_db()
    paper_id = upsert_paper({"pmid": "test-1", "title": "Test", "extraction_done": 1})
    method_source = "We applied graph convolutional network (GCN) to the slides."
    disease_source = "Our cohort had incidentally detected HER2-positive breast carcinoma."
    method = Triple.model_validate({
        "subject": {"name": "paper", "type": "Method"},
        "relation": "APPLIES_METHOD",
        "object": {"name": "GCN", "type": "Method"},
        "evidence_quote": method_source,
    })
    disease = Triple.model_validate({
        "subject": {"name": "paper", "type": "Method"},
        "relation": "TARGETS_DISEASE",
        "object": {"name": "HER2-positive breast carcinoma", "type": "Disease"},
        "evidence_quote": disease_source,
        "disease_qualifiers": [
            {"kind": "molecular", "phrase": "HER2-positive"},
            {"kind": "other", "phrase": "incidentally detected"},
            {"kind": "stage", "phrase": "stage IV"},
        ],
    })
    grounded_method = ground_triples(
        [method], method_source,
        abbreviation_map={"gcn": ("graph convolutional network", "graph convolutional network (GCN)")},
    )[0][0]
    grounded_disease = ground_triples([disease], disease_source)[0][0]
    _save_triple(grounded_method, paper_id, "test-1", "methods", "fulltext")
    _save_triple(grounded_disease, paper_id, "test-1", "methods", "fulltext")

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT entity_type, surface_name, explicit_long_form, qualifiers_json, "
            "resolution_status FROM entity_mentions ORDER BY entity_type"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["entity_type"] == "Disease"
    assert json.loads(rows[0]["qualifiers_json"]) == [
        {"kind": "molecular", "phrase": "HER2-positive"}
    ]
    assert rows[1]["explicit_long_form"] == "graph convolutional network"
    assert all(row["resolution_status"] == "unresolved" for row in rows)


def test_disease_abbreviation_uses_only_same_paper_definition():
    source = "The cohort included hepatocellular carcinoma (HCC). We studied HCC."
    from extractor.mention_context import abbreviation_definitions
    definitions = abbreviation_definitions([source])
    assert definitions["hcc"][0] == "hepatocellular carcinoma"
    triple = Triple.model_validate({
        "subject": {"name": "paper", "type": "Method"},
        "relation": "TARGETS_DISEASE",
        "object": {"name": "HCC", "type": "Disease"},
        "evidence_quote": "We studied HCC.",
    })
    grounded, _ = ground_triples(
        [triple], source,
        abbreviation_map=definitions,
    )
    assert grounded[0].disease_long_form == "hepatocellular carcinoma"
    assert ground_triples([triple], source, abbreviation_map={})[0][0].disease_long_form is None


def test_backfill_adds_missing_reconcile_mention(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "backfill.db")
    init_db()
    paper_id = upsert_paper({"pmid": "test-2", "title": "Test", "extraction_done": 1})
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO document_sections(paper_id,section_type,content) VALUES (?,?,?)",
            (paper_id, "methods", "hepatocellular carcinoma (HCC) was studied."),
        )
    entity_id = upsert_entity("HCC", "Disease")
    relation_id = insert_relation(
        "Paper", paper_id, "COVERS_DISEASE", "Disease", entity_id,
        source_pmid="test-2", evidence_quote="HCC was studied.",
    )
    insert_relation_evidence(
        relation_id, source_pmid="test-2", evidence_quote="HCC was studied."
    )
    assert backfill_paper_mentions("test-2") == 1
    assert backfill_paper_mentions("test-2") == 0
    with get_conn() as conn:
        row = conn.execute(
            "SELECT explicit_long_form,annotation_version FROM entity_mentions"
        ).fetchone()
    assert row["explicit_long_form"] == "hepatocellular carcinoma"
    assert row["annotation_version"] == "mention/v1-backfill"


def test_malformed_optional_qualifier_does_not_drop_triple():
    triple = Triple.model_validate({
        "subject": {"name": "paper", "type": "Method"},
        "relation": "TARGETS_DISEASE",
        "object": {"name": "lung adenocarcinoma", "type": "Disease"},
        "evidence_quote": "The cohort had lung adenocarcinoma.",
        "disease_qualifiers": ["lung", {"kind": "invalid", "phrase": "lung"}],
    })
    assert triple.disease_qualifiers == []


def test_backfill_recovers_only_locatable_legacy_relation_quote(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "legacy.db")
    init_db()
    paper_id = upsert_paper({"pmid": "legacy-1", "title": "Test", "extraction_done": 1})
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO document_sections(paper_id,section_type,content) VALUES (?,?,?)",
            (paper_id, "methods", "We used graph convolutional network (GCN)."),
        )
    entity_id = upsert_entity("GCN", "Method")
    insert_relation(
        "Paper", paper_id, "APPLIES_METHOD", "Method", entity_id,
        source_pmid="legacy-1", evidence_quote="We used graph convolutional network (GCN).",
    )
    assert backfill_paper_mentions("legacy-1") == 1
    with get_conn() as conn:
        row = conn.execute(
            """SELECT m.explicit_long_form,re.evidence_status FROM entity_mentions m
               JOIN relation_evidence re ON re.id=m.relation_evidence_id"""
        ).fetchone()
    assert row["explicit_long_form"] == "graph convolutional network"
    assert row["evidence_status"] == "located"
