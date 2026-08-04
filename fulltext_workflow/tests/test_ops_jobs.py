"""Tests for weekly ops job status + runner."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis import ops_jobs as oj  # noqa: E402


def _tmp_jobs(monkeypatch):
    td = Path(tempfile.mkdtemp())
    monkeypatch.setattr(oj, "OPS_JOBS_DIR", td / "ops_jobs")
    return td


def test_create_weekly_job_writes_status(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job(since_days=7, extract_limit=3, skip_enrich=True)
    assert job["kind"] == "weekly"
    assert job["state"] == "pending"
    assert len(job["steps"]) == 10
    assert job["params"]["skip_enrich"] is True
    loaded = oj.read_status(job["job_id"])
    assert loaded["job_id"] == job["job_id"]
    cur = oj.read_current()
    assert cur["job_id"] == job["job_id"]


def test_build_weekly_argv_skip_enrich(monkeypatch):
    _tmp_jobs(monkeypatch)
    params = {"since_days": 14, "extract_limit": 0, "skip_enrich": True}
    assert oj.build_weekly_argv("enrich-s2", params) is None
    fetch = oj.build_weekly_argv("fetch", params)
    assert fetch[:2] == ["fetch", "--since-days"]
    assert "14" in fetch
    ext = oj.build_weekly_argv("extract", {"since_days": 14, "extract_limit": 5, "skip_enrich": False})
    assert ext == ["extract", "--limit", "5", "--core-only"]


def test_tail_log_and_progress(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    oj.append_log(job["job_id"], "a\nb\nc\n")
    assert oj.tail_log(job["job_id"], max_lines=2) == "b\nc"
    job["steps"][0]["status"] = "succeeded"
    job["steps"][1]["status"] = "skipped"
    done, total = oj.progress_counts(job)
    assert (done, total) == (2, 10)


def test_run_weekly_job_skips_enrich_and_succeeds(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job(skip_enrich=True)
    calls: list[list[str]] = []

    def fake_run(argv, log_fh):
        calls.append(list(argv))
        log_fh.write(f"ok {' '.join(argv)}\n")
        return 0

    result = oj.run_weekly_job(job["job_id"], run_step_fn=fake_run)
    assert result["state"] == "succeeded"
    assert all(c[0] != "enrich-s2" for c in calls)
    enrich = next(s for s in result["steps"] if s["id"] == "enrich-s2")
    assert enrich["status"] == "skipped"
    assert calls[0][0] == "fetch"


def test_run_weekly_job_stops_on_failure(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job(skip_enrich=True)

    def fake_run(argv, log_fh):
        if argv[0] == "fetch-fulltext":
            log_fh.write("boom\n")
            return 2
        return 0

    result = oj.run_weekly_job(job["job_id"], run_step_fn=fake_run)
    assert result["state"] == "failed"
    ft = next(s for s in result["steps"] if s["id"] == "fetch-fulltext")
    assert ft["status"] == "failed"
    later = next(s for s in result["steps"] if s["id"] == "build")
    assert later["status"] == "pending"
