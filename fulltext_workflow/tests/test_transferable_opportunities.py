"""Transferable opportunities require ok Task bridges (no Cartesian holes)."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.weekly_hotspot import (  # noqa: E402
    compute_emerging_gap_opportunities,
    compute_weekly_hotspots,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)
    init_db()
    return path


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _paper(pmid: str, days_ago: int) -> int:
    return upsert_paper(
        {
            "pmid": pmid,
            "title": pmid,
            "pub_date": _iso(days_ago),
            "year": int(_iso(days_ago)[:4]),
            "date_precision": "day",
            "extraction_done": 1,
        }
    )


def _edge(pmid: str, paper_id: int, relation: str, name: str, entity_type: str) -> None:
    entity_id = upsert_entity(name, entity_type)
    insert_relation(
        "Paper",
        paper_id,
        relation,
        entity_type,
        entity_id,
        source_pmid=pmid,
        status="active",
    )


def test_cartesian_hot_without_ok_task_bridge_is_excluded(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = _paper("1", 3)
    _edge("1", p1, "APPLIES_METHOD", "method-a", "Method")
    _edge("1", p1, "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("1", p1, "PERFORMS_TASK", "survival prediction", "Task")
    p2 = _paper("2", 4)
    _edge("2", p2, "APPLIES_METHOD", "method-b", "Method")
    _edge("2", p2, "TARGETS_DISEASE", "disease-b", "Disease")
    _edge("2", p2, "PERFORMS_TASK", "tumor segmentation", "Task")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    pairs = {(row["method"], row["disease"]) for row in rows}

    assert ("method-a", "disease-b") not in pairs
    assert ("method-b", "disease-a") not in pairs


def test_sparse_pair_with_ok_cross_paper_task_bridge_is_included(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = _paper("1", 3)
    _edge("1", p1, "APPLIES_METHOD", "method-a", "Method")
    _edge("1", p1, "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("1", p1, "PERFORMS_TASK", "survival prediction", "Task")
    p2 = _paper("2", 5)
    _edge("2", p2, "TARGETS_DISEASE", "disease-b", "Disease")
    _edge("2", p2, "PERFORMS_TASK", "survival prediction", "Task")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    hit = [
        row
        for row in rows
        if row["method"] == "method-a" and row["disease"] == "disease-b"
    ]

    assert hit, rows
    assert hit[0]["literature_gap"] == "unexplored"
    assert hit[0]["literature_paper_cnt"] == 0
    assert hit[0]["bridge_task"] == "survival prediction"
    assert hit[0]["bridge_quality"] == "ok"
    assert hit[0]["bridge_mode"] == "cross_paper"
    assert "disease-a" in hit[0]["support_diseases"]
