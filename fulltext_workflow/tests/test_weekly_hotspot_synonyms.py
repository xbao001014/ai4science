"""Canonical method aggregation for weekly hotspots."""
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
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 2)
    monkeypatch.setattr(config, "HOTSPOT_ESTABLISHED_MIN_PAPERS", 10)
    init_db()
    return path


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _paper(pmid: str, days_ago: int) -> int:
    return upsert_paper({
        "pmid": pmid,
        "title": pmid,
        "pub_date": _iso(days_ago),
        "year": int(_iso(days_ago)[:4]),
        "date_precision": "day",
        "extraction_done": 1,
    })


def _edge(pmid: str, paper_id: int, relation: str, name: str, entity_type: str) -> None:
    entity_id = upsert_entity(name, entity_type)
    insert_relation(
        "Paper", paper_id, relation, entity_type, entity_id,
        source_pmid=pmid, status="active",
    )


def test_two_aliases_merge_to_pass_min_recent(monkeypatch):
    _tmp_db(monkeypatch)
    import analysis.method_synonyms as ms

    monkeypatch.setitem(ms._METHOD_SYNONYMS, "niche-tool-v2", "niche-tool")
    p1 = _paper("1", 2)
    _edge("1", p1, "APPLIES_METHOD", "niche-tool", "Method")
    p2 = _paper("2", 3)
    _edge("2", p2, "APPLIES_METHOD", "niche-tool-v2", "Method")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    emerging = {r["name"]: r for r in payload["emerging_methods"]}

    assert "niche-tool" in emerging
    assert emerging["niche-tool"]["recent_cnt"] == 2
    assert emerging["niche-tool"]["corpus_paper_cnt"] == 2
    assert emerging["niche-tool"]["alias_count"] == 2
    assert emerging["niche-tool"]["aliases"] == "niche-tool, niche-tool-v2"


def test_transfer_pairing_resolves_hot_and_edge_method_aliases(monkeypatch):
    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)
    import analysis.method_synonyms as ms

    monkeypatch.setitem(ms._METHOD_SYNONYMS, "niche-tool-v2", "niche-tool")
    p1 = _paper("1", 2)
    _edge("1", p1, "APPLIES_METHOD", "niche-tool-v2", "Method")
    _edge("1", p1, "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("1", p1, "PERFORMS_TASK", "survival prediction", "Task")
    p2 = _paper("2", 3)
    _edge("2", p2, "APPLIES_METHOD", "niche-tool", "Method")
    _edge("2", p2, "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("2", p2, "PERFORMS_TASK", "survival prediction", "Task")
    p3 = _paper("3", 4)
    _edge("3", p3, "TARGETS_DISEASE", "disease-b", "Disease")
    _edge("3", p3, "PERFORMS_TASK", "survival prediction", "Task")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    hit = next(
        row for row in rows
        if row["method"] == "niche-tool" and row["disease"] == "disease-b"
    )

    assert hit["literature_paper_cnt"] == 0
