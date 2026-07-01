"""Find papers whose cached PMC XML embeds a different PMID/DOI; reset for re-fetch."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from db.schema import delete_paper_sections, get_conn, init_db
from fetcher.pmc_fetcher import _jats_article_ids, _jats_matches_paper


def find_mismatches() -> list[dict]:
    init_db()
    cache_dir = Path(config.RAW_PMC_DIR)
    if not cache_dir.is_dir():
        return []

    mismatches: list[dict] = []
    with get_conn() as conn:
        for xml_path in cache_dir.glob("*.xml"):
            pmid = xml_path.stem
            row = conn.execute(
                "SELECT id, pmid, doi, title, full_text_status FROM papers WHERE pmid=?",
                (pmid,),
            ).fetchone()
            if not row:
                continue
            root = ET.parse(xml_path).getroot()
            if _jats_matches_paper(root, pmid, row["doi"]):
                continue
            xml_ids = _jats_article_ids(root)
            mismatches.append(
                {
                    "paper_id": row["id"],
                    "pmid": pmid,
                    "doi": row["doi"],
                    "title": (row["title"] or "")[:80],
                    "status": row["full_text_status"],
                    "xml_pmid": xml_ids.get("pmid"),
                    "xml_doi": xml_ids.get("doi"),
                    "cache": str(xml_path),
                }
            )
    return mismatches


def reset_mismatches(dry_run: bool = False) -> list[str]:
    fixed: list[str] = []
    for item in find_mismatches():
        pmid = item["pmid"]
        print(
            f"{'[dry-run] ' if dry_run else ''}PMID {pmid}: "
            f"xml pmid={item['xml_pmid']} doi={item['xml_doi']} "
            f"(paper doi={item['doi']})"
        )
        if dry_run:
            fixed.append(pmid)
            continue
        paper_id = item["paper_id"]
        delete_paper_sections(paper_id)
        with get_conn() as conn:
            conn.execute(
                """UPDATE papers SET
                   full_text_status='unavailable',
                   pmc_id=NULL,
                   extraction_done=0,
                   study_type=NULL,
                   full_text_fetched_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (paper_id,),
            )
        cache_path = Path(item["cache"])
        if cache_path.exists():
            cache_path.unlink()
        fixed.append(pmid)
    return fixed


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    items = reset_mismatches(dry_run=dry)
    print(f"\n{'Would fix' if dry else 'Fixed'} {len(items)} paper(s): {items}")
