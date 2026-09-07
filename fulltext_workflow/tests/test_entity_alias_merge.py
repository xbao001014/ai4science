from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_merge_known_aliases_rewires_relations_and_bindings(tmp_path, monkeypatch):
    import config
    from db.entity_alias_merge import merge_known_entity_aliases
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "aliases.sqlite"))
    init_db()
    with get_conn() as conn:
        conn.execute("INSERT INTO papers (pmid, title) VALUES ('1', 'test')")
        conn.execute("INSERT INTO entities (name, type) VALUES ('support vector machine', 'Method')")
        canonical_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO entities (name, type) VALUES ('svm', 'Method')")
        alias_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO relations
               (subject_type, subject_id, relation, object_type, object_id, source_pmid)
               VALUES ('Paper', 1, 'APPLIES_METHOD', 'Method', ?, '1')""",
            (alias_id,),
        )
        conn.execute(
            "INSERT INTO paper_entity_bindings (source_pmid, method_entity_id) VALUES ('1', ?)",
            (alias_id,),
        )

    preview = merge_known_entity_aliases(apply=False)
    assert preview["group_count"] == 1
    assert preview["alias_entity_count"] == 1
    result = merge_known_entity_aliases(apply=True)
    assert result["applied"] is True
    with get_conn() as conn:
        assert conn.execute(
            "SELECT object_id FROM relations WHERE source_pmid='1'"
        ).fetchone()[0] == canonical_id
        assert conn.execute(
            "SELECT method_entity_id FROM paper_entity_bindings WHERE source_pmid='1'"
        ).fetchone()[0] == canonical_id
        names = conn.execute("SELECT name FROM entities WHERE type='Method'").fetchall()
        assert [row[0] for row in names] == ["support vector machine"]
