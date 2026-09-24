"""Populate grounded Method/Disease mention annotations for recent papers."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.schema import get_conn, init_db  # noqa: E402
from extractor.entity_mention_backfill import (  # noqa: E402
    backfill_paper_mentions, enrich_explicit_long_forms,
)


def run(days: int, *, dry_run: bool = False) -> dict[str, int]:
    if days < 1:
        raise ValueError("days must be positive")
    init_db()
    with get_conn() as conn:
        keys = [str(row[0]) for row in conn.execute(
            """SELECT DISTINCT COALESCE(p.source_key,p.pmid) AS paper_key
               FROM papers p
               WHERE p.date_precision IN ('day','month')
                 AND date(p.pub_date) BETWEEN date('now', ?) AND date('now')
                 AND EXISTS (
                   SELECT 1 FROM relations r JOIN entities e ON e.id=r.object_id
                   WHERE r.source_pmid=COALESCE(p.source_key,p.pmid)
                     AND COALESCE(r.status,'active')='active'
                     AND e.type IN ('Method','Disease')
                 )
               ORDER BY paper_key""",
            (f"-{days} days",),
        )]
    result = {"eligible_papers": len(keys), "mentions_added": 0, "long_forms_enriched": 0}
    if dry_run:
        return result
    for index, key in enumerate(keys, 1):
        result["mentions_added"] += backfill_paper_mentions(key)
        result["long_forms_enriched"] += enrich_explicit_long_forms(key)
        if index % 100 == 0:
            print(f"[annotations] {index}/{len(keys)} papers", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(run(args.days, dry_run=args.dry_run))
