"""Tests for papers.date_precision persistence via upsert_paper."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import get_conn, init_db, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_upsert_inserts_date_precision(monkeypatch):
    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {
            "pmid": "1001",
            "title": "Day precision paper",
            "pub_date": "2020-09-18",
            "year": 2020,
            "date_precision": "day",
        }
    )
    with get_conn() as conn:
        row = conn.execute(
            "SELECT date_precision, pub_date, year FROM papers WHERE id=?", (pid,)
        ).fetchone()
    assert row["date_precision"] == "day"
    assert row["pub_date"] == "2020-09-18"
    assert row["year"] == 2020


def test_upsert_backfills_missing_date_precision(monkeypatch):
    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {
            "pmid": "1002",
            "title": "Legacy paper",
            "pub_date": "2019-01-01",
            "year": 2019,
        }
    )
    with get_conn() as conn:
        conn.execute("UPDATE papers SET date_precision=NULL WHERE id=?", (pid,))

    upsert_paper(
        {
            "pmid": "1002",
            "title": "Legacy paper",
            "pub_date": "2019-12-01",
            "year": 2019,
            "date_precision": "month",
            "abstract": "updated abstract",
        }
    )
    with get_conn() as conn:
        row = conn.execute(
            "SELECT date_precision, pub_date, abstract FROM papers WHERE id=?", (pid,)
        ).fetchone()
    assert row["date_precision"] == "month"
    assert row["pub_date"] == "2019-12-01"
    assert "updated" in (row["abstract"] or "")


def test_upsert_does_not_overwrite_existing_precision(monkeypatch):
    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {
            "pmid": "1003",
            "title": "Already precise",
            "pub_date": "2021-05-15",
            "year": 2021,
            "date_precision": "day",
        }
    )
    upsert_paper(
        {
            "pmid": "1003",
            "title": "Already precise",
            "pub_date": "2021-01-01",
            "year": 2021,
            "date_precision": "year",
        }
    )
    with get_conn() as conn:
        row = conn.execute(
            "SELECT date_precision, pub_date FROM papers WHERE id=?", (pid,)
        ).fetchone()
    assert row["date_precision"] == "day"
    assert row["pub_date"] == "2021-05-15"
