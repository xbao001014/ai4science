"""Persist method_role on Method entities."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.method_role import backfill_method_roles, load_method_roles  # noqa: E402
from db.schema import get_conn, init_db, upsert_entity  # noqa: E402


def _tmp(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_upsert_method_stores_resolved_role(monkeypatch):
    _tmp(monkeypatch)
    eid = upsert_entity("resnet-50", "Method", method_role="tool")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT method_role FROM entities WHERE id=?", (eid,)
        ).fetchone()
    assert row["method_role"] == "backbone"


def test_upsert_hint_fills_unknown_only(monkeypatch):
    _tmp(monkeypatch)
    eid = upsert_entity("novel-widget-aaa", "Method", method_role="classical_ml")
    with get_conn() as conn:
        assert conn.execute(
            "SELECT method_role FROM entities WHERE id=?", (eid,)
        ).fetchone()["method_role"] == "classical_ml"


def test_upsert_unknown_does_not_clear_existing(monkeypatch):
    _tmp(monkeypatch)
    eid = upsert_entity("novel-widget-bbb", "Method", method_role="tool")
    upsert_entity("novel-widget-bbb", "Method", method_role=None)
    with get_conn() as conn:
        assert conn.execute(
            "SELECT method_role FROM entities WHERE id=?", (eid,)
        ).fetchone()["method_role"] == "tool"


def test_backfill_sets_roles(monkeypatch):
    _tmp(monkeypatch)
    upsert_entity("random forest", "Method")
    upsert_entity("qupath", "Method")
    with get_conn() as conn:
        conn.execute("UPDATE entities SET method_role=NULL WHERE type='Method'")
    counts = backfill_method_roles()
    assert counts.get("classical_ml", 0) >= 1
    assert counts.get("tool", 0) >= 1
    roles = load_method_roles()
    assert roles["random forest"] == "classical_ml"
    assert roles["qupath"] == "tool"
