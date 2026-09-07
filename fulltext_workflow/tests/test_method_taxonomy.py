from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.embedding_inputs import MethodEmbeddingInput  # noqa: E402
from analysis.embedding_store import CacheWrite, put_cached_vectors  # noqa: E402
from analysis.method_taxonomy import (  # noqa: E402
    FAMILIES,
    export_gold_template,
    prototype_embedding_items,
    shadow_classify_cached_methods,
    sync_family_catalog,
)


def test_catalog_has_13_stable_families_and_unique_prototypes(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "taxonomy.sqlite"))
    init_db()
    assert sync_family_catalog("test-v1") == 13
    assert len({family.family_id for family in FAMILIES}) == 13
    items, family_by_item = prototype_embedding_items("test-v1")
    assert len(items) > 50
    assert len({item.input_sha256 for item in items}) == len(items)
    assert set(family_by_item.values()) == {family.family_id for family in FAMILIES}
    with get_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM method_taxonomy_families WHERE taxonomy_version='test-v1'"
        ).fetchone()[0] == 13


def test_shadow_classification_writes_review_only_top_k(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "shadow.sqlite"))
    init_db()
    with get_conn() as conn:
        conn.execute("INSERT INTO entities (name, type) VALUES ('Example MIL', 'Method')")
        method_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO papers (pmid, title, year) VALUES ('1', 'MIL paper', 2026)")
        conn.execute(
            """INSERT INTO relations
               (subject_type, subject_id, relation, object_type, object_id, source_pmid)
               VALUES ('Paper', 1, 'APPLIES_METHOD', 'Method', ?, '1')""",
            (method_id,),
        )
    text = "method: Example MIL"
    input_hash = hashlib.sha256(text.encode()).hexdigest()
    put_cached_vectors(
        [CacheWrite(input_hash, (1.0, 0.0, 0.0), len(text))],
        provider="bailian",
        model="test-model",
        dimensions=3,
    )
    centroids = {}
    for index, family in enumerate(FAMILIES):
        if family.family_id == "mil":
            centroids[family.family_id] = (1.0, 0.0, 0.0)
        else:
            centroids[family.family_id] = (0.0, 1.0, (index + 1) / 100.0)
    item = MethodEmbeddingInput(
        method_entity_id=method_id,
        text=text,
        input_sha256=input_hash,
        context_quality="name_only",
        input_chars=len(text),
        input_bytes=len(text.encode()),
        estimated_tokens=7,
    )
    result = shadow_classify_cached_methods(
        [item],
        centroids,
        provider="bailian",
        model="test-model",
        dimensions=3,
        taxonomy_version="test-v1",
        top_k=3,
    )
    assert result["classified_methods"] == 1
    assert result["primary_family_counts"] == {"mil": 1}
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT family_id, candidate_rank, is_primary, status, source
               FROM method_family_assignments ORDER BY candidate_rank"""
        ).fetchall()
    assert len(rows) == 3
    assert rows[0]["family_id"] == "mil"
    assert rows[0]["is_primary"] == 1
    assert all(row["status"] == "review" for row in rows)
    assert all(row["source"] == "embedding_shadow" for row in rows)
    output = tmp_path / "gold.csv"
    exported = export_gold_template(output, size=1)
    assert exported["rows"] == 1
    text_out = output.read_text(encoding="utf-8-sig")
    assert "gold_primary" in text_out
    assert "Example MIL" in text_out
