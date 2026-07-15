"""Clear weekly ops memory tables (ops_runs / ops_gap_items / ops_proposals).

Does not touch papers, KG, feasibility_assessments, or weekly_hotspot_* tables.

Examples (from fulltext_workflow/):

  # Preview only (default)
  ..\\.venv\\Scripts\\python.exe scripts\\clear_ops_memory.py

  # Clear all ops memory
  ..\\.venv\\Scripts\\python.exe scripts\\clear_ops_memory.py --yes

  # Clear one focus lane only
  ..\\.venv\\Scripts\\python.exe scripts\\clear_ops_memory.py --focus "breast cancer" --yes

  # Also delete proposal/gap markdown files referenced by cleared rows
  ..\\.venv\\Scripts\\python.exe scripts\\clear_ops_memory.py --yes --delete-files
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.ops_memory import normalize_focus_key
from db.schema import get_conn, init_db


def _counts(conn, focus_key: str | None = None) -> dict[str, int]:
    if focus_key:
        runs = conn.execute(
            "SELECT COUNT(*) FROM ops_runs WHERE focus_key=?", (focus_key,)
        ).fetchone()[0]
        gaps = conn.execute(
            """SELECT COUNT(*) FROM ops_gap_items g
               JOIN ops_runs r ON g.run_id = r.run_id
               WHERE r.focus_key=?""",
            (focus_key,),
        ).fetchone()[0]
        props = conn.execute(
            """SELECT COUNT(*) FROM ops_proposals p
               JOIN ops_runs r ON p.run_id = r.run_id
               WHERE r.focus_key=?""",
            (focus_key,),
        ).fetchone()[0]
    else:
        runs = conn.execute("SELECT COUNT(*) FROM ops_runs").fetchone()[0]
        gaps = conn.execute("SELECT COUNT(*) FROM ops_gap_items").fetchone()[0]
        props = conn.execute("SELECT COUNT(*) FROM ops_proposals").fetchone()[0]
    return {"ops_runs": runs, "ops_gap_items": gaps, "ops_proposals": props}


def _collect_file_paths(conn, focus_key: str | None) -> list[str]:
    paths: list[str] = []
    if focus_key:
        rows = conn.execute(
            """SELECT gap_report_path, proposal_report_path FROM ops_runs
               WHERE focus_key=?""",
            (focus_key,),
        ).fetchall()
        prop_rows = conn.execute(
            """SELECT p.proposal_path FROM ops_proposals p
               JOIN ops_runs r ON p.run_id = r.run_id
               WHERE r.focus_key=?""",
            (focus_key,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT gap_report_path, proposal_report_path FROM ops_runs"
        ).fetchall()
        prop_rows = conn.execute(
            "SELECT proposal_path FROM ops_proposals"
        ).fetchall()
    for row in rows:
        for col in ("gap_report_path", "proposal_report_path"):
            p = row[col]
            if p:
                paths.append(p)
    for row in prop_rows:
        if row["proposal_path"]:
            paths.append(row["proposal_path"])
    # unique, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def clear_ops_memory(
    *,
    focus: str | None = None,
    execute: bool = False,
    delete_files: bool = False,
) -> dict:
    init_db()
    focus_key = normalize_focus_key(focus) if focus is not None else None
    # Empty CLI focus string means "__all__" lane only when explicitly passed as ""
    if focus is not None and not str(focus).strip():
        focus_key = "__all__"

    with get_conn() as conn:
        before = _counts(conn, focus_key)
        file_paths = _collect_file_paths(conn, focus_key) if delete_files else []

        print(
            f"Scope: {'focus_key=' + repr(focus_key) if focus_key else 'ALL ops memory'}"
        )
        print(
            f"Before: runs={before['ops_runs']} gaps={before['ops_gap_items']} "
            f"proposals={before['ops_proposals']}"
        )
        if delete_files:
            print(f"Referenced files: {len(file_paths)}")

        if not execute:
            print("Dry run — pass --yes to delete.")
            return {"dry_run": True, "before": before, "files": file_paths}

        # Child tables first (FK order)
        if focus_key:
            conn.execute(
                """DELETE FROM ops_proposals WHERE run_id IN
                   (SELECT run_id FROM ops_runs WHERE focus_key=?)""",
                (focus_key,),
            )
            conn.execute(
                """DELETE FROM ops_gap_items WHERE run_id IN
                   (SELECT run_id FROM ops_runs WHERE focus_key=?)""",
                (focus_key,),
            )
            conn.execute("DELETE FROM ops_runs WHERE focus_key=?", (focus_key,))
        else:
            conn.execute("DELETE FROM ops_proposals")
            conn.execute("DELETE FROM ops_gap_items")
            conn.execute("DELETE FROM ops_runs")

        after = _counts(conn, focus_key)
        print(
            f"After:  runs={after['ops_runs']} gaps={after['ops_gap_items']} "
            f"proposals={after['ops_proposals']}"
        )

    deleted_files = 0
    if delete_files:
        for path in file_paths:
            try:
                if path and os.path.isfile(path):
                    os.remove(path)
                    deleted_files += 1
                    print(f"  removed {path}")
            except OSError as exc:
                print(f"  [warn] could not remove {path}: {exc}")
        print(f"Files removed: {deleted_files}/{len(file_paths)}")

    return {
        "dry_run": False,
        "before": before,
        "after": after,
        "files_removed": deleted_files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clear ops memory tables (ops_runs / gaps / proposals)."
    )
    parser.add_argument(
        "--focus",
        "-f",
        default=None,
        help="Only clear this focus_key lane (normalized). Omit to clear all.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete rows (default is dry-run preview).",
    )
    parser.add_argument(
        "--delete-files",
        action="store_true",
        help="Also delete markdown files referenced by cleared rows.",
    )
    args = parser.parse_args()
    clear_ops_memory(
        focus=args.focus,
        execute=args.yes,
        delete_files=args.delete_files,
    )


if __name__ == "__main__":
    main()
