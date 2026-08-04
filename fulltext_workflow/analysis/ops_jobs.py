"""Weekly ops job status files and step plan (Gap UI ops tab)."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import config

OPS_JOBS_DIR: Path = Path(config.OUTPUT_DIR) / "ops_jobs"

WEEKLY_STEPS: list[dict[str, str]] = [
    {"id": "fetch", "label": "fetch"},
    {"id": "enrich-s2", "label": "enrich-s2"},
    {"id": "fetch-fulltext", "label": "fetch-fulltext"},
    {"id": "extract", "label": "extract"},
    {"id": "compute-gap-lifecycle", "label": "compute-gap-lifecycle"},
    {"id": "hotspot-report", "label": "hotspot-report"},
    {"id": "hotspot-brief", "label": "hotspot-brief"},
    {"id": "build", "label": "build"},
    {"id": "analyze", "label": "analyze"},
    {"id": "stats", "label": "stats"},
]

_DONE_STEP_STATUSES = frozenset({"succeeded", "skipped"})


class OpsJobError(Exception):
    """Raised for invalid weekly ops job operations (e.g. already running)."""


def new_job_id(kind: str = "weekly") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{kind}"


def job_dir(job_id: str) -> Path:
    return OPS_JOBS_DIR / job_id


def _current_path() -> Path:
    return OPS_JOBS_DIR / "current.json"


def write_status(job: dict) -> None:
    d = job_dir(job["job_id"])
    d.mkdir(parents=True, exist_ok=True)
    path = d / "status.json"
    tmp = d / "status.json.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_status(job_id: str) -> dict | None:
    path = job_dir(job_id) / "status.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_current(job_id: str, state: str) -> None:
    OPS_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"job_id": job_id, "state": state}
    path = _current_path()
    tmp = OPS_JOBS_DIR / "current.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_current() -> dict | None:
    path = _current_path()
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _initial_steps() -> list[dict]:
    return [
        {
            "id": step["id"],
            "label": step["label"],
            "status": "pending",
            "started_at": None,
            "finished_at": None,
        }
        for step in WEEKLY_STEPS
    ]


def create_weekly_job(
    *,
    since_days: int = 14,
    extract_limit: int = 0,
    skip_enrich: bool = False,
) -> dict:
    job_id = new_job_id("weekly")
    job = {
        "job_id": job_id,
        "kind": "weekly",
        "state": "pending",
        "params": {
            "since_days": since_days,
            "extract_limit": extract_limit,
            "skip_enrich": skip_enrich,
        },
        "pid": None,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "steps": _initial_steps(),
    }
    write_status(job)
    write_current(job_id, "pending")
    return job


def build_weekly_argv(step_id: str, params: dict) -> list[str] | None:
    if step_id == "enrich-s2" and params.get("skip_enrich"):
        return None
    if step_id == "fetch":
        return ["fetch", "--since-days", str(params["since_days"])]
    if step_id == "extract":
        return [
            "extract",
            "--limit",
            str(params["extract_limit"]),
            "--core-only",
        ]
    if step_id in {
        "enrich-s2",
        "fetch-fulltext",
        "compute-gap-lifecycle",
        "hotspot-report",
        "hotspot-brief",
        "build",
        "analyze",
        "stats",
    }:
        return [step_id]
    return None


def _log_path(job_id: str) -> Path:
    return job_dir(job_id) / "log.txt"


def append_log(job_id: str, text: str) -> None:
    path = _log_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def tail_log(job_id: str, max_lines: int = 200) -> str:
    path = _log_path(job_id)
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    if max_lines <= 0:
        return ""
    return "\n".join(lines[-max_lines:])


def progress_counts(job: dict) -> tuple[int, int]:
    steps = job.get("steps") or []
    total = len(steps)
    done = sum(1 for s in steps if s.get("status") in _DONE_STEP_STATUSES)
    return done, total


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_run_step(argv: list[str], log_fh) -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(root / "main.py"), *argv]
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log_fh.write(proc.stdout or "")
    log_fh.flush()
    return int(proc.returncode)


def run_weekly_job(
    job_id: str,
    *,
    run_step_fn: Callable[[list[str], object], int] | None = None,
) -> dict:
    if run_step_fn is None:
        run_step_fn = _default_run_step

    job = read_status(job_id)
    if job is None:
        raise ValueError(f"unknown job: {job_id}")

    job["state"] = "running"
    job["pid"] = os.getpid()
    if not job.get("started_at"):
        job["started_at"] = _utc_now()
    write_status(job)
    write_current(job_id, "running")

    params = job["params"]
    failed = False

    for step in job["steps"]:
        if step.get("status") in _DONE_STEP_STATUSES:
            continue

        argv = build_weekly_argv(step["id"], params)
        if argv is None:
            step["status"] = "skipped"
            step["finished_at"] = _utc_now()
            write_status(job)
            continue

        step["status"] = "running"
        step["started_at"] = _utc_now()
        write_status(job)

        log_path = _log_path(job_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_fh:
            rc = run_step_fn(argv, log_fh)

        step["finished_at"] = _utc_now()
        if rc == 0:
            step["status"] = "succeeded"
            write_status(job)
        else:
            step["status"] = "failed"
            job["error"] = f"step {step['id']} exited with code {rc}"
            job["state"] = "failed"
            job["finished_at"] = _utc_now()
            write_status(job)
            failed = True
            break

    if not failed and all(s.get("status") in _DONE_STEP_STATUSES for s in job["steps"]):
        job["state"] = "succeeded"
        job["finished_at"] = _utc_now()
        write_status(job)

    write_current(job_id, job["state"])
    return job


def pid_is_alive(pid: int) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            still_active = 259
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def reclaim_zombie(job: dict) -> dict:
    if job is None:
        return job
    if job.get("state") == "running" and not pid_is_alive(job.get("pid")):
        job["state"] = "failed"
        job["error"] = "process exited unexpectedly"
        job["finished_at"] = _utc_now()
        for step in job["steps"]:
            if step.get("status") == "running":
                step["status"] = "failed"
                step["finished_at"] = _utc_now()
        write_status(job)
        write_current(job["job_id"], job["state"])
    return job


def get_active_weekly_job() -> dict | None:
    current = read_current()
    if current is None:
        return None
    job = read_status(current["job_id"])
    if job is None:
        return None
    if job.get("state") == "running":
        job = reclaim_zombie(job)
    return job


def _default_spawn(job_id: str) -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "analysis.ops_jobs", "--run-job", job_id]
    kwargs: dict = {"cwd": str(root), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return int(proc.pid)


def start_weekly_job(
    *,
    since_days: int = 14,
    extract_limit: int = 0,
    skip_enrich: bool = False,
    spawn_fn: Callable[[str], int] | None = None,
) -> dict:
    if spawn_fn is None:
        spawn_fn = _default_spawn

    active = get_active_weekly_job()
    if active is not None and active.get("state") == "running":
        raise OpsJobError(f"weekly job {active['job_id']} is already running")

    job = create_weekly_job(
        since_days=since_days,
        extract_limit=extract_limit,
        skip_enrich=skip_enrich,
    )
    job["pid"] = int(spawn_fn(job["job_id"]))
    write_status(job)
    return job


def _kill_process_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def cancel_weekly_job(job_id: str | None = None) -> dict:
    if job_id is None:
        current = read_current()
        if current is None:
            raise OpsJobError("no active weekly job to cancel")
        job_id = current["job_id"]

    job = read_status(job_id)
    if job is None:
        raise OpsJobError(f"unknown job: {job_id}")

    pid = job.get("pid")
    if pid and pid_is_alive(pid):
        _kill_process_tree(pid)

    for step in job["steps"]:
        if step.get("status") == "running":
            step["status"] = "cancelled"
            step["finished_at"] = _utc_now()

    job["state"] = "cancelled"
    job["finished_at"] = _utc_now()
    write_status(job)
    write_current(job_id, job["state"])
    return job


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-job", required=True)
    args = parser.parse_args()
    run_weekly_job(args.run_job)
