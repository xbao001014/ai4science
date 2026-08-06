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
    cooldown_days_for_pdf_attempts,
    get_conn,
    init_db,
    increment_fulltext_pdf_attempts,
    mark_fulltext_status,
    repair_misclassified_unavailable_without_pdf_attempt,
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


def test_requeue_resets_only_cooled_unavailable(monkeypatch):
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
    assert n == 1
    with get_conn() as conn:
        rows = {
            r["pmid"]: r["full_text_status"]
            for r in conn.execute(
                "SELECT pmid, full_text_status FROM papers"
            ).fetchall()
        }
    assert rows["1"] == "pending"
    assert rows["2"] == "jats_unavailable"
    assert rows["3"] == "available"


def test_cooldown_days_schedule():
    assert cooldown_days_for_pdf_attempts(0) == 7
    assert cooldown_days_for_pdf_attempts(1) == 7
    assert cooldown_days_for_pdf_attempts(2) == 14
    assert cooldown_days_for_pdf_attempts(3) == 28
    assert cooldown_days_for_pdf_attempts(4) == 56
    assert cooldown_days_for_pdf_attempts(9) == 56


def test_requeue_escalating_cooldown_by_attempts(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "1", "title": "A", "year": 2025})
    p2 = upsert_paper({"pmid": "2", "title": "B", "year": 2024})
    mark_fulltext_status(p1, "unavailable")
    mark_fulltext_status(p2, "unavailable")
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=1 WHERE id=?", (p1,)
        )
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=2 WHERE id=?", (p2,)
        )
    _set_fetched_at(p1, 8)   # needs 7 → eligible
    _set_fetched_at(p2, 8)   # needs 14 → not eligible
    n = requeue_cooled_fulltext_failures(cooldown_days=7, force=False)
    assert n == 1
    with get_conn() as conn:
        rows = {
            r["pmid"]: r["full_text_status"]
            for r in conn.execute("SELECT pmid, full_text_status FROM papers")
        }
    assert rows["1"] == "pending"
    assert rows["2"] == "unavailable"


def test_repair_misclassified_unavailable(monkeypatch):
    _tmp_db(monkeypatch)
    p0 = upsert_paper({"pmid": "10", "title": "Z", "year": 2025})
    p1 = upsert_paper({"pmid": "11", "title": "Y", "year": 2024})
    mark_fulltext_status(p0, "unavailable")
    mark_fulltext_status(p1, "unavailable")
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=0 WHERE id=?", (p0,)
        )
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=2 WHERE id=?", (p1,)
        )
    n = repair_misclassified_unavailable_without_pdf_attempt()
    assert n == 1
    with get_conn() as conn:
        rows = {
            r["pmid"]: (r["full_text_status"], r["fulltext_pdf_attempts"])
            for r in conn.execute(
                "SELECT pmid, full_text_status, fulltext_pdf_attempts FROM papers"
            )
        }
    assert rows["10"] == ("jats_unavailable", 0)
    assert rows["11"][0] == "unavailable"


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


def test_pdf_fallback_limit_leaves_untried_as_jats_unavailable(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    # attempts=1 older year should still sort after attempts=0
    for i, (year, attempts) in enumerate(
        ((2025, 1), (2024, 0), (2023, 0)), start=1
    ):
        pid = upsert_paper(
            {
                "pmid": str(i),
                "doi": f"10.1/{i}",
                "title": f"T{i}",
                "year": year,
            }
        )
        mark_fulltext_status(pid, "jats_unavailable")
        with get_conn() as conn:
            conn.execute(
                "UPDATE papers SET fulltext_pdf_attempts=? WHERE id=?",
                (attempts, pid),
            )

    calls: list[str] = []

    def fake_download(doi, pmid):
        calls.append(pmid)
        return {"success": False}

    monkeypatch.setattr(ff, "download_pdf", fake_download)
    monkeypatch.setattr(ff, "pdf_to_sections", lambda *a, **k: [])

    ok = ff.fetch_pdf_mineru_fallback(limit=2)
    assert ok == 0
    # never-tried first (pmid 2 year 2024, pmid 3 year 2023), then attempted
    assert calls == ["2", "3"]

    with get_conn() as conn:
        rows = {
            r["pmid"]: (r["full_text_status"], r["fulltext_pdf_attempts"])
            for r in conn.execute(
                "SELECT pmid, full_text_status, fulltext_pdf_attempts FROM papers"
            )
        }
    assert rows["2"][0] == "unavailable" and rows["2"][1] == 1
    assert rows["3"][0] == "unavailable" and rows["3"][1] == 1
    assert rows["1"] == ("jats_unavailable", 1)  # not attempted this run


def test_fetch_all_does_not_finalize_deferred(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {"pmid": "50", "doi": "10.1/50", "title": "T", "year": 2025}
    )
    mark_fulltext_status(pid, "jats_unavailable")
    monkeypatch.setattr(ff, "fetch_jats_fulltext", lambda cache_xml=True: None)
    monkeypatch.setattr(ff, "fetch_pdf_mineru_fallback", lambda limit=None: 0)
    monkeypatch.setattr(
        ff, "repair_misclassified_unavailable_without_pdf_attempt", lambda: 0
    )

    stats = ff.fetch_all_fulltext(retry=False, pdf_retry_limit=0)
    assert stats.get("pdf_deferred", 0) >= 1
    with get_conn() as conn:
        st = conn.execute(
            "SELECT full_text_status FROM papers WHERE id=?", (pid,)
        ).fetchone()[0]
    assert st == "jats_unavailable"


def test_fetch_all_fulltext_no_retry_skips_requeue(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "77", "title": "X", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 30)
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=1 WHERE id=?", (pid,)
        )

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
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=1 WHERE id=?", (pid,)
        )

    monkeypatch.setattr(ff, "fetch_jats_fulltext", lambda cache_xml=True: None)
    monkeypatch.setattr(ff, "fetch_pdf_mineru_fallback", lambda limit=None: 0)

    stats = ff.fetch_all_fulltext(retry=True, force_retry=False)
    assert stats["retried_into_pending"] == 1
