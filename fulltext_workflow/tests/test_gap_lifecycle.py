"""Unit tests for limitation temporal profiles and gap lifecycle heuristics."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

config.DB_PATH = str(_ROOT / "data" / "test_gap_lifecycle.db")

from analysis.gap_lifecycle import (  # noqa: E402
    classify_temporal_status,
    compute_limitation_gap_status,
    compute_limitation_temporal_profiles,
    compute_resolution_signal,
    run_gap_lifecycle,
)
from db.schema import (  # noqa: E402
    get_limitation_temporal_rows,
    init_db,
    insert_relation,
    upsert_entity,
    upsert_paper,
)


def _setup_db() -> None:
    db_path = config.DB_PATH
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()


def _seed_persistent_fixture() -> int:
    paper_a = upsert_paper({
        "pmid": "90000001",
        "title": "Early pathology AI study",
        "year": 2018,
        "abstract": "Abstract about digital pathology limitations.",
    })
    paper_b = upsert_paper({
        "pmid": "90000002",
        "title": "Recent pathology AI follow-up",
        "year": 2024,
        "abstract": "Follow-up on small sample size limitation.",
    })
    paper_c = upsert_paper({
        "pmid": "90000003",
        "title": "Method application on lung cancer",
        "year": 2024,
        "abstract": "CNN applied to lung cancer classification.",
    })

    lim_id = upsert_entity("small sample size", "Limitation")
    disease_id = upsert_entity("lung cancer", "Disease")
    method_id = upsert_entity("cnn", "Method")
    task_id = upsert_entity("classification", "Task")

    insert_relation(
        "Paper", paper_a, "REPORTS_LIMITATION", "Limitation", lim_id,
        source_pmid="90000001", evidence_section="limitations", polarity="asserted",
    )
    insert_relation(
        "Paper", paper_a, "TARGETS_DISEASE", "Disease", disease_id,
        source_pmid="90000001", evidence_section="methods",
    )
    insert_relation(
        "Paper", paper_a, "APPLIES_METHOD", "Method", method_id,
        source_pmid="90000001", evidence_section="methods",
    )
    insert_relation(
        "Paper", paper_b, "REPORTS_LIMITATION", "Limitation", lim_id,
        source_pmid="90000002", evidence_section="discussion", polarity="asserted",
    )
    insert_relation(
        "Paper", paper_b, "TARGETS_DISEASE", "Disease", disease_id,
        source_pmid="90000002", evidence_section="methods",
    )
    insert_relation(
        "Paper", paper_c, "TARGETS_DISEASE", "Disease", disease_id,
        source_pmid="90000003", evidence_section="methods",
    )
    insert_relation(
        "Paper", paper_c, "APPLIES_METHOD", "Method", method_id,
        source_pmid="90000003", evidence_section="methods",
    )
    insert_relation(
        "Paper", paper_c, "PERFORMS_TASK", "Task", task_id,
        source_pmid="90000003", evidence_section="results",
    )
    return lim_id


def _seed_declining_fixture() -> None:
    paper_old = upsert_paper({
        "pmid": "90000010",
        "title": "Old limitation only",
        "year": 2016,
        "abstract": "Legacy study.",
    })
    lim_id = upsert_entity("lack of external validation", "Limitation")
    insert_relation(
        "Paper", paper_old, "REPORTS_LIMITATION", "Limitation", lim_id,
        source_pmid="90000010", evidence_section="limitations", polarity="asserted",
    )


def test_classify_temporal_status():
    from analysis.gap_lifecycle import recent_year_cutoff

    cutoff = recent_year_cutoff()
    assert classify_temporal_status(cutoff, cutoff + 1, 2, 2, 1.0) == "emerging"
    assert classify_temporal_status(2018, cutoff - 1, 4, 0, 0.0) == "declining"
    assert classify_temporal_status(2018, cutoff + 1, 4, 2, 0.5) == "persistent"


def test_persistent_limitation_profile():
    _setup_db()
    _seed_persistent_fixture()
    profiles = compute_limitation_temporal_profiles()
    row = next(r for r in profiles if r["limitation_name"] == "small sample size")
    assert row["first_year"] == 2018
    assert row["last_year"] == 2024
    assert row["paper_cnt"] == 2
    assert row["temporal_status"] == "persistent"


def test_resolution_signal_moderate():
    _setup_db()
    _seed_persistent_fixture()
    profiles = compute_limitation_temporal_profiles()
    profile = next(r for r in profiles if r["limitation_name"] == "small sample size")
    signal = compute_resolution_signal(profile)
    assert signal["followup_paper_cnt"] >= 1
    assert signal["resolution_signal"] in ("weak", "moderate")


def test_declining_limitation():
    _setup_db()
    _seed_declining_fixture()
    profiles = compute_limitation_temporal_profiles()
    row = next(
        r for r in profiles if r["limitation_name"] == "lack of external validation"
    )
    assert row["temporal_status"] == "declining"
    assert row["recent_cnt"] == 0


def test_run_gap_lifecycle_persists():
    _setup_db()
    _seed_persistent_fixture()
    stats = run_gap_lifecycle(force=True)
    assert stats["profiles_computed"] >= 1
    assert stats["limitation_temporal"] >= 1
    cached = get_limitation_temporal_rows(limit=10)
    assert any(r["limitation_name"] == "small sample size" for r in cached)


def test_limitation_gap_status_tool_shape():
    _setup_db()
    _seed_persistent_fixture()
    rows = compute_limitation_gap_status()
    assert rows
    assert "resolution_signal" in rows[0]
    assert "temporal_status" in rows[0]


if __name__ == "__main__":
    test_classify_temporal_status()
    test_persistent_limitation_profile()
    test_resolution_signal_moderate()
    test_declining_limitation()
    test_run_gap_lifecycle_persists()
    test_limitation_gap_status_tool_shape()
    print("all ok")
