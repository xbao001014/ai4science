from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.method_family_blind import (  # noqa: E402
    BLIND_FIELDS,
    BlindValidationError,
    export_blind_set,
    import_blind_submission,
)


def _seed_blind_fixture() -> None:
    from db.schema import get_conn

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_gold_sets
               (gold_set_id, taxonomy_version, file_sha256, source_filename,
                byte_count, row_count, known_count, unknown_count, secondary_count,
                normalization_policy, reviewer, split_manifest_sha256,
                calibration_count, holdout_count)
               VALUES ('gold-blind-test', 'method-family-v1', ?, 'gold.csv', 10,
                       5, 4, 1, 0, 'test', 'expert', ?, 4, 1)""",
            ("a" * 64, "b" * 64),
        )
        conn.executemany(
            "INSERT INTO entities (id, name, type, method_role) VALUES (?, ?, 'Method', ?)",
            [
                (method_id, f"Method {method_id}", "backbone" if method_id % 2 else "tool")
                for method_id in range(1, 121)
            ],
        )
        conn.executemany(
            """INSERT INTO method_family_gold_labels
               (gold_set_id, method_entity_id, source_row, method_name_snapshot,
                method_role_snapshot, paper_count_snapshot, raw_primary,
                normalized_primary, secondary_json, review_notes,
                suggested_primary, top1_similarity, ranking_score, margin,
                suggested_top3_json, split, split_group)
               VALUES ('gold-blind-test', ?, ?, ?, 'unknown', 1, ?, ?, '[]', '',
                       'cnn', 0.8, 0.8, 0.1, '["cnn"]', ?, ?)""",
            [
                (
                    method_id,
                    method_id + 1,
                    f"Method {method_id}",
                    "unknown" if method_id == 5 else "cnn",
                    "unknown" if method_id == 5 else "cnn",
                    "holdout" if method_id == 5 else "calibration",
                    f"group-{method_id}",
                )
                for method_id in range(1, 6)
            ],
        )
        conn.executemany(
            """INSERT INTO relations
               (subject_type, subject_id, relation, object_type, object_id,
                source_pmid, status)
               VALUES ('Paper', ?, 'APPLIES_METHOD', 'Method', ?, ?, 'active')""",
            [(method_id, method_id, f"PMID-{method_id}") for method_id in range(1, 121)],
        )
        conn.executemany(
            """INSERT INTO method_family_assignments
               (method_entity_id, family_id, taxonomy_version, candidate_rank,
                is_primary, confidence, similarity, margin, source, status,
                input_sha256, provider, model, dimensions)
               VALUES (?, ?, 'method-family-v1', 1, 1, 0.7, 0.6, 0.1,
                       'embedding_shadow', 'review', ?, 'bailian',
                       'text-embedding-v4', 768)""",
            [
                (
                    method_id,
                    "cnn" if method_id % 3 else "other_tooling",
                    f"{method_id:064d}",
                )
                for method_id in range(1, 121)
            ],
        )


def test_blind_export_hides_predictions_and_submission_is_immutable(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "blind.sqlite"))
    init_db()
    _seed_blind_fixture()
    path = tmp_path / "blind.csv"
    first = export_blind_set("gold-blind-test", output_path=path, size=50)
    second = export_blind_set("gold-blind-test", output_path=path, size=50)
    assert first["blind_set_id"] == second["blind_set_id"]
    assert second["idempotent"] is True
    assert first["visible_model_suggestions"] == 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 50
    assert tuple(rows[0]) == BLIND_FIELDS
    assert "suggested_primary" not in rows[0]
    assert {int(row["method_entity_id"]) for row in rows}.isdisjoint(range(1, 6))
    for row in rows:
        row["gold_primary"] = "cnn"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BLIND_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    report = import_blind_submission(
        path,
        blind_set_id=first["blind_set_id"],
        reviewer="blind-expert-v1",
    )
    duplicate = import_blind_submission(
        path,
        blind_set_id=first["blind_set_id"],
        reviewer="ignored",
    )
    assert report["counts"]["rows"] == 50
    assert report["safety"]["used_for_training"] is False
    assert duplicate["idempotent"] is True
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM method_family_blind_sets").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM method_family_blind_items").fetchone()[0] == 50
        assert conn.execute("SELECT COUNT(*) FROM method_family_blind_submissions").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with get_conn() as conn:
            conn.execute(
                "UPDATE method_family_blind_sets SET row_count=51 WHERE blind_set_id=?",
                (first["blind_set_id"],),
            )


def test_blind_submission_rejects_blank_or_changed_snapshot(tmp_path, monkeypatch):
    import config
    from db.schema import init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "invalid.sqlite"))
    init_db()
    _seed_blind_fixture()
    path = tmp_path / "blind.csv"
    result = export_blind_set("gold-blind-test", output_path=path, size=50)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["method_name"] = "changed"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BLIND_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(BlindValidationError, match="frozen field method_name"):
        import_blind_submission(
            path,
            blind_set_id=result["blind_set_id"],
            reviewer="blind-expert-v1",
        )


def test_next_blind_generation_excludes_prior_blind_methods(tmp_path, monkeypatch):
    import config
    from db.schema import init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "generation.sqlite"))
    init_db()
    _seed_blind_fixture()
    first = export_blind_set(
        "gold-blind-test", output_path=tmp_path / "g1.csv", size=50, generation=1
    )
    second = export_blind_set(
        "gold-blind-test", output_path=tmp_path / "g2.csv", size=10 + 40, generation=2
    )
    with (tmp_path / "g1.csv").open(encoding="utf-8-sig", newline="") as handle:
        first_ids = {int(row["method_entity_id"]) for row in csv.DictReader(handle)}
    with (tmp_path / "g2.csv").open(encoding="utf-8-sig", newline="") as handle:
        second_ids = {int(row["method_entity_id"]) for row in csv.DictReader(handle)}
    assert first["rows"] == 50
    assert second["prior_blind_methods_excluded"] == 50
    assert first_ids.isdisjoint(second_ids)
