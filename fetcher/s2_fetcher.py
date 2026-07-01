"""
fetcher/s2_fetcher.py
Semantic Scholar Academic Graph API — enriches papers with:
  - citation_count, open_access flag
  - paper references / citations (→ citation edges)
  - s2id
  - fallback abstract if PubMed abstract is empty

Uses the /paper/batch endpoint to fetch up to 500 papers at a time by DOI or PMID.
API key recommended to avoid rate limits (100 req/s vs 1 req/s).
"""
from __future__ import annotations

import time
from typing import Any

import requests
from tqdm import tqdm

import config
from utils.db import get_conn, upsert_citation

_BASE = "https://api.semanticscholar.org/graph/v1"
_BATCH_SIZE = 100          # papers per /paper/batch request (max 500)
_RATE_DELAY = 1.0          # seconds between batches (conservative)
_TIMEOUT = 30

_HEADERS: dict[str, str] = {}
if config.S2_API_KEY:
    _HEADERS["x-api-key"] = config.S2_API_KEY


# ─────────────────────────────────────────────────────────────────────────────
# Low-level API calls
# ─────────────────────────────────────────────────────────────────────────────

def _batch_fetch(paper_ids: list[str], fields: str) -> list[dict]:
    """
    POST /paper/batch — fetch multiple papers at once.
    paper_ids can be "PMID:xxxxx" or "DOI:10.xxxx" or S2 paperId.
    """
    url = f"{_BASE}/paper/batch"
    payload = {"ids": paper_ids}
    params = {"fields": fields}
    resp = requests.post(url, json=payload, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    if resp.status_code == 429:
        print("  [S2] Rate limited — waiting 60s...")
        time.sleep(60)
        resp = requests.post(url, json=payload, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _get_paper_references(s2id: str) -> list[str]:
    """Return list of PMIDs that this S2 paper references."""
    url = f"{_BASE}/paper/{s2id}/references"
    params = {"fields": "externalIds", "limit": 500}

    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
            continue

        if resp.status_code == 429:
            wait = 30 * (attempt + 1)   # 30s, 60s, 90s, 120s
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return []   # paper not in S2
        if resp.status_code != 200:
            return []

        payload = resp.json()
        items = payload.get("data") or []   # guard against None
        pmids = []
        for item in items:
            cited = item.get("citedPaper") or {}
            ext_ids = cited.get("externalIds") or {}
            pmid = ext_ids.get("PubMed", "")
            if pmid:
                pmids.append(pmid)
        return pmids

    return []   # all retries exhausted


# ─────────────────────────────────────────────────────────────────────────────
# Enrichment routine
# ─────────────────────────────────────────────────────────────────────────────

def _get_papers_needing_enrichment() -> list[dict]:
    """Papers that have a PMID but no s2id (not yet enriched)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, pmid, doi, abstract FROM papers WHERE pmid IS NOT NULL AND s2id IS NULL"
        ).fetchall()
    return [dict(r) for r in rows]


def _build_s2_ids(papers: list[dict]) -> list[str]:
    """Build S2-style IDs: prefer PMID, fallback DOI."""
    ids = []
    for p in papers:
        if p.get("pmid"):
            ids.append(f"PMID:{p['pmid']}")
        elif p.get("doi"):
            ids.append(f"DOI:{p['doi']}")
    return ids


def enrich_from_s2(fetch_citations: bool = True) -> None:
    """
    Enrich all papers in DB that don't yet have S2 data.
    Updates: s2id, citation_count, open_access, abstract (if missing).
    Optionally fetches citation reference lists and inserts citation edges.
    """
    papers = _get_papers_needing_enrichment()
    print(f"[S2] {len(papers)} papers to enrich.")
    if not papers:
        return

    fields = "paperId,externalIds,citationCount,isOpenAccess,abstract,publicationTypes"

    batches = [papers[i:i + _BATCH_SIZE] for i in range(0, len(papers), _BATCH_SIZE)]

    for batch in tqdm(batches, desc="[S2] Enriching", unit="batch"):
        s2_ids = _build_s2_ids(batch)
        try:
            results: list = _batch_fetch(s2_ids, fields)
        except Exception as e:
            print(f"  [S2] Batch error: {e}. Skipping.")
            time.sleep(5)
            continue

        with get_conn() as conn:
            for paper_data, s2_result in zip(batch, results):
                if not s2_result:
                    continue
                s2id = s2_result.get("paperId", "")
                citation_count = s2_result.get("citationCount", 0)
                open_access = int(s2_result.get("isOpenAccess", False))

                # Fill abstract if empty
                s2_abstract = s2_result.get("abstract", "") or ""
                update_abstract = (
                    not (paper_data.get("abstract") or "").strip()
                    and s2_abstract.strip()
                )

                if update_abstract:
                    conn.execute(
                        "UPDATE papers SET s2id=?, citation_count=?, open_access=?, abstract=? WHERE id=?",
                        (s2id, citation_count, open_access, s2_abstract, paper_data["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE papers SET s2id=?, citation_count=?, open_access=? WHERE id=?",
                        (s2id, citation_count, open_access, paper_data["id"]),
                    )

        time.sleep(_RATE_DELAY)

    # ── Fetch citation reference edges ────────────────────────────────────
    if not fetch_citations:
        print("[S2] Skipping citation edge fetch.")
        return

    with get_conn() as conn:
        s2_papers = conn.execute(
            "SELECT pmid, s2id FROM papers WHERE s2id IS NOT NULL"
        ).fetchall()

    # Base delay between requests. With an S2 API key the limit is 1 req/s
    # for the /references endpoint; without a key it is ~1 req/s as well.
    # We use 1.1 s to stay safely under the limit.
    _REF_DELAY = 1.1 if not config.S2_API_KEY else 1.1

    print(f"[S2] Fetching reference edges for {len(s2_papers)} papers...")
    for row in tqdm(s2_papers, desc="[S2] Citations", unit="paper"):
        citing_pmid = row["pmid"]
        s2id = row["s2id"]
        try:
            cited_pmids = _get_paper_references(s2id)
            for cited_pmid in cited_pmids:
                upsert_citation(citing_pmid, cited_pmid)
        except Exception as e:
            print(f"\n  [S2] Ref fetch error for {s2id}: {e}")
        time.sleep(_REF_DELAY)

    print("[S2] Enrichment complete.")


if __name__ == "__main__":
    from utils.db import init_db
    init_db()
    enrich_from_s2(fetch_citations=True)
