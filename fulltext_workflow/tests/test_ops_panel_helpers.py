"""Tests for pure Gap UI ops-panel display helpers, plus AppTest-driven
regression coverage for the clear-memory confirm reset behavior."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import init_db  # noqa: E402
from ops_panel import format_sidebar_job_chip, step_status_icon  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover - AppTest is optional per task scope
    AppTest = None


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


def _clear_memory_app(focus_hint: str = "", root: str = "") -> None:
    import sys

    if root and root not in sys.path:
        sys.path.insert(0, root)
    import ops_panel

    ops_panel._render_clear_memory_section(focus_hint)


def _tmp_db(monkeypatch):
    td = tempfile.mkdtemp()
    db = str(Path(td) / "t.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    init_db()


@pytest.mark.skipif(AppTest is None, reason="streamlit AppTest not available")
def test_clear_confirm_resets_when_focus_option_disappears(monkeypatch):
    """Reproduces review M2: removing the sidebar focus makes the
    "仅当前焦点" radio option disappear (scope silently snaps to "全部");
    the confirm checkbox must not stay armed across that widening."""
    _tmp_db(monkeypatch)

    at = AppTest.from_function(
        _clear_memory_app, kwargs={"focus_hint": "breast cancer", "root": str(_ROOT)}
    )
    at.run()
    at.radio(key="ops_clear_scope").set_value("仅当前焦点")
    at.run()
    at.checkbox(key="ops_clear_confirm").set_value(True)
    at.run()
    assert at.session_state["ops_clear_confirm"] is True

    at.kwargs = {"focus_hint": "", "root": str(_ROOT)}
    at.run()
    assert at.session_state["ops_clear_scope"] == "全部"
    assert at.session_state["ops_clear_confirm"] is False


@pytest.mark.skipif(AppTest is None, reason="streamlit AppTest not available")
def test_clear_confirm_resets_on_manual_scope_switch(monkeypatch):
    """Manually switching the radio from "仅当前焦点" back to "全部" (focus
    unchanged) must also disarm the confirm checkbox."""
    _tmp_db(monkeypatch)

    at = AppTest.from_function(
        _clear_memory_app, kwargs={"focus_hint": "breast cancer", "root": str(_ROOT)}
    )
    at.run()
    at.radio(key="ops_clear_scope").set_value("仅当前焦点")
    at.run()
    at.checkbox(key="ops_clear_confirm").set_value(True)
    at.run()
    assert at.session_state["ops_clear_confirm"] is True

    at.radio(key="ops_clear_scope").set_value("全部")
    at.run()
    assert at.session_state["ops_clear_confirm"] is False


@pytest.mark.skipif(AppTest is None, reason="streamlit AppTest not available")
def test_clear_execute_resets_confirm_without_session_state_error(monkeypatch):
    """After a successful clear, confirm must disarm on the next run without
    mutating the widget key after the checkbox is instantiated."""
    _tmp_db(monkeypatch)

    at = AppTest.from_function(
        _clear_memory_app, kwargs={"focus_hint": "", "root": str(_ROOT)}
    )
    at.run()
    at.checkbox(key="ops_clear_confirm").set_value(True)
    at.run()
    assert at.session_state["ops_clear_confirm"] is True

    at.button(key="ops_clear_execute_btn").click()
    at.run()

    assert not at.exception
    assert at.session_state["ops_clear_confirm"] is False
    assert any("已清空" in s.value for s in at.success)
