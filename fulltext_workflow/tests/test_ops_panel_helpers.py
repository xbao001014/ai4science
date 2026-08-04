"""Tests for pure Gap UI ops-panel display helpers."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ops_panel import format_sidebar_job_chip, step_status_icon  # noqa: E402


def test_step_status_icon():
    assert step_status_icon("pending") == "○"
    assert step_status_icon("running") == "●"
    assert step_status_icon("succeeded") == "✓"
    assert step_status_icon("skipped") == "–"
    assert step_status_icon("failed") == "✗"
    assert step_status_icon("cancelled") == "■"
    assert step_status_icon("unknown-status") == "○"


def test_sidebar_chip_idle_when_no_job():
    assert format_sidebar_job_chip(None) == "周更：空闲"


def test_sidebar_chip_running_shows_current_step():
    job = {
        "state": "running",
        "steps": [
            {"id": "fetch", "status": "succeeded"},
            {"id": "enrich-s2", "status": "running"},
        ],
    }
    assert "enrich-s2" in format_sidebar_job_chip(job)


def test_sidebar_chip_idle_when_job_finished():
    job = {
        "state": "succeeded",
        "steps": [{"id": "fetch", "status": "succeeded"}],
    }
    assert format_sidebar_job_chip(job) == "周更：空闲"


def test_sidebar_chip_pending_without_running_step():
    job = {"state": "pending", "steps": []}
    assert format_sidebar_job_chip(job) == "周更：进行中"
