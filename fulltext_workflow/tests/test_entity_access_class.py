"""Tests for entities.access_class upsert upgrade."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_upsert_dataset_access_class_upgrade(monkeypatch):
    import config
    from db import schema as schema_mod

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(schema_mod, "DB_PATH", path)

    schema_mod.init_db()
    eid1 = schema_mod.upsert_entity("camelyon17", "Dataset", access_class="unknown")
    eid2 = schema_mod.upsert_entity("camelyon17", "Dataset", access_class="public")
    assert eid1 == eid2

    with schema_mod.get_conn() as conn:
        row = conn.execute(
            "SELECT access_class FROM entities WHERE id=?", (eid1,)
        ).fetchone()
    assert row["access_class"] == "public"

    Path(path).unlink(missing_ok=True)
    for side in (path + "-wal", path + "-shm"):
        Path(side).unlink(missing_ok=True)
