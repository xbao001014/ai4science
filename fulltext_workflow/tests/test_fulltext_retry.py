"""Tests for fulltext cooldown requeue and PDF retry limit."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    get_conn,
    init_db,
    mark_fulltext_status,
    requeue_cooled_fulltext_failures,
    upsert_paper,
)


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def _set_fetched_at(paper_id: int, days_ago: float) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE papers SET full_text_fetched_at =
                   datetime('now', ?) WHERE id=?""",
            (f"-{days_ago} days", paper_id),
        )


def test_requeue_skips_fresh_unavailable(monkeypatch):
    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "1", "title": "A", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 2)
    n = requeue_cooled_fulltext_failures(cooldown_days=7, force=False)
    assert n == 0
    with get_conn() as conn:
        st = conn.execute(
            "SELECT full_text_status FROM papers WHERE id=?", (pid,)
        ).fetchone()[0]
    assert st == "unavailable"


def test_requeue_resets_cooled_unavailable_and_jats(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "1", "title": "A", "year": 2025})
    p2 = upsert_paper({"pmid": "2", "title": "B", "year": 2024})
    p3 = upsert_paper({"pmid": "3", "title": "C", "year": 2023})
    mark_fulltext_status(p1, "unavailable")
    mark_fulltext_status(p2, "jats_unavailable")
    mark_fulltext_status(p3, "available")
    _set_fetched_at(p1, 8)
    _set_fetched_at(p2, 8)
    _set_fetched_at(p3, 8)
    n = requeue_cooled_fulltext_failures(cooldown_days=7, force=False)
    assert n == 2
    with get_conn() as conn:
        rows = {
            r["pmid"]: r["full_text_status"]
            for r in conn.execute(
                "SELECT pmid, full_text_status FROM papers"
            ).fetchall()
        }
    assert rows["1"] == "pending"
    assert rows["2"] == "pending"
    assert rows["3"] == "available"


def test_force_requeue_ignores_cooldown(monkeypatch):
    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "9", "title": "F", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 0.1)
    n = requeue_cooled_fulltext_failures(cooldown_days=7, force=True)
    assert n == 1
    with get_conn() as conn:
        st = conn.execute(
            "SELECT full_text_status FROM papers WHERE id=?", (pid,)
        ).fetchone()[0]
    assert st == "pending"
