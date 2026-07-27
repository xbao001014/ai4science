"""Unit tests for fulltext reconcile assemble/parse helpers."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    get_conn,
    init_db,
    insert_relation,
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


def test_assemble_prefers_core_sections_and_truncates():
    from extractor.fulltext_reconcile import assemble_reconcile_text

    sections = [
        {"section_type": "introduction", "content": "INTRO " * 5000},
        {"section_type": "methods", "content": "METHODS " * 100},
        {"section_type": "discussion", "content": "DISC " * 100},
        {"section_type": "limitations", "content": "LIM " * 50},
    ]
    text = assemble_reconcile_text(sections, max_chars=2000)
    assert "METHODS" in text
    assert "LIM" in text
    assert len(text) <= 2000


def test_parse_reconcile_payload_normalizes():
    from extractor.fulltext_reconcile import parse_reconcile_payload

    raw = {
        "datasets": [
            {
                "name": "PubMed",
                "access": "public",
                "action": "drop",
                "reason": "platform",
            }
        ],
        "bindings": [
            {"method": "CNN", "disease": "breast cancer", "dataset": "", "quote": "q"}
        ],
        "limitations": [
            {"canonical": "small sample size", "merges": ["small n"], "quote": "q2"}
        ],
    }
    p = parse_reconcile_payload(raw)
    assert p["datasets"][0]["action"] == "drop"
    assert p["bindings"][0]["dataset"] == ""
    assert p["limitations"][0]["canonical"] == "small sample size"


def test_apply_reconcile_payload(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "12345678"
    paper_id = upsert_paper({"pmid": pmid, "title": "Reconcile test paper"})

    pubmed_id = upsert_entity("pubmed", "Dataset")
    camelyon_id = upsert_entity("camelyon16", "Dataset", access_class="unknown")
    small_n_id = upsert_entity("small n", "Limitation")
    cohort_id = upsert_entity("limited cohort", "Limitation")

    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        pubmed_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        camelyon_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "REPORTS_LIMITATION",
        "Limitation",
        small_n_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "REPORTS_LIMITATION",
        "Limitation",
        cohort_id,
        source_pmid=pmid,
        extraction_pass="section",
    )

    payload = {
        "datasets": [
            {"name": "PubMed", "access": "public", "action": "drop", "reason": "platform"},
            {"name": "camelyon16", "access": "public", "action": "keep", "reason": "benchmark"},
        ],
        "limitations": [
            {
                "canonical": "small sample size",
                "merges": ["small n", "limited cohort"],
                "quote": "small cohort limits generalizability",
            }
        ],
        "bindings": [
            {
                "method": "CNN",
                "disease": "breast cancer",
                "dataset": "camelyon16",
                "quote": "CNN on Camelyon16 for breast cancer",
            }
        ],
    }
    apply_reconcile_payload(paper_id, pmid, payload)

    with get_conn() as conn:
        active_datasets = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET' AND r.status='active'""",
            (pmid,),
        ).fetchall()
        pubmed_row = conn.execute(
            """SELECT r.status, r.superseded_by FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND e.name='pubmed'""",
            (pmid,),
        ).fetchone()
        active_lims = conn.execute(
            """SELECT e.name, r.extraction_pass, r.evidence_section
               FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='REPORTS_LIMITATION'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
        superseded_lims = conn.execute(
            """SELECT e.name, r.superseded_by FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='REPORTS_LIMITATION'
                 AND r.status='superseded'""",
            (pmid,),
        ).fetchall()
        bind_cnt = conn.execute(
            "SELECT COUNT(*) FROM paper_entity_bindings WHERE source_pmid=?",
            (pmid,),
        ).fetchone()[0]
        camelyon_access = conn.execute(
            "SELECT access_class FROM entities WHERE id=?", (camelyon_id,)
        ).fetchone()["access_class"]

    assert {r["name"] for r in active_datasets} == {"camelyon16"}
    assert pubmed_row["status"] == "superseded"
    assert pubmed_row["superseded_by"] is None
    assert len(active_lims) == 1
    assert active_lims[0]["name"] == "small sample size"
    assert active_lims[0]["extraction_pass"] == "fulltext_reconcile"
    assert active_lims[0]["evidence_section"] == "fulltext_reconcile"
    assert len(superseded_lims) == 2
    canonical_id = upsert_entity("small sample size", "Limitation")
    assert all(r["superseded_by"] == canonical_id for r in superseded_lims)
    assert bind_cnt == 1
    assert camelyon_access == "public"


def test_apply_platform_keep_and_binding_do_not_pollute(monkeypatch):
    """Pass 2 apply must treat platform keep/binding as drop — no active edges."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "87654321"
    paper_id = upsert_paper({"pmid": pmid, "title": "Platform pollution test"})

    pubmed_id = upsert_entity("pubmed", "Dataset")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        pubmed_id,
        source_pmid=pmid,
        extraction_pass="section",
    )

    payload = {
        "datasets": [
            {"name": "PubMed", "access": "public", "action": "keep", "reason": "mistake"},
        ],
        "bindings": [
            {
                "method": "CNN",
                "disease": "breast cancer",
                "dataset": "PubMed",
                "quote": "CNN trained on PubMed",
            }
        ],
        "limitations": [],
    }
    apply_reconcile_payload(paper_id, pmid, payload)

    with get_conn() as conn:
        active_datasets = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
        pubmed_status = conn.execute(
            """SELECT r.status FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND e.name='pubmed'""",
            (pmid,),
        ).fetchone()["status"]
        bind_rows = conn.execute(
            """SELECT b.dataset_entity_id, e.name
               FROM paper_entity_bindings b
               LEFT JOIN entities e ON e.id = b.dataset_entity_id
               WHERE b.source_pmid=?""",
            (pmid,),
        ).fetchall()

    assert active_datasets == []
    assert pubmed_status == "superseded"
    assert len(bind_rows) == 1
    assert bind_rows[0]["dataset_entity_id"] is None


def test_apply_dataset_merge_supersedes_aliases(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "11223344"
    paper_id = upsert_paper({"pmid": pmid, "title": "Dataset merge test"})

    alias_a_id = upsert_entity("camelyon 16", "Dataset")
    alias_b_id = upsert_entity("camelyon16 dataset", "Dataset")
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        alias_a_id,
        source_pmid=pmid,
        extraction_pass="section",
    )
    insert_relation(
        "Paper",
        paper_id,
        "USES_DATASET",
        "Dataset",
        alias_b_id,
        source_pmid=pmid,
        extraction_pass="section",
    )

    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [
                {
                    "name": "camelyon16",
                    "access": "public",
                    "action": "merge",
                    "reason": "alias collapse",
                }
            ],
            "bindings": [],
            "limitations": [],
        },
    )

    with get_conn() as conn:
        active = conn.execute(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                 AND r.status='active'""",
            (pmid,),
        ).fetchall()
        superseded = conn.execute(
            """SELECT e.name, r.superseded_by FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                 AND r.status='superseded'""",
            (pmid,),
        ).fetchall()

    assert {r["name"] for r in active} == {"camelyon16"}
    assert len(active) == 1
    assert {r["name"] for r in superseded} == {"camelyon 16", "camelyon16 dataset"}
    assert all(r["superseded_by"] is None for r in superseded)
