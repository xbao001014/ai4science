"""Reset completed LLM extractions so papers can be re-extracted.

Deletes KG extraction artifacts (relations, Pass2 bindings / improvement
suggestions), clears limitation lifecycle tables, removes orphan entities, and
resets extraction_done + reconcile_status.

Preserves: papers metadata, sections, fulltext caches, citations/IF, ops memory,
weekly hotspot snapshots (recompute after re-extract if needed).

Default mode skips errata/correction notices (keeps their extraction_done=1 and
triples). For a clean full re-extract use ``--purge-all`` to wipe every
relation/entity and reset all papers.
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


def _count_for_pmids(conn, table: str, pmids: list[str]) -> int:
    if not pmids:
        return 0
    placeholders = ",".join("?" * len(pmids))
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_pmid IN ({placeholders})",
            pmids,
        ).fetchone()[0]
    )


def reset_extractions(*, dry_run: bool = False, purge_all: bool = False) -> dict:
    init_db()
    with get_conn() as conn:
        paper_count = int(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0])
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
        placeholders = ",".join("?" * len(pmids)) if pmids else ""

        if purge_all:
            rel_count = int(conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0])
            bind_count = int(
                conn.execute("SELECT COUNT(*) FROM paper_entity_bindings").fetchone()[0]
            )
            sugg_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM paper_improvement_suggestions"
                ).fetchone()[0]
            )
            ent_count = int(conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
        else:
            rel_count = _count_for_pmids(conn, "relations", pmids)
            bind_count = _count_for_pmids(conn, "paper_entity_bindings", pmids)
            sugg_count = _count_for_pmids(conn, "paper_improvement_suggestions", pmids)
            ent_count = 0

        deleted_entities = 0
        if not dry_run and (purge_all or pmids):
            if purge_all:
                conn.execute("DELETE FROM relations")
                conn.execute("DELETE FROM paper_entity_bindings")
                conn.execute("DELETE FROM paper_improvement_suggestions")
                conn.execute("DELETE FROM limitation_resolution_signals")
                conn.execute("DELETE FROM limitation_temporal")
                conn.execute("DELETE FROM entities")
                deleted_entities = ent_count
                conn.execute(
                    """
                    UPDATE papers
                    SET extraction_done = 0,
                        study_type = NULL,
                        reconcile_status = 'pending',
                        reconcile_at = NULL
                    """
                )
            else:
                conn.execute(
                    f"DELETE FROM relations WHERE source_pmid IN ({placeholders})",
                    pmids,
                )
                conn.execute(
                    f"DELETE FROM paper_entity_bindings WHERE source_pmid IN ({placeholders})",
                    pmids,
                )
                conn.execute(
                    f"""
                    DELETE FROM paper_improvement_suggestions
                    WHERE source_pmid IN ({placeholders})
                    """,
                    pmids,
                )
                conn.execute("DELETE FROM limitation_resolution_signals")
                conn.execute("DELETE FROM limitation_temporal")
                deleted_entities = conn.execute(
                    """
                    DELETE FROM entities
                    WHERE id NOT IN (
                        SELECT object_id FROM relations
                        UNION
                        SELECT subject_id FROM relations WHERE subject_type != 'Paper'
                        UNION
                        SELECT method_entity_id FROM paper_entity_bindings
                            WHERE method_entity_id IS NOT NULL
                        UNION
                        SELECT disease_entity_id FROM paper_entity_bindings
                            WHERE disease_entity_id IS NOT NULL
                        UNION
                        SELECT dataset_entity_id FROM paper_entity_bindings
                            WHERE dataset_entity_id IS NOT NULL
                        UNION
                        SELECT limitation_entity_id FROM paper_improvement_suggestions
                            WHERE limitation_entity_id IS NOT NULL
                    )
                    """
                ).rowcount
                ids = [r["id"] for r in to_reset]
                id_ph = ",".join("?" * len(ids))
                conn.execute(
                    f"""
                    UPDATE papers
                    SET extraction_done = 0,
                        study_type = NULL,
                        reconcile_status = 'pending',
                        reconcile_at = NULL
                    WHERE id IN ({id_ph})
                    """,
                    ids,
                )

    return {
        "purge_all": purge_all,
        "reset_papers": paper_count if purge_all else len(to_reset),
        "skipped_errata": 0 if purge_all else len(skipped),
        "deleted_relations": rel_count,
        "deleted_bindings": bind_count,
        "deleted_suggestions": sugg_count,
        "deleted_orphan_entities": deleted_entities if not dry_run else None,
        "sample_pmids": pmids[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset completed extractions for re-run")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts only")
    parser.add_argument(
        "--purge-all",
        action="store_true",
        help="Wipe ALL relations/entities and reset every paper (for full re-extract)",
    )
    args = parser.parse_args()

    stats = reset_extractions(dry_run=args.dry_run, purge_all=args.purge_all)
    action = "Would reset" if args.dry_run else "Reset"
    mode = " (purge-all)" if stats["purge_all"] else ""
    print(f"{action} {stats['reset_papers']} paper(s){mode}")
    print(f"Skipped errata/non-extractable: {stats['skipped_errata']}")
    print(f"Relations affected: {stats['deleted_relations']}")
    print(f"Pass2 bindings affected: {stats['deleted_bindings']}")
    print(f"Improvement suggestions affected: {stats['deleted_suggestions']}")
    if stats["deleted_orphan_entities"] is not None:
        print(f"Entities removed: {stats['deleted_orphan_entities']}")
    if stats["sample_pmids"]:
        print(f"Sample PMIDs: {stats['sample_pmids']}")


if __name__ == "__main__":
    main()
