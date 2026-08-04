"""Weekly hotspot payload includes method_role without changing maturity gates."""
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
from db.schema import get_conn, init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)
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


def _edge(pmid: str, paper_id: int, name: str) -> None:
    entity_id = upsert_entity(name, "Method")
    insert_relation(
        "Paper", paper_id, "APPLIES_METHOD", "Method", entity_id,
        source_pmid=pmid, status="active",
    )


def _related_edge(
    pmid: str,
    paper_id: int,
    relation: str,
    name: str,
    entity_type: str,
) -> None:
    entity_id = upsert_entity(name, entity_type)
    insert_relation(
        "Paper", paper_id, relation, entity_type, entity_id,
        source_pmid=pmid, status="active",
    )


def test_emerging_and_active_have_method_role(monkeypatch):
    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 2)
    for i, pmid in enumerate(("1", "2"), start=1):
        pid = _paper(pmid, i)
        _edge(pmid, pid, "niche-mil-aggregator-x")
        _related_edge(pmid, pid, "TARGETS_DISEASE", "disease-a", "Disease")
    for i, pmid in enumerate(("3", "4"), start=1):
        pid = _paper(pmid, i + 2)
        _edge(pmid, pid, "resnet-50")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    emerging = {r["name"]: r for r in payload["emerging_methods"]}
    active = {r["name"]: r for r in payload["active_methods"]}

    assert emerging["niche-mil-aggregator-x"]["method_role"] == "aggregator"
    assert active["resnet-50"]["method_role"] == "backbone"
    # resnet-50 is established blacklist → excluded from emerging
    assert "resnet-50" not in emerging
    assert "resnet-50" in active
    assert payload.get("hot_combos")
    assert payload.get("hot_combos_by_method")
    for row in payload.get("hot_combos") or []:
        assert row.get("method_role") in {"backbone", "aggregator", "unknown"}
    for row in payload.get("hot_combos_by_method") or []:
        assert row.get("method_role") in {"backbone", "aggregator", "unknown"}


def test_emerging_gap_opportunity_has_method_role(monkeypatch):
    _tmp_db(monkeypatch)
    method = "niche-mil-aggregator-x"
    support_paper = _paper("support", 2)
    _edge("support", support_paper, method)
    _related_edge(
        "support", support_paper, "TARGETS_DISEASE", "disease-a", "Disease"
    )
    _related_edge(
        "support", support_paper, "PERFORMS_TASK", "survival prediction", "Task"
    )
    target_paper = _paper("target", 3)
    _related_edge(
        "target", target_paper, "TARGETS_DISEASE", "disease-b", "Disease"
    )
    _related_edge(
        "target", target_paper, "PERFORMS_TASK", "survival prediction", "Task"
    )
    payload = {
        "emerging_methods": [{
            "name": method,
            "method_maturity": "nascent",
            "corpus_paper_cnt": 1,
            "recent_cnt": 1,
            "velocity": 1.0,
            "emerging_score": 1.0,
        }],
        "active_methods": [],
        "heating_diseases": [{"name": "disease-b"}],
    }

    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)

    assert rows
    assert rows[0]["method_role"] == "aggregator"
