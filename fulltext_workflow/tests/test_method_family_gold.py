from __future__ import annotations

import csv
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.method_family_gold import (  # noqa: E402
    GoldValidationError,
    assign_deterministic_split,
    calibrate_gold_set,
    gold_summary,
    import_gold_set,
    load_and_validate_gold_csv,
)
from analysis.method_taxonomy import FAMILIES  # noqa: E402


FIELDS = (
    "method_entity_id",
    "method_name",
    "method_role",
    "paper_count",
    "first_year",
    "last_year",
    "suggested_primary",
    "top1_similarity",
    "ranking_score",
    "margin",
    "suggested_top3",
    "gold_primary",
    "gold_secondary",
    "review_notes",
)


def _write_gold(path: Path, rows: list[dict[str, object]]) -> str:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(
    method_id: int,
    *,
    gold: str = "cnn",
    suggested: str = "cnn",
    score: float = 0.8,
    margin: float = 0.1,
    reject: bool = False,
) -> dict[str, object]:
    alternatives = [family.family_id for family in FAMILIES if family.family_id != suggested][:2]
    return {
        "method_entity_id": method_id,
        "method_name": f"Synthetic method {method_id}",
        "method_role": "backbone" if method_id % 2 else "unknown",
        "paper_count": 12 if method_id % 3 == 0 else 1,
        "first_year": 2020,
        "last_year": 2026,
        "suggested_primary": suggested,
        "top1_similarity": 0.6,
        "ranking_score": score,
        "margin": margin,
        "suggested_top3": "|".join([suggested, *alternatives]),
        "gold_primary": "" if reject else gold,
        "gold_secondary": "",
        "review_notes": "[reject] generic method" if reject else "",
    }


def _seed_methods(count: int) -> None:
    from db.schema import get_conn

    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO entities (id, name, type) VALUES (?, ?, 'Method')",
            [(method_id, f"Synthetic method {method_id}") for method_id in range(1, count + 1)],
        )


def test_validate_normalizes_legacy_reject_and_split_is_deterministic(tmp_path):
    path = tmp_path / "gold.csv"
    rows = [_row(method_id, reject=method_id > 16) for method_id in range(1, 21)]
    digest = _write_gold(path, rows)

    first = assign_deterministic_split(
        load_and_validate_gold_csv(path, expected_sha256=digest, expected_rows=20)
    )
    second = assign_deterministic_split(
        load_and_validate_gold_csv(path, expected_sha256=digest, expected_rows=20)
    )
    summary = gold_summary(first)

    assert summary["known_rows"] == 16
    assert summary["unknown_rows"] == 4
    assert summary["legacy_reject_rows"] == 4
    assert summary["split_counts"] == {"calibration": 14, "holdout": 6}
    assert first.split_manifest_sha256 == second.split_manifest_sha256
    assert [row.split for row in first.rows] == [row.split for row in second.rows]


def test_validate_rejects_unlabeled_blank_and_hash_mismatch(tmp_path):
    path = tmp_path / "invalid.csv"
    row = _row(1)
    row["gold_primary"] = ""
    _write_gold(path, [row])

    with pytest.raises(GoldValidationError, match="empty gold_primary"):
        load_and_validate_gold_csv(path, expected_rows=1)
    with pytest.raises(GoldValidationError, match="SHA-256 mismatch"):
        load_and_validate_gold_csv(path, expected_sha256="0" * 64, expected_rows=1)


def test_import_is_idempotent_and_tables_are_immutable(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "gold.sqlite"))
    init_db()
    _seed_methods(10)
    path = tmp_path / "gold.csv"
    rows = [_row(method_id, reject=method_id > 8) for method_id in range(1, 11)]
    digest = _write_gold(path, rows)

    first = import_gold_set(
        path,
        reviewer="expert-v1",
        expected_sha256=digest,
        expected_rows=10,
    )
    second = import_gold_set(
        path,
        reviewer="ignored-on-idempotent-reimport",
        expected_sha256=digest,
        expected_rows=10,
    )
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert first["gold_set_id"] == second["gold_set_id"]
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM method_family_gold_sets").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM method_family_gold_labels").fetchone()[0] == 10
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with get_conn() as conn:
            conn.execute(
                "UPDATE method_family_gold_sets SET reviewer='changed' WHERE gold_set_id=?",
                (first["gold_set_id"],),
            )


def test_calibration_freezes_report_without_promoting_assignments(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "calibration.sqlite"))
    init_db()
    _seed_methods(100)
    path = tmp_path / "gold.csv"
    rows = [
        _row(
            method_id,
            reject=method_id > 80,
            score=0.8 if method_id <= 80 else 0.4,
            margin=0.1 if method_id <= 80 else 0.01,
        )
        for method_id in range(1, 101)
    ]
    _write_gold(path, rows)
    imported = import_gold_set(path, reviewer="expert-v1", expected_rows=100)
    report_path = tmp_path / "calibration.json"
    first = calibrate_gold_set(imported["gold_set_id"], output_path=report_path)
    second = calibrate_gold_set(imported["gold_set_id"], output_path=report_path)

    assert first["status"] == "threshold_validated"
    assert first["embedding_family_allowlist"] == ["cnn"]
    assert first["release_build_eligible"] is False
    assert second["idempotent"] is True
    assert report_path.exists()
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM method_family_calibrations").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM method_family_assignments WHERE status='accepted'"
        ).fetchone()[0] == 0
