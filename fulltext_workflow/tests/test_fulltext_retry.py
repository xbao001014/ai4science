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


def test_pdf_fallback_respects_limit_and_marks_rest_unavailable(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    for i, year in enumerate((2025, 2024, 2023), start=1):
        pid = upsert_paper(
            {
                "pmid": str(i),
                "doi": f"10.1/{i}",
                "title": f"T{i}",
                "year": year,
            }
        )
        mark_fulltext_status(pid, "jats_unavailable")

    calls: list[str] = []

    def fake_download(doi, pmid):
        calls.append(pmid)
        return {"success": False}

    monkeypatch.setattr(ff, "download_pdf", fake_download)
    monkeypatch.setattr(ff, "pdf_to_sections", lambda *a, **k: [])

    ok = ff.fetch_pdf_mineru_fallback(limit=2)
    assert ok == 0
    assert calls == ["1", "2"]  # newest year first

    with get_conn() as conn:
        skipped = conn.execute(
            """SELECT COUNT(*) FROM papers
               WHERE full_text_status='jats_unavailable'"""
        ).fetchone()[0]
    assert skipped == 1  # pmid 3 not attempted

    n_skip = ff.finalize_jats_unavailable_as_unavailable()
    assert n_skip == 1
    with get_conn() as conn:
        rows = {
            r["pmid"]: (r["full_text_status"], r["full_text_fetched_at"] is not None)
            for r in conn.execute(
                "SELECT pmid, full_text_status, full_text_fetched_at FROM papers"
            )
        }
    assert rows["1"][0] == "unavailable"
    assert rows["2"][0] == "unavailable"
    assert rows["3"][0] == "unavailable"
    assert all(v[1] for v in rows.values())


def test_fetch_all_fulltext_no_retry_skips_requeue(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "77", "title": "X", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 30)

    monkeypatch.setattr(ff, "fetch_jats_fulltext", lambda cache_xml=True: None)
    monkeypatch.setattr(ff, "fetch_pdf_mineru_fallback", lambda limit=None: 0)

    stats = ff.fetch_all_fulltext(retry=False)
    assert stats["retried_into_pending"] == 0
    with get_conn() as conn:
        st = conn.execute(
            "SELECT full_text_status FROM papers WHERE id=?", (pid,)
        ).fetchone()[0]
    assert st == "unavailable"


def test_fetch_all_fulltext_rejects_negative_pdf_retry_limit(monkeypatch):
    import pytest

    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    monkeypatch.setattr(ff, "fetch_jats_fulltext", lambda cache_xml=True: None)
    monkeypatch.setattr(ff, "fetch_pdf_mineru_fallback", lambda limit=None: 0)

    with pytest.raises(ValueError, match="pdf_retry_limit must be >= 0"):
        ff.fetch_all_fulltext(retry=False, pdf_retry_limit=-1)


def test_fetch_all_fulltext_default_requeues(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "88", "title": "Y", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 30)

    monkeypatch.setattr(ff, "fetch_jats_fulltext", lambda cache_xml=True: None)
    monkeypatch.setattr(ff, "fetch_pdf_mineru_fallback", lambda limit=None: 0)

    stats = ff.fetch_all_fulltext(retry=True, force_retry=False)
    assert stats["retried_into_pending"] == 1
