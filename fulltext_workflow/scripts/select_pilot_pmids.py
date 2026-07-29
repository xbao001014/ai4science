"""Select 10 pilot PMIDs with fulltext for reconcile QA."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.schema import get_conn, init_db  # noqa: E402


def main() -> None:
    init_db()
    with get_conn() as c:
        papers = c.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        extracted = c.execute(
            "SELECT COUNT(*) FROM papers WHERE extraction_done=1"
        ).fetchone()[0]
        fulltext = c.execute(
            "SELECT COUNT(*) FROM papers "
            "WHERE full_text_status IN ('available','pdf_available')"
        ).fetchone()[0]
        print(f"papers={papers} extracted={extracted} fulltext={fulltext}")

        rows = c.execute(
            """
            SELECT p.pmid, p.full_text_status, p.extraction_done, p.year,
                   (SELECT COUNT(*) FROM relations r
                    WHERE r.source_pmid=p.pmid AND r.relation='USES_DATASET') AS ds,
                   (SELECT COUNT(*) FROM relations r
                    WHERE r.source_pmid=p.pmid
                      AND r.relation='REPORTS_LIMITATION') AS lim
            FROM papers p
            WHERE p.full_text_status IN ('available', 'pdf_available')
              AND p.extraction_done=1
              AND EXISTS (
                  SELECT 1 FROM document_sections s WHERE s.paper_id=p.id
              )
            ORDER BY ds DESC, lim DESC, p.year DESC
            LIMIT 40
            """
        ).fetchall()

        # Prefer mix: top dataset-rich + some with limitations
        picked: list[str] = []
        for r in rows:
            if r["ds"] and r["ds"] > 0 and len(picked) < 7:
                picked.append(r["pmid"])
        for r in rows:
            if r["pmid"] in picked:
                continue
            if r["lim"] and r["lim"] > 0 and len(picked) < 10:
                picked.append(r["pmid"])
        for r in rows:
            if len(picked) >= 10:
                break
            if r["pmid"] not in picked:
                picked.append(r["pmid"])

        out = ROOT / "data" / "pilot_pmids.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "# pilot 10 papers for extraction-quality QA\n"
            + "\n".join(picked)
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {out} ({len(picked)} pmids)")
        by = {r["pmid"]: r for r in rows}
        for pmid in picked:
            r = by[pmid]
            print(
                f"  {pmid} year={r['year']} status={r['full_text_status']} "
                f"ds={r['ds']} lim={r['lim']}"
            )


if __name__ == "__main__":
    main()
