"""
Unified full-text fetch: JATS (Europe PMC) → ScanSci PDF + MinerU → mark unavailable.

Extraction stage (section_extractor) falls back to abstract when full_text_status
is unavailable. Cooled-down unavailable papers are requeued at the start of a run.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from tqdm import tqdm

import config
from db.schema import (
    delete_paper_sections,
    get_conn,
    insert_sections,
    mark_fulltext_status,
    requeue_cooled_fulltext_failures,
)
from fetcher.mineru_parser import pdf_to_sections
from fetcher.pmc_fetcher import fetch_jats_fulltext
from fetcher.scansci_fetcher import download_pdf


def _papers_for_pdf_fallback(limit: int | None = None) -> list[sqlite3.Row]:
    """jats_unavailable papers, newest first. limit=None or 0 → no cap."""
    sql = """
        SELECT id, pmid, doi, pmc_id, full_text_status, year, created_at
        FROM papers
        WHERE pmid IS NOT NULL AND full_text_status = 'jats_unavailable'
        ORDER BY year IS NULL, year DESC, created_at DESC
    """
    with get_conn() as conn:
        if limit is not None and limit > 0:
            return conn.execute(sql + " LIMIT ?", (int(limit),)).fetchall()
        return conn.execute(sql).fetchall()


def finalize_jats_unavailable_as_unavailable() -> int:
    """Mark leftover jats_unavailable as unavailable; refresh fetched_at."""
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE papers SET
                   full_text_status='unavailable',
                   full_text_fetched_at=CURRENT_TIMESTAMP
               WHERE full_text_status='jats_unavailable'"""
        )
        return int(cur.rowcount)


def _store_pdf_sections(paper_id: int, sections: list[dict[str, Any]]) -> bool:
    if not sections:
        return False
    delete_paper_sections(paper_id)
    insert_sections(paper_id, sections)
    return True


def fetch_pdf_mineru_fallback(limit: int | None = None) -> int:
    """Try ScanSci PDF + MinerU for papers without JATS full text."""
    pending = _papers_for_pdf_fallback(limit=limit)
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


def fetch_all_fulltext(
    cache_xml: bool = True,
    *,
    retry: bool = True,
    force_retry: bool = False,
    pdf_retry_limit: int | None = None,
) -> dict[str, int]:
    """Three-tier fulltext acquisition (tiers 1–2; tier 3 is abstract at extract)."""
    if pdf_retry_limit is None:
        pdf_retry_limit = config.FULLTEXT_PDF_RETRY_LIMIT

    retried = 0
    if retry or force_retry:
        retried = requeue_cooled_fulltext_failures(
            cooldown_days=config.FULLTEXT_RETRY_COOLDOWN_DAYS,
            force=force_retry,
        )
        print(
            f"[Fulltext] Requeued {retried} cooled-down failures "
            f"(force={force_retry}, cooldown_days={config.FULLTEXT_RETRY_COOLDOWN_DAYS})."
        )

    print("[Fulltext] Tier 1: Europe PMC JATS XML")
    fetch_jats_fulltext(cache_xml=cache_xml)

    with get_conn() as conn:
        jats_pool = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='jats_unavailable'"
        ).fetchone()[0]

    effective_limit = None if pdf_retry_limit == 0 else pdf_retry_limit
    pdf_attempt_cap = jats_pool if effective_limit is None else min(jats_pool, effective_limit)
    pdf_skipped_by_limit = max(0, jats_pool - pdf_attempt_cap)

    print("[Fulltext] Tier 2: ScanSci PDF + MinerU")
    pdf_ok = fetch_pdf_mineru_fallback(limit=effective_limit)

    still = finalize_jats_unavailable_as_unavailable()
    if still:
        print(
            f"[Fulltext] Marked {still} papers unavailable "
            f"(abstract-only at extract; skipped_by_pdf_limit≈{pdf_skipped_by_limit})."
        )

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

    stats = {
        "retried_into_pending": retried,
        "pdf_attempted": pdf_attempt_cap,
        "pdf_ok": pdf_ok,
        "pdf_skipped_by_limit": pdf_skipped_by_limit,
        "jats_available": jats,
        "pdf_available": pdf,
        "unavailable": unavail,
        "jats_unavailable_before_tier2": jats_pool,
    }
    print(
        f"[Fulltext] Done: retried={retried}, JATS={jats}, MinerU-PDF={pdf}, "
        f"abstract-only={unavail}, pdf_skipped_by_limit={pdf_skipped_by_limit}"
    )
    return stats
