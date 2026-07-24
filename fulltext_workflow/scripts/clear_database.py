"""Clear the fulltext KG SQLite database (all tables).

Removes `data/kg_fulltext.db` (and WAL/SHM sidecars) then recreates an empty
schema via `init_db()`. Does **not** delete `raw/` caches (PMC XML, MinerU, etc.).

Examples (from fulltext_workflow/):

  # Preview row counts only (default)
  ..\\.venv\\Scripts\\python.exe scripts\\clear_database.py

  # Wipe and re-init empty DB
  ..\\.venv\\Scripts\\python.exe scripts\\clear_database.py --yes
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from db.schema import init_db


def _db_paths() -> list[Path]:
    base = Path(config.DB_PATH)
    return [base, Path(str(base) + "-wal"), Path(str(base) + "-shm")]


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


def _table_counts() -> dict[str, int]:
    path = Path(config.DB_PATH)
    if not path.exists():
        return {}
    counts: dict[str, int] = {}
    with sqlite3.connect(path) as conn:
        for name in _list_tables(conn):
            counts[name] = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
    return counts


def _wipe_via_delete() -> None:
    """Clear all rows when the DB file is locked (cannot unlink)."""
    path = Path(config.DB_PATH)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        tables = _list_tables(conn)
        for name in tables:
            conn.execute(f"DELETE FROM [{name}]")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    init_db()


def clear_database(*, yes: bool = False) -> dict:
    path = Path(config.DB_PATH)
    before = _table_counts()
    total = sum(before.values())

    if not yes:
        return {
            "dry_run": True,
            "db_path": str(path),
            "exists": path.exists(),
            "tables": before,
            "total_rows": total,
        }

    mode = "unlink"
    try:
        for p in _db_paths():
            if p.exists():
                p.unlink()
        init_db()
    except OSError as exc:
        # WinError 32: file in use by another process (IDE / extract / Streamlit).
        mode = "delete_rows"
        print(f"[clear_database] Could not delete file ({exc}); wiping via DELETE instead.")
        _wipe_via_delete()

    after = _table_counts()
    return {
        "dry_run": False,
        "db_path": str(path),
        "exists": True,
        "mode": mode,
        "tables_before": before,
        "total_rows_before": total,
        "tables_after": after,
        "total_rows_after": sum(after.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clear kg_fulltext.db (all tables) and recreate empty schema"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete the DB file and re-init (required to wipe)",
    )
    args = parser.parse_args()

    result = clear_database(yes=args.yes)
    print(f"DB: {result['db_path']}")

    if result["dry_run"]:
        if not result["exists"]:
            print("Database file does not exist (nothing to clear).")
            return
        print(f"Would wipe {result['total_rows']} row(s) across {len(result['tables'])} table(s):")
        for name, cnt in result["tables"].items():
            print(f"  {cnt:6d}  {name}")
        print("\nRe-run with --yes to delete the DB and recreate an empty schema.")
        print("(raw/ caches are left untouched.)")
        return

    print(
        f"Cleared {result['total_rows_before']} row(s) via {result['mode']}; "
        f"DB now has {result['total_rows_after']} row(s)."
    )


if __name__ == "__main__":
    main()
