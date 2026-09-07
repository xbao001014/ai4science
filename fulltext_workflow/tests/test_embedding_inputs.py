from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.embedding_inputs import (  # noqa: E402
    build_embedding_plan,
    load_method_embedding_inputs,
)


def _seed(conn):
    conn.execute("INSERT INTO papers (pmid, title) VALUES ('2', 'Second paper')")
    conn.execute("INSERT INTO papers (pmid, title) VALUES ('1', 'First paper')")
    conn.execute(
        """INSERT INTO entities (name, type, aliases, method_role)
           VALUES ('TransMIL', 'Method', '[\"Transformer MIL\", \"trans-mil\"]', 'aggregator')"""
    )
    method_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO entities (name, type) VALUES ('Unused', 'Method')")
    conn.execute(
        """INSERT INTO relations
           (subject_type, subject_id, relation, object_type, object_id,
            source_pmid, evidence_section, evidence_quote, status)
           VALUES ('Paper', 1, 'APPLIES_METHOD', 'Method', ?, '2',
                   'discussion', 'later evidence', 'active')""",
        (method_id,),
    )
    relation_two = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO relations
           (subject_type, subject_id, relation, object_type, object_id,
            source_pmid, evidence_section, evidence_quote, status)
           VALUES ('Paper', 1, 'APPLIES_METHOD', 'Method', ?, '1',
                   'methods', 'legacy evidence', 'active')""",
        (method_id,),
    )
    relation_one = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO relation_evidence
           (relation_id, source_pmid, evidence_section, evidence_quote,
            evidence_sha256)
           VALUES (?, '1', 'methods', 'preferred evidence', 'hash-1')""",
        (relation_one,),
    )
    return method_id, relation_two


def test_method_input_is_deterministic_and_privacy_bounded(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "inputs.sqlite"))
    init_db()
    with get_conn() as conn:
        method_id, _ = _seed(conn)
    first = load_method_embedding_inputs()
    assert len(first) == 1
    assert first[0].method_entity_id == method_id
    assert first[0].context_quality == "evidence"
    assert "preferred evidence" in first[0].text
    assert "legacy evidence" not in first[0].text
    assert first[0].text.index("pmid: 1") < first[0].text.index("pmid: 2")
    assert "Unused" not in first[0].text

    with get_conn() as conn:
        conn.execute(
            "UPDATE entities SET aliases='[\"trans-mil\", \"Transformer MIL\"]' WHERE id=?",
            (method_id,),
        )
    second = load_method_embedding_inputs()
    assert second[0].text == first[0].text
    assert second[0].input_sha256 == first[0].input_sha256


def test_context_change_changes_hash_and_inactive_is_excluded(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "changes.sqlite"))
    init_db()
    with get_conn() as conn:
        _, relation_id = _seed(conn)
    old_hash = load_method_embedding_inputs()[0].input_sha256
    with get_conn() as conn:
        conn.execute(
            "UPDATE relations SET evidence_quote='changed evidence' WHERE id=?",
            (relation_id,),
        )
    assert load_method_embedding_inputs()[0].input_sha256 != old_hash
    with get_conn() as conn:
        conn.execute("UPDATE relations SET status='superseded'")
    assert load_method_embedding_inputs() == []


def test_dry_run_plan_has_no_cache_writes(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "plan.sqlite"))
    init_db()
    with get_conn() as conn:
        _seed(conn)
    plan = build_embedding_plan(batch_size=10)
    assert plan["estimate_only"] is True
    assert plan["candidate_methods"] == 1
    assert plan["cache_misses"] == 1
    assert plan["estimated_sync_requests"] == 1
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM embedding_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0] == 0
