"""Reset completed LLM extractions so papers can be re-extracted.

Deletes relations for selected papers, removes orphan entities, clears
limitation lifecycle tables, and sets extraction_done=0.

Skips errata/correction notices (same rules as reset_empty_extraction.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from db.schema import get_conn, init_db
from extractor.skip_rules import skip_extraction_reason


def _is_skippable(row) -> bool:
    pub_types_raw = row["pub_types"] or "[]"
    try:
        pub_types = json.loads(pub_types_raw)
    except Exception:
        pub_types = []
    return bool(skip_extraction_reason(row["title"] or "", row["abstract"] or "", pub_types))


def reset_extractions(*, dry_run: bool = False) -> dict:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, pmid, title, abstract, pub_types
            FROM papers
            WHERE extraction_done = 1
            ORDER BY id
            """
        ).fetchall()

        to_reset = [r for r in rows if not _is_skippable(r)]
        skipped = [r for r in rows if _is_skippable(r)]
        pmids = [r["pmid"] for r in to_reset if r["pmid"]]
        rel_count = 0
        if pmids:
            placeholders = ",".join("?" * len(pmids))
            rel_count = conn.execute(
                f"SELECT COUNT(*) FROM relations WHERE source_pmid IN ({placeholders})",
                pmids,
            ).fetchone()[0]

        orphan_entities = 0
        if not dry_run and pmids:
            placeholders = ",".join("?" * len(pmids))
            conn.execute(
                f"DELETE FROM relations WHERE source_pmid IN ({placeholders})",
                pmids,
            )
            conn.execute("DELETE FROM limitation_resolution_signals")
            conn.execute("DELETE FROM limitation_temporal")
            orphan_entities = conn.execute(
                """
                DELETE FROM entities
                WHERE id NOT IN (
                    SELECT object_id FROM relations
                    UNION
                    SELECT subject_id FROM relations WHERE subject_type != 'Paper'
                )
                """
            ).rowcount
            ids = [r["id"] for r in to_reset]
            id_ph = ",".join("?" * len(ids))
            conn.execute(
                f"""
                UPDATE papers SET extraction_done = 0, study_type = NULL
                WHERE id IN ({id_ph})
                """,
                ids,
            )

    return {
        "reset_papers": len(to_reset),
        "skipped_errata": len(skipped),
        "deleted_relations": rel_count,
        "deleted_orphan_entities": orphan_entities if not dry_run else None,
        "sample_pmids": pmids[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset completed extractions for re-run")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts only")
    args = parser.parse_args()

    stats = reset_extractions(dry_run=args.dry_run)
    action = "Would reset" if args.dry_run else "Reset"
    print(f"{action} {stats['reset_papers']} paper(s)")
    print(f"Skipped errata/non-extractable: {stats['skipped_errata']}")
    print(f"Relations affected: {stats['deleted_relations']}")
    if stats["deleted_orphan_entities"] is not None:
        print(f"Orphan entities removed: {stats['deleted_orphan_entities']}")
    if stats["sample_pmids"]:
        print(f"Sample PMIDs: {stats['sample_pmids']}")


if __name__ == "__main__":
    main()
