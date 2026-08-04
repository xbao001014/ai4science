"""Weekly ops job status files and step plan (Gap UI ops tab)."""
from __future__ import annotations

import argparse
import json
import os
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-job", required=True)
    args = parser.parse_args()
    run_weekly_job(args.run_job)
