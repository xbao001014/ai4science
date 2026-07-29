"""Snapshot dataset/limitation state for pilot PMIDs (before or after)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extractor.dataset_access import is_literature_platform  # noqa: E402
from db.schema import get_conn, init_db  # noqa: E402


def load_pmids(path: Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "snap"
    pmid_list = ROOT / "data" / "pilot_pmids.txt"
    out = ROOT / "output" / f"pilot_{label}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pmids = load_pmids(pmid_list)
    init_db()
    rows_out = []
    with get_conn() as c:
        for pmid in pmids:
            paper = c.execute(
                "SELECT reconcile_status, extraction_done FROM papers WHERE pmid=?",
                (pmid,),
            ).fetchone()
            ds = c.execute(
                """
                SELECT e.name, COALESCE(e.access_class,'unknown') AS access_class,
                       COALESCE(r.status,'active') AS status
                FROM relations r
                JOIN entities e ON e.id=r.object_id AND e.type='Dataset'
                WHERE r.source_pmid=? AND r.relation='USES_DATASET'
                """,
                (pmid,),
            ).fetchall()
            lim = c.execute(
                """
                SELECT e.name, COALESCE(r.status,'active') AS status,
                       r.extraction_pass
                FROM relations r
                JOIN entities e ON e.id=r.object_id AND e.type='Limitation'
                WHERE r.source_pmid=? AND r.relation='REPORTS_LIMITATION'
                """,
                (pmid,),
            ).fetchall()
            binds = c.execute(
                "SELECT COUNT(*) FROM paper_entity_bindings WHERE source_pmid=?",
                (pmid,),
            ).fetchone()[0]
            active_ds = [r["name"] for r in ds if r["status"] == "active"]
            super_ds = [r["name"] for r in ds if r["status"] == "superseded"]
            active_lim = [r["name"] for r in lim if r["status"] == "active"]
            super_lim = [r["name"] for r in lim if r["status"] == "superseded"]
            public_active = [
                r["name"]
                for r in ds
                if r["status"] == "active" and r["access_class"] == "public"
            ]
            platform_hits = [n for n in active_ds if is_literature_platform(n)]
            rows_out.append(
                {
                    "pmid": pmid,
                    "reconcile_status": (paper["reconcile_status"] if paper else None),
                    "n_active_ds": len(active_ds),
                    "n_super_ds": len(super_ds),
                    "n_active_lim": len(active_lim),
                    "n_super_lim": len(super_lim),
                    "n_bindings": binds,
                    "platform_hit": 1 if platform_hits else 0,
                    "platform_names": "|".join(platform_hits),
                    "public_active": "|".join(public_active[:12]),
                    "active_datasets": "|".join(active_ds[:20]),
                    "active_limitations": "|".join(active_lim[:15]),
                }
            )
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"wrote {out}")
    plat = sum(r["platform_hit"] for r in rows_out)
    print(
        f"summary: papers={len(rows_out)} platform_hit_papers={plat} "
        f"total_active_ds={sum(r['n_active_ds'] for r in rows_out)} "
        f"total_active_lim={sum(r['n_active_lim'] for r in rows_out)} "
        f"total_bindings={sum(r['n_bindings'] for r in rows_out)} "
        f"total_super_lim={sum(r['n_super_lim'] for r in rows_out)}"
    )


if __name__ == "__main__":
    main()
