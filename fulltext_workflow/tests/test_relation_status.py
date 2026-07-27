"""Tests for relation status, reconcile flags, and paper_entity_bindings."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    clear_paper_kg_extractions,
    get_conn,
    get_papers_by_pmids,
    init_db,
    insert_relation,
    mark_extraction_done,
    set_paper_reconcile_status,
    supersede_relation,
    upsert_entity,
    upsert_paper,
    upsert_paper_entity_binding,
)


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_insert_relation_defaults_active(monkeypatch):
    _tmp_db(monkeypatch)
    sid = upsert_entity("lung cancer", "Disease")
    oid = upsert_entity("small sample size", "Limitation")
    insert_relation(
        "Disease",
        sid,
        "REPORTS_LIMITATION",
        "Limitation",
        oid,
        source_pmid="12345",
    )
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, extraction_pass FROM relations WHERE source_pmid=?",
            ("12345",),
        ).fetchone()
    assert row["status"] == "active"
    assert row["extraction_pass"] == "section"


def test_supersede_relation(monkeypatch):
    _tmp_db(monkeypatch)
    sid = upsert_entity("lung cancer", "Disease")
    frag_id = upsert_entity("limited cohort", "Limitation")
    canonical_id = upsert_entity("small sample size", "Limitation")

    insert_relation(
        "Disease",
        sid,
        "REPORTS_LIMITATION",
        "Limitation",
        frag_id,
        source_pmid="999",
    )
    insert_relation(
        "Disease",
        sid,
        "REPORTS_LIMITATION",
        "Limitation",
        canonical_id,
        source_pmid="999",
    )
    with get_conn() as conn:
        frag_row = conn.execute(
            "SELECT id FROM relations WHERE object_id=?", (frag_id,)
        ).fetchone()
    supersede_relation(frag_row["id"], canonical_id)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, superseded_by FROM relations WHERE id=?",
            (frag_row["id"],),
        ).fetchone()
    assert row["status"] == "superseded"
    assert row["superseded_by"] == canonical_id


def test_clear_paper_kg_extractions(monkeypatch):
    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "555", "title": "Test paper"})
    mark_extraction_done(pid, "observational")
    set_paper_reconcile_status(pid, "done")

    sid = upsert_entity("lung cancer", "Disease")
    oid = upsert_entity("tcga", "Dataset")
    insert_relation(
        "Disease",
        sid,
        "USES_DATASET",
        "Dataset",
        oid,
        source_pmid="555",
    )
    upsert_paper_entity_binding(
        "555",
        method_entity_id=sid,
        disease_entity_id=sid,
        dataset_entity_id=oid,
        confidence=0.9,
        evidence_quote="used tcga",
    )

    clear_paper_kg_extractions("555")

    with get_conn() as conn:
        rel_cnt = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid=?", ("555",)
        ).fetchone()[0]
        bind_cnt = conn.execute(
            "SELECT COUNT(*) FROM paper_entity_bindings WHERE source_pmid=?", ("555",)
        ).fetchone()[0]
        paper = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid=?", ("555",)
        ).fetchone()
    assert rel_cnt == 0
    assert bind_cnt == 0
    assert paper["extraction_done"] == 0
    assert paper["reconcile_status"] == "pending"


def test_upsert_paper_entity_binding(monkeypatch):
    _tmp_db(monkeypatch)
    method_id = upsert_entity("cnn", "Method")
    disease_id = upsert_entity("melanoma", "Disease")
    dataset_id = upsert_entity("isic", "Dataset")

    upsert_paper_entity_binding(
        "777",
        method_entity_id=method_id,
        disease_entity_id=disease_id,
        dataset_entity_id=dataset_id,
        confidence=0.8,
        evidence_quote="first",
    )
    upsert_paper_entity_binding(
        "777",
        method_entity_id=method_id,
        disease_entity_id=disease_id,
        dataset_entity_id=dataset_id,
        confidence=1.0,
        evidence_quote="updated",
    )

    with get_conn() as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM paper_entity_bindings WHERE source_pmid=?", ("777",)
        ).fetchone()[0]
        row = conn.execute(
            """SELECT confidence, evidence_quote FROM paper_entity_bindings
               WHERE source_pmid=?""",
            ("777",),
        ).fetchone()
    assert cnt == 1
    assert row["confidence"] == 1.0
    assert row["evidence_quote"] == "updated"


def test_get_papers_by_pmids(monkeypatch):
    _tmp_db(monkeypatch)
    upsert_paper({"pmid": "111", "title": "Paper A"})
    upsert_paper({"pmid": "222", "title": "Paper B"})

    rows = get_papers_by_pmids(["111", "222", "333"])
    pmids = {r["pmid"] for r in rows}
    assert pmids == {"111", "222"}
