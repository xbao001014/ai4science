"""Weekly hotspot windows use pub_date + date_precision (not created_at)."""
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
    compute_emerging_entities,
    compute_emerging_limitations,
    compute_weekly_hotspots,
    count_window_papers,
)
from db.schema import get_conn, init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def _iso(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d")


def _add_paper(
    *,
    pmid: str,
    title: str,
    pub_days_ago: int,
    precision: str,
    created_days_ago: int | None = None,
) -> int:
    pid = upsert_paper(
        {
            "pmid": pmid,
            "title": title,
            "pub_date": _iso(pub_days_ago),
            "year": int(_iso(pub_days_ago)[:4]),
            "date_precision": precision,
        }
    )
    if created_days_ago is not None:
        # Force created_at independent of pub_date (SQLite localtime).
        created = (
            datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        ).strftime("%Y-%m-%d %H:%M:%S")
        with get_conn() as conn:
            conn.execute(
                "UPDATE papers SET created_at=? WHERE id=?", (created, pid)
            )
    return pid


def _link_method(pmid: str, paper_id: int, method: str) -> None:
    eid = upsert_entity(method, "Method")
    insert_relation(
        "Paper",
        paper_id,
        "APPLIES_METHOD",
        "Method",
        eid,
        source_pmid=pmid,
        extraction_granularity="fulltext",
    )


def test_window_counts_pub_date_not_created_at(monkeypatch):
    _tmp_db(monkeypatch)
    # Published recently, ingested long ago → should count
    _add_paper(
        pmid="1",
        title="recent pub",
        pub_days_ago=3,
        precision="day",
        created_days_ago=400,
    )
    # Published long ago, ingested yesterday → must NOT count
    _add_paper(
        pmid="2",
        title="old pub new ingest",
        pub_days_ago=400,
        precision="day",
        created_days_ago=1,
    )
    assert count_window_papers(14) == 1


def test_year_precision_excluded_from_window(monkeypatch):
    _tmp_db(monkeypatch)
    _add_paper(pmid="10", title="day", pub_days_ago=2, precision="day")
    _add_paper(pmid="11", title="month", pub_days_ago=2, precision="month")
    _add_paper(pmid="12", title="year only", pub_days_ago=2, precision="year")
    _add_paper(pmid="13", title="unknown", pub_days_ago=2, precision="unknown")
    assert count_window_papers(14) == 2


def test_emerging_entities_use_pub_date_window(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = _add_paper(
        pmid="21",
        title="hot method paper",
        pub_days_ago=5,
        precision="day",
        created_days_ago=400,
    )
    _link_method("21", p1, "Vision Transformer")
    p2 = _add_paper(
        pmid="22",
        title="stale method via ingest",
        pub_days_ago=400,
        precision="day",
        created_days_ago=1,
    )
    _link_method("22", p2, "Legacy CNN")

    rows = compute_emerging_entities(
        "Method", window_days=14, prior_days=14, min_recent=1, limit=20
    )
    names = {r["name"] for r in rows}
    assert "vision transformer" in names
    assert "legacy cnn" not in names


def test_payload_reports_pub_date_axis(monkeypatch):
    _tmp_db(monkeypatch)
    _add_paper(pmid="31", title="a", pub_days_ago=1, precision="day")
    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    assert payload.get("time_axis") == "pub_date"
    assert payload.get("eligible_precision") == ["day", "month"]
    assert "papers_ingested" in payload  # persisted field kept
    assert payload["papers_ingested"] == payload.get("papers_in_window")


def test_limitations_follow_pub_date(monkeypatch):
    _tmp_db(monkeypatch)
    pid = _add_paper(
        pmid="41",
        title="lim paper",
        pub_days_ago=4,
        precision="month",
        created_days_ago=300,
    )
    lid = upsert_entity("small cohort", "Limitation")
    insert_relation(
        "Paper",
        pid,
        "REPORTS_LIMITATION",
        "Limitation",
        lid,
        source_pmid="41",
        extraction_granularity="fulltext",
    )
    rows = compute_emerging_limitations(window_days=14, limit=10)
    assert any(r["limitation"] == "small cohort" for r in rows)
