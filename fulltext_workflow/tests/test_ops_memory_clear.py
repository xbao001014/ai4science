"""Tests for ops memory preview/clear API."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.ops_memory import clear_ops_memory, preview_ops_memory  # noqa: E402
from db.schema import get_conn, init_db, insert_ops_run  # noqa: E402


def _tmp_db(monkeypatch):
    td = tempfile.mkdtemp()
    db = str(Path(td) / "t.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    init_db()
    return db


def test_preview_and_clear_all(monkeypatch):
    _tmp_db(monkeypatch)
    insert_ops_run(
        week_id="2026-W31",
        focus_raw="breast cancer",
        focus_key="breast carcinoma",
        source="test",
    )
    insert_ops_run(
        week_id="2026-W31",
        focus_raw=None,
        focus_key="__all__",
        source="test",
    )
    prev = preview_ops_memory(None)
    assert prev["focus_key"] is None
    assert prev["counts"]["ops_runs"] == 2
    dry = clear_ops_memory(execute=False)
    assert dry["dry_run"] is True
    assert dry["before"]["ops_runs"] == 2
    done = clear_ops_memory(execute=True)
    assert done["after"]["ops_runs"] == 0


def test_clear_focus_lane_only(monkeypatch):
    _tmp_db(monkeypatch)
    insert_ops_run(
        week_id="2026-W31",
        focus_raw="breast cancer",
        focus_key="breast carcinoma",
        source="test",
    )
    insert_ops_run(
        week_id="2026-W31",
        focus_raw=None,
        focus_key="__all__",
        source="test",
    )
    clear_ops_memory(focus="breast cancer", execute=True)
    prev = preview_ops_memory(None)
    assert prev["counts"]["ops_runs"] == 1
