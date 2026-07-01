"""Reset papers marked extracted but with zero relations (failed/empty LLM runs).

Skips errata/correction notices — those are intentionally extraction_done with 0 relations.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from db.schema import get_conn, init_db
from extractor.skip_rules import skip_extraction_reason


def _should_reset(row) -> bool:
    pub_types_raw = row["pub_types"] or "[]"
    try:
        pub_types = json.loads(pub_types_raw)
    except Exception:
        pub_types = []
    if skip_extraction_reason(row["title"] or "", row["abstract"] or "", pub_types):
        return False
    return True


def reset_empty_extractions(dry_run: bool = False) -> list[str]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.pmid, p.title, p.abstract, p.pub_types FROM papers p
            WHERE p.extraction_done = 1
              AND NOT EXISTS (
                  SELECT 1 FROM relations r WHERE r.source_pmid = p.pmid
              )
            ORDER BY p.id
            """
        ).fetchall()
        to_reset = [r for r in rows if _should_reset(r)]
        pmids = [r["pmid"] for r in to_reset]
        skipped = [r["pmid"] for r in rows if not _should_reset(r)]
        if not dry_run and pmids:
            ids = [r["id"] for r in to_reset]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"""
                UPDATE papers SET extraction_done=0, study_type=NULL
                WHERE id IN ({placeholders})
                """,
                ids,
            )
    if skipped:
        print(f"Skipped {len(skipped)} errata/non-extractable (left extraction_done=1): {skipped}")
    return pmids


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    pmids = reset_empty_extractions(dry_run=dry)
    action = "Would reset" if dry else "Reset"
    print(f"{action} {len(pmids)} paper(s): {pmids}")
