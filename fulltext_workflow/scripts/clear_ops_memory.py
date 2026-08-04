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
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.ops_memory import clear_ops_memory, preview_ops_memory


def _print_result(
    *,
    focus: str | None,
    delete_files: bool,
    result: dict,
) -> None:
    focus_key = preview_ops_memory(focus)["focus_key"]
    before = result["before"]
    print(
        f"Scope: {'focus_key=' + repr(focus_key) if focus_key else 'ALL ops memory'}"
    )
    print(
        f"Before: runs={before['ops_runs']} gaps={before['ops_gap_items']} "
        f"proposals={before['ops_proposals']}"
    )
    if delete_files:
        files = result.get("files") or []
        print(f"Referenced files: {len(files)}")
    if result.get("dry_run"):
        print("Dry run — pass --yes to delete.")
        return
    after = result["after"]
    print(
        f"After:  runs={after['ops_runs']} gaps={after['ops_gap_items']} "
        f"proposals={after['ops_proposals']}"
    )
    if delete_files:
        removed = result.get("files_removed", 0)
        files = result.get("files") or []
        print(f"Files removed: {removed}/{len(files)}")


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
    result = clear_ops_memory(
        focus=args.focus,
        execute=args.yes,
        delete_files=args.delete_files,
    )
    _print_result(focus=args.focus, delete_files=args.delete_files, result=result)


if __name__ == "__main__":
    main()
