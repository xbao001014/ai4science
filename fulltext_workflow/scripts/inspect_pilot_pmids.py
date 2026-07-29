"""Inspect post-reconcile details for selected PMIDs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.schema import get_conn, init_db  # noqa: E402

PMIDS = sys.argv[1:] or ["42056496", "41486277", "41547829", "41258399"]


def main() -> None:
    init_db()
    with get_conn() as c:
        for pmid in PMIDS:
            print("====", pmid)
            paper = c.execute(
                "SELECT reconcile_status, extraction_done FROM papers WHERE pmid=?",
                (pmid,),
            ).fetchone()
            print("paper", dict(paper) if paper else None)
            print("datasets:")
            for r in c.execute(
                """
                SELECT e.name, e.access_class, r.status, r.extraction_pass
                FROM relations r
                JOIN entities e ON e.id=r.object_id
                WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                ORDER BY r.status, e.name
                """,
                (pmid,),
            ):
                print(" ", dict(r))
            print("limitations:")
            for r in c.execute(
                """
                SELECT e.name, r.status, r.superseded_by, r.extraction_pass,
                       substr(COALESCE(r.evidence_quote,''),1,80) AS q
                FROM relations r
                JOIN entities e ON e.id=r.object_id
                WHERE r.source_pmid=? AND r.relation='REPORTS_LIMITATION'
                ORDER BY r.status, e.name
                """,
                (pmid,),
            ):
                print(" ", dict(r))
            n = c.execute(
                "SELECT COUNT(*) FROM paper_entity_bindings WHERE source_pmid=?",
                (pmid,),
            ).fetchone()[0]
            print("bindings", n)


if __name__ == "__main__":
    main()
