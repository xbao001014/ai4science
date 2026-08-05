"""Tests for weekly ops job status + runner."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

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
    assert ext == ["extract", "--limit", "5", "--core-only", "--no-upgrade-reextract"]


def test_build_weekly_argv_fetch_fulltext_unchanged():
    params = {"since_days": 14, "extract_limit": 0, "skip_enrich": False}
    assert oj.build_weekly_argv("fetch-fulltext", params) == ["fetch-fulltext"]


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


def test_start_rejects_second_running(monkeypatch):
    _tmp_jobs(monkeypatch)
    spawned = []

    def spawn(job_id):
        spawned.append(job_id)
        return 4242

    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: True)
    j1 = oj.start_weekly_job(spawn_fn=spawn, skip_enrich=True)
    # Simulate runner marked running with alive pid
    j1["state"] = "running"
    j1["pid"] = 4242
    oj.write_status(j1)
    oj.write_current(j1["job_id"], "running")
    try:
        oj.start_weekly_job(spawn_fn=spawn)
        assert False, "expected OpsJobError"
    except oj.OpsJobError:
        pass
    assert len(spawned) == 1


def test_reclaim_zombie(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "running"
    job["pid"] = 999001
    oj.write_status(job)
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: False)
    out = oj.reclaim_zombie(oj.read_status(job["job_id"]))
    assert out["state"] == "failed"
    assert "exited" in (out.get("error") or "").lower()


def test_reclaim_zombie_handles_dead_pending(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["pid"] = 999003
    oj.write_status(job)
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: False)
    out = oj.reclaim_zombie(oj.read_status(job["job_id"]))
    assert out["state"] == "failed"
    assert "start" in (out.get("error") or "").lower()


def test_start_weekly_job_marks_failed_on_spawn_exception(monkeypatch):
    _tmp_jobs(monkeypatch)

    def bad_spawn(job_id):
        raise OSError("spawn failed")

    try:
        oj.start_weekly_job(spawn_fn=bad_spawn)
        assert False, "expected OpsJobError"
    except oj.OpsJobError as exc:
        assert "failed to start" in str(exc).lower()

    current = oj.read_current()
    assert current["state"] == "failed"
    job = oj.read_status(current["job_id"])
    assert job["state"] == "failed"
    assert "spawn failed" in (job.get("error") or "")

    # Failed spawn must not block a subsequent start.
    active = oj.get_active_weekly_job()
    assert active is None or active.get("state") != "running"


def test_get_active_weekly_job_reclaims_dead_pending(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["pid"] = 999004
    oj.write_status(job)
    oj.write_current(job["job_id"], "pending")
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: False)
    out = oj.get_active_weekly_job()
    assert out["state"] == "failed"


def test_start_weekly_job_not_blocked_by_stale_pending(monkeypatch):
    _tmp_jobs(monkeypatch)
    stuck = oj.create_weekly_job()
    stuck["pid"] = 999005
    oj.write_status(stuck)
    oj.write_current(stuck["job_id"], "pending")
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: False)

    spawned = []

    def spawn(job_id):
        spawned.append(job_id)
        return 4343

    job = oj.start_weekly_job(spawn_fn=spawn, skip_enrich=True)
    assert job["state"] == "pending"
    assert spawned == [job["job_id"]]


def test_cancel_marks_cancelled(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "running"
    job["pid"] = 777
    job["steps"][0]["status"] = "running"
    oj.write_status(job)
    oj.write_current(job["job_id"], "running")
    killed = []

    def fake_kill(pid):
        killed.append(pid)
        return True

    monkeypatch.setattr(oj, "_kill_process_tree", fake_kill)
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: True)
    monkeypatch.setattr(oj, "_pid_looks_like_runner", lambda pid, job_id: True)
    out = oj.cancel_weekly_job(job["job_id"])
    assert out["state"] == "cancelled"
    assert out["steps"][0]["status"] == "cancelled"
    assert killed == [777]


def test_cancel_reclaims_when_pid_already_dead(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "running"
    job["pid"] = 888
    job["steps"][0]["status"] = "running"
    oj.write_status(job)
    oj.write_current(job["job_id"], "running")

    killed = []
    monkeypatch.setattr(oj, "_kill_process_tree", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: False)

    out = oj.cancel_weekly_job(job["job_id"])
    assert out["state"] == "failed"
    assert killed == []
    assert out["steps"][0]["status"] == "failed"


def test_cancel_refuses_when_pid_does_not_look_like_runner(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "running"
    job["pid"] = 999
    job["steps"][0]["status"] = "running"
    oj.write_status(job)
    oj.write_current(job["job_id"], "running")

    killed = []
    monkeypatch.setattr(oj, "_kill_process_tree", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: True)
    monkeypatch.setattr(oj, "_pid_looks_like_runner", lambda pid, job_id: False)

    try:
        oj.cancel_weekly_job(job["job_id"])
        assert False, "expected OpsJobError"
    except oj.OpsJobError as exc:
        assert "pid reuse" in str(exc).lower() or "does not" in str(exc).lower() or "no longer" in str(exc).lower()
    assert killed == []
    loaded = oj.read_status(job["job_id"])
    assert loaded["state"] == "running"


def test_cancel_raises_when_kill_fails(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "running"
    job["pid"] = 1010
    job["steps"][0]["status"] = "running"
    oj.write_status(job)
    oj.write_current(job["job_id"], "running")

    monkeypatch.setattr(oj, "_kill_process_tree", lambda pid: False)
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: True)
    monkeypatch.setattr(oj, "_pid_looks_like_runner", lambda pid, job_id: True)

    try:
        oj.cancel_weekly_job(job["job_id"])
        assert False, "expected OpsJobError"
    except oj.OpsJobError as exc:
        assert "failed to kill" in str(exc).lower()
    loaded = oj.read_status(job["job_id"])
    assert loaded["state"] == "running"


def test_get_active_weekly_job_reclaims_zombie(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "running"
    job["pid"] = 999002
    oj.write_status(job)
    oj.write_current(job["job_id"], "running")
    monkeypatch.setattr(oj, "pid_is_alive", lambda pid: False)
    out = oj.get_active_weekly_job()
    assert out["state"] == "failed"
    assert "exited" in (out.get("error") or "").lower()


def test_get_active_weekly_job_none_when_no_current(monkeypatch):
    _tmp_jobs(monkeypatch)
    assert oj.get_active_weekly_job() is None


def test_cancel_rejects_pending_job(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    assert job["state"] == "pending"
    try:
        oj.cancel_weekly_job(job["job_id"])
        assert False, "expected OpsJobError"
    except oj.OpsJobError as exc:
        assert "not running" in str(exc).lower()
    loaded = oj.read_status(job["job_id"])
    assert loaded["state"] == "pending"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only pid-reuse guard")
def test_pid_looks_like_runner_matches_and_rejects(monkeypatch):
    monkeypatch.setattr(
        oj,
        "_pid_command_line",
        lambda pid: r'"C:\Python\python.exe" -m analysis.ops_jobs --run-job 20260101T000000Z_weekly',
    )
    assert oj._pid_looks_like_runner(123, "20260101T000000Z_weekly") is True

    monkeypatch.setattr(oj, "_pid_command_line", lambda pid: r"C:\Windows\System32\notepad.exe")
    assert oj._pid_looks_like_runner(123, "20260101T000000Z_weekly") is False

    monkeypatch.setattr(oj, "_pid_command_line", lambda pid: "")
    assert oj._pid_looks_like_runner(123, "20260101T000000Z_weekly") is True


def test_cancel_rejects_succeeded_job(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job()
    job["state"] = "succeeded"
    job["finished_at"] = "2026-01-01T00:00:00Z"
    oj.write_status(job)
    oj.write_current(job["job_id"], "succeeded")
    try:
        oj.cancel_weekly_job(job["job_id"])
        assert False, "expected OpsJobError"
    except oj.OpsJobError as exc:
        assert "not running" in str(exc).lower()
    loaded = oj.read_status(job["job_id"])
    assert loaded["state"] == "succeeded"


def test_build_weekly_argv_upgrade_flags():
    base = {"since_days": 14, "extract_limit": 0, "skip_enrich": False}
    off = oj.build_weekly_argv("extract", {**base, "upgrade_abstract_fulltext": False})
    assert off == [
        "extract",
        "--limit",
        "0",
        "--core-only",
        "--no-upgrade-reextract",
    ]
    on = oj.build_weekly_argv("extract", {**base, "upgrade_abstract_fulltext": True})
    assert on == [
        "extract",
        "--limit",
        "0",
        "--core-only",
        "--upgrade-reextract",
    ]
    # Missing key → off (fast weekly default)
    missing = oj.build_weekly_argv("extract", base)
    assert missing[-1] == "--no-upgrade-reextract"


def test_create_weekly_job_stores_upgrade_flag(monkeypatch):
    _tmp_jobs(monkeypatch)
    job = oj.create_weekly_job(upgrade_abstract_fulltext=True)
    assert job["params"]["upgrade_abstract_fulltext"] is True
    job2 = oj.create_weekly_job()
    assert job2["params"]["upgrade_abstract_fulltext"] is False
