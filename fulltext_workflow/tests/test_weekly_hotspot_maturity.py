"""Emerging method board excludes established baselines."""
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
    compute_weekly_hotspots,
    generate_hotspot_report,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


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


def test_llm_excluded_from_emerging_but_in_active(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = _paper("1", 2)
    _edge("1", p1, "APPLIES_METHOD", "large language model", "Method")
    _edge("1", p1, "TARGETS_DISEASE", "disease-a", "Disease")
    p2 = _paper("2", 3)
    _edge("2", p2, "APPLIES_METHOD", "niche-new-method", "Method")
    _edge("2", p2, "TARGETS_DISEASE", "disease-a", "Disease")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    emerging_names = {r["name"] for r in payload["emerging_methods"]}
    active_names = {r["name"] for r in payload["active_methods"]}

    assert "large language model" not in emerging_names
    assert "niche-new-method" in emerging_names
    assert "large language model" in active_names
    llm_row = next(r for r in payload["active_methods"] if r["name"] == "large language model")
    assert llm_row["method_maturity"] == "established"
    niche = next(r for r in payload["emerging_methods"] if r["name"] == "niche-new-method")
    assert niche["method_maturity"] == "nascent"


def test_report_labels_new_methods_and_lists_established(monkeypatch):
    _tmp_db(monkeypatch)
    paper_id = _paper("1", 2)
    _edge("1", paper_id, "APPLIES_METHOD", "large language model", "Method")
    _edge("1", paper_id, "TARGETS_DISEASE", "disease-a", "Disease")

    report = generate_hotspot_report(
        compute_weekly_hotspots(window_days=14, prior_days=14),
        wow={"has_baseline": False, "previous_week_id": "2026-W01", "boards": {}},
    )

    assert "## Emerging Methods (新苗头)" in report
    assert "### Established Methods (active this window)" in report
    assert "- large language model (corpus papers: 1)" in report
