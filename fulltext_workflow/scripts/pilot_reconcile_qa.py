#!/usr/bin/env python3
"""Export pilot reconcile QA metrics to CSV for manual review."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from db.schema import get_conn, get_papers_by_pmids, init_db  # noqa: E402
from extractor.dataset_access import is_literature_platform  # noqa: E402

CSV_COLUMNS = (
    "pmid",
    "reconcile_status",
    "active_datasets",
    "superseded_datasets",
    "active_limitations",
    "superseded_limitations",
    "binding_count",
    "platform_hit",
)


def _load_pmid_list(path_str: str) -> list[str]:
    path = Path(path_str)
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def _entity_names(pmid: str, relation: str, status: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name
            FROM relations r
            JOIN entities e ON e.id = r.object_id
            WHERE r.source_pmid = ?
              AND r.relation = ?
              AND r.status = ?
            ORDER BY e.name
            """,
            (pmid, relation, status),
        ).fetchall()
    return [row["name"] for row in rows]


def _binding_count(pmid: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM paper_entity_bindings WHERE source_pmid = ?",
            (pmid,),
        ).fetchone()
    return int(row[0])


def _join_names(names: list[str]) -> str:
    return "; ".join(names)


def build_row(pmid: str, paper: dict | None) -> dict[str, str | int]:
    reconcile_status = ""
    if paper is not None:
        reconcile_status = paper.get("reconcile_status") or "pending"

    active_datasets = _entity_names(pmid, "USES_DATASET", "active")
    superseded_datasets = _entity_names(pmid, "USES_DATASET", "superseded")
    active_limitations = _entity_names(pmid, "REPORTS_LIMITATION", "active")
    superseded_limitations = _entity_names(pmid, "REPORTS_LIMITATION", "superseded")
    binding_count = _binding_count(pmid)
    platform_hit = int(any(is_literature_platform(name) for name in active_datasets))

    return {
        "pmid": pmid,
        "reconcile_status": reconcile_status,
        "active_datasets": _join_names(active_datasets),
        "superseded_datasets": _join_names(superseded_datasets),
        "active_limitations": _join_names(active_limitations),
        "superseded_limitations": _join_names(superseded_limitations),
        "binding_count": binding_count,
        "platform_hit": platform_hit,
    }


def export_qa(pmids: list[str], out_path: Path) -> int:
    init_db()
    papers = get_papers_by_pmids(pmids)
    by_pmid = {p["pmid"]: dict(p) for p in papers}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for pmid in pmids:
            writer.writerow(build_row(pmid, by_pmid.get(pmid)))
    return len(pmids)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export pilot reconcile QA metrics to CSV",
    )
    parser.add_argument(
        "--pmid-list",
        type=str,
        required=True,
        help="Text file with one PMID per line (# comments allowed)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output CSV path (e.g. output/pilot_qa.csv)",
    )
    args = parser.parse_args()

    pmids = _load_pmid_list(args.pmid_list)
    if not pmids:
        print("No PMIDs found in list.", file=sys.stderr)
        sys.exit(1)

    count = export_qa(pmids, Path(args.out))
    print(f"Wrote {count} row(s) to {args.out}")


if __name__ == "__main__":
    main()
