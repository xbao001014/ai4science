"""
Unified full-text fetch: JATS (Europe PMC) → ScanSci PDF + MinerU → mark unavailable.

Extraction stage (section_extractor) falls back to abstract when full_text_status
is unavailable.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from tqdm import tqdm

from db.schema import (
    delete_paper_sections,
    get_conn,
    insert_sections,
    mark_fulltext_status,
)
from fetcher.mineru_parser import pdf_to_sections
from fetcher.pmc_fetcher import fetch_jats_fulltext
from fetcher.scansci_fetcher import download_pdf


def _papers_for_pdf_fallback() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT id, pmid, doi, pmc_id, full_text_status FROM papers
               WHERE pmid IS NOT NULL AND full_text_status = 'jats_unavailable'"""
        ).fetchall()


def _store_pdf_sections(paper_id: int, sections: list[dict[str, Any]]) -> bool:
    if not sections:
        return False
    delete_paper_sections(paper_id)
    insert_sections(paper_id, sections)
    return True


def fetch_pdf_mineru_fallback() -> int:
    """Try ScanSci PDF + MinerU for papers without JATS full text."""
    pending = _papers_for_pdf_fallback()
    print(f"[PDF/MinerU] {len(pending)} papers to try after JATS failure.")

    if not pending:
        return 0

    success = 0
    for row in tqdm(pending, desc="  PDF+MinerU", unit="paper"):
        paper_id = row["id"]
        pmid = row["pmid"] or ""
        doi = row["doi"] or ""

        if not doi:
            mark_fulltext_status(paper_id, "unavailable")
            continue

        dl = download_pdf(doi, pmid)
        if not dl.get("success"):
            mark_fulltext_status(paper_id, "unavailable")
            continue

        try:
            sections = pdf_to_sections(dl["file"], pmid)
            if _store_pdf_sections(paper_id, sections):
                mark_fulltext_status(paper_id, "pdf_available")
                success += 1
            else:
                mark_fulltext_status(paper_id, "unavailable")
        except Exception as e:
            print(f"  [WARN] PMID {pmid} MinerU failed: {e}")
            mark_fulltext_status(paper_id, "unavailable")

    print(f"[PDF/MinerU] {success} papers with MinerU sections stored.")
    return success


def fetch_all_fulltext(cache_xml: bool = True) -> None:
    """Three-tier fulltext acquisition (tiers 1–2; tier 3 is abstract at extract time)."""
    print("[Fulltext] Tier 1: Europe PMC JATS XML")
    fetch_jats_fulltext(cache_xml=cache_xml)

    print("[Fulltext] Tier 2: ScanSci PDF + MinerU")
    fetch_pdf_mineru_fallback()

    with get_conn() as conn:
        still = conn.execute(
            """SELECT COUNT(*) FROM papers WHERE full_text_status='jats_unavailable'"""
        ).fetchone()[0]
        if still:
            conn.execute(
                """UPDATE papers SET full_text_status='unavailable'
                   WHERE full_text_status='jats_unavailable'"""
            )
            print(f"[Fulltext] Marked {still} papers unavailable (abstract-only at extract).")

    with get_conn() as conn:
        jats = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='available'"
        ).fetchone()[0]
        pdf = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='pdf_available'"
        ).fetchone()[0]
        unavail = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='unavailable'"
        ).fetchone()[0]
    print(f"[Fulltext] Done: JATS={jats}, MinerU-PDF={pdf}, abstract-only={unavail}")
