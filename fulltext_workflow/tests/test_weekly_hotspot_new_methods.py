"""Independent 本周新方法 board (nascent, min_recent=1, no Top-N)."""
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
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 2)
    monkeypatch.setattr(config, "HOTSPOT_ESTABLISHED_MIN_PAPERS", 10)
    monkeypatch.setattr(config, "HOTSPOT_TOP_N", 2)
    monkeypatch.setattr(config, "HOTSPOT_NEW_METHODS_MAX", 500)
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


def _edge(pmid: str, paper_id: int, name: str) -> None:
    entity_id = upsert_entity(name, "Method")
    insert_relation(
        "Paper",
        paper_id,
        "APPLIES_METHOD",
        "Method",
        entity_id,
        source_pmid=pmid,
        status="active",
    )


def test_nascent_in_new_methods_established_and_emerging_out(monkeypatch):
    _tmp_db(monkeypatch)
    # nascent: 1 recent paper
    p_new = _paper("new-1", 2)
    _edge("new-1", p_new, "brand-new-niche-method")

    # established blacklist
    p_llm = _paper("llm-1", 2)
    _edge("llm-1", p_llm, "large language model")

    # emerging: 5 corpus papers, 1 in recent window (others older than window)
    for i in range(4):
        pmid = f"em-old-{i}"
        pid = _paper(pmid, 40 + i)
        _edge(pmid, pid, "mid-frequency-method")
    p_em = _paper("em-recent", 3)
    _edge("em-recent", p_em, "mid-frequency-method")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14, min_recent=2)
    names = {r["name"] for r in payload["new_methods"]}
    assert "brand-new-niche-method" in names
    assert "large language model" not in names
    assert "mid-frequency-method" not in names
    row = next(r for r in payload["new_methods"] if r["name"] == "brand-new-niche-method")
    assert row["method_maturity"] == "nascent"
    assert int(row["recent_cnt"]) == 1


def test_new_methods_ignores_sidebar_min_recent_and_top_n(monkeypatch):
    _tmp_db(monkeypatch)
    # Fill heat board with two count=2 established-ish high scorers
    for name, base in (("heat-a", 10), ("heat-b", 20)):
        for j in range(2):
            pmid = f"{name}-{j}"
            pid = _paper(pmid, 2 + j)
            _edge(pmid, pid, name)

    # Single-paper nascent — filtered from emerging when min_recent=2 / Top-N=2
    p = _paper("solo-nascent", 2)
    _edge("solo-nascent", p, "solo-nascent-method")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14, min_recent=2)
    emerging = {r["name"] for r in payload["emerging_methods"]}
    new_names = {r["name"] for r in payload["new_methods"]}
    assert "solo-nascent-method" in new_names
    assert "solo-nascent-method" not in emerging


def test_new_methods_sorted_by_corpus_then_score(monkeypatch):
    _tmp_db(monkeypatch)
    # corpus_paper_cnt=1
    p1 = _paper("c1", 2)
    _edge("c1", p1, "alpha-one-paper")
    # corpus_paper_cnt=2 (one older outside window still counts for corpus)
    p_old = _paper("c2-old", 40)
    _edge("c2-old", p_old, "beta-two-paper")
    p_new = _paper("c2-new", 2)
    _edge("c2-new", p_new, "beta-two-paper")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14, min_recent=1)
    names = [r["name"] for r in payload["new_methods"]]
    assert names.index("alpha-one-paper") < names.index("beta-two-paper")


def test_report_includes_new_methods_section(monkeypatch):
    _tmp_db(monkeypatch)
    p = _paper("1", 2)
    _edge("1", p, "report-niche-method")
    report = generate_hotspot_report(
        compute_weekly_hotspots(window_days=14, prior_days=14, min_recent=1),
        wow={"has_baseline": False, "previous_week_id": "2026-W01", "boards": {}},
    )
    assert "## New Methods This Window (本周新方法)" in report
    assert "report-niche-method" in report
