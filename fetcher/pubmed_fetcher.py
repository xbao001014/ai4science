"""
fetcher/pubmed_fetcher.py
Fetch literature from PubMed using Biopython Entrez.

Features:
  - Multiple query groups with configurable date range
  - Batch fetching with rate-limit handling
  - Resume support (skips PMIDs already in DB)
  - Extracts: PMID, DOI, title, abstract, pub_date, journal, ISSN,
              authors+affiliations, MeSH terms, publication types
"""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from typing import Any

from Bio import Entrez
from tqdm import tqdm

import config
from utils.db import (
    get_conn,
    upsert_author,
    upsert_paper,
    link_paper_author,
    upsert_journal,
    link_paper_journal,
)

# Entrez setup
Entrez.email = config.PUBMED_EMAIL
Entrez.api_key = config.PUBMED_API_KEY or None

_BATCH_SIZE = 200          # records per efetch call
_RATE_DELAY = 0.34         # seconds between calls (≤3/s without API key, ≤10/s with)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _existing_pmids() -> set[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT pmid FROM papers WHERE pmid IS NOT NULL").fetchall()
    return {r["pmid"] for r in rows}


def _build_date_filter() -> str:
    return f"{config.SEARCH_YEAR_START}/01/01:{config.SEARCH_YEAR_END}/12/31[PDAT]"


def _search_pmids(query: str, max_results: int) -> list[str]:
    """Run esearch and return list of PMIDs."""
    full_query = f"({query}) AND ({_build_date_filter()})"
    handle = Entrez.esearch(
        db="pubmed",
        term=full_query,
        retmax=max_results,
        usehistory="y",
    )
    record = Entrez.read(handle)
    handle.close()
    return list(record.get("IdList", []))


def _parse_date(article: ET.Element) -> tuple[str, int]:
    """Return (ISO date string, year int) from PubDate element."""
    pub_date_el = article.find(".//PubDate")
    if pub_date_el is None:
        return "", 0
    year = pub_date_el.findtext("Year", "")
    month = pub_date_el.findtext("Month", "01")
    day = pub_date_el.findtext("Day", "01")
    # Convert month abbreviation to number
    month_map = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    }
    month_num = month_map.get(month, month.zfill(2) if month.isdigit() else "01")
    day_num = day.zfill(2) if day.isdigit() else "01"
    iso_date = f"{year}-{month_num}-{day_num}" if year else ""
    return iso_date, int(year) if year.isdigit() else 0


def _parse_single_article(medline_citation: ET.Element, pub_med_data: ET.Element) -> dict[str, Any]:
    """Parse a single MedlineCitation XML element into a dict."""
    data: dict[str, Any] = {}

    # PMID
    data["pmid"] = medline_citation.findtext("PMID", "")

    # Article info
    article = medline_citation.find("Article")
    if article is None:
        return data

    data["title"] = article.findtext("ArticleTitle", "").strip()

    # Abstract (may have multiple AbstractText sections)
    abstract_parts = article.findall(".//AbstractText")
    abstract_texts = []
    for part in abstract_parts:
        label = part.get("Label", "")
        text = part.text or ""
        if label:
            abstract_texts.append(f"{label}: {text}")
        else:
            abstract_texts.append(text)
    data["abstract"] = " ".join(abstract_texts).strip()

    # Publication date
    pub_date_str, year_int = _parse_date(article)
    data["pub_date"] = pub_date_str
    data["year"] = year_int

    # Journal
    journal_el = article.find("Journal")
    if journal_el is not None:
        data["journal_name"] = journal_el.findtext("Title", "")
        data["journal_abbr"] = journal_el.findtext("ISOAbbreviation", "")
        issn_el = journal_el.find("ISSN")
        data["issn"] = issn_el.text if issn_el is not None else ""

    # DOI
    doi = ""
    for id_el in pub_med_data.findall(".//ArticleId"):
        if id_el.get("IdType") == "doi":
            doi = id_el.text or ""
            break
    data["doi"] = doi.strip()

    # Publication types
    pub_types = [pt.text for pt in medline_citation.findall(".//PublicationType") if pt.text]
    data["pub_types"] = pub_types

    # MeSH terms
    mesh_terms = [
        mh.findtext("DescriptorName", "")
        for mh in medline_citation.findall(".//MeshHeading")
    ]
    data["mesh_terms"] = [m for m in mesh_terms if m]

    # Author keywords
    keywords = [
        kw.text for kw in medline_citation.findall(".//Keyword") if kw.text
    ]
    data["keywords"] = keywords

    # Authors
    authors = []
    for author_el in article.findall(".//Author"):
        last = author_el.findtext("LastName", "")
        fore = author_el.findtext("ForeName", "")
        name = f"{last}, {fore}".strip(", ")
        affil_el = author_el.find(".//AffiliationInfo/Affiliation")
        affil = affil_el.text if affil_el is not None else ""
        orcid = ""
        for id_el in author_el.findall("Identifier"):
            if id_el.get("Source") == "ORCID":
                orcid = id_el.text or ""
        if name:
            authors.append({"name": name, "affiliation": affil or "", "orcid": orcid})
    data["authors"] = authors

    return data


def _fetch_batch(pmids: list[str]) -> list[dict[str, Any]]:
    """Efetch a batch of PMIDs and parse them."""
    handle = Entrez.efetch(db="pubmed", id=pmids, rettype="xml", retmode="xml")
    raw_xml = handle.read()
    handle.close()

    root = ET.fromstring(raw_xml)
    results = []
    for pub_article in root.findall("PubmedArticle"):
        medline = pub_article.find("MedlineCitation")
        pubmed_data = pub_article.find("PubmedData")
        if medline is not None:
            try:
                parsed = _parse_single_article(medline, pubmed_data or ET.Element("PubmedData"))
                if parsed.get("title"):
                    results.append(parsed)
            except Exception as e:
                pmid = medline.findtext("PMID", "?")
                print(f"  [WARN] Parse error for PMID {pmid}: {e}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Main fetch routine
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_queries(resume: bool = True) -> None:
    """
    Run all query groups from config, fetch abstracts, and store to SQLite.
    Set resume=False to re-fetch all papers (still does upsert, won't duplicate).
    """
    existing = _existing_pmids() if resume else set()
    print(f"[PubMed] {len(existing)} papers already in DB — will skip those PMIDs.")

    for group in config.get_enabled_groups():
        name = group["name"]
        query = group["query"]
        print(f"\n[PubMed] Query group: {name}")
        print(f"  Query: {query[:120]}...")

        all_pmids = _search_pmids(query, config.MAX_RESULTS_PER_QUERY)
        new_pmids = [p for p in all_pmids if p not in existing]
        print(f"  Found {len(all_pmids)} PMIDs, {len(new_pmids)} new to fetch.")

        if not new_pmids:
            continue

        batches = [new_pmids[i:i + _BATCH_SIZE] for i in range(0, len(new_pmids), _BATCH_SIZE)]
        for batch in tqdm(batches, desc=f"  Fetching {name}", unit="batch"):
            try:
                articles = _fetch_batch(batch)
                for art in articles:
                    art["source_queries"] = [name]
                    paper_id = upsert_paper(art)

                    # Upsert journal and link
                    if art.get("journal_name"):
                        jid = upsert_journal(
                            art["journal_name"],
                            art.get("journal_abbr", ""),
                            art.get("issn", ""),
                        )
                        link_paper_journal(paper_id, jid)

                    # Upsert authors and link
                    for order, author in enumerate(art.get("authors", []), start=1):
                        aid = upsert_author(
                            author["name"],
                            author.get("affiliation", ""),
                            author.get("orcid", ""),
                        )
                        link_paper_author(paper_id, aid, order)

                    existing.add(art.get("pmid", ""))

            except Exception as e:
                print(f"\n  [ERROR] Batch fetch failed: {e}. Retrying after 5s...")
                time.sleep(5)
                try:
                    articles = _fetch_batch(batch)
                    for art in articles:
                        art["source_queries"] = [name]
                        upsert_paper(art)
                except Exception as e2:
                    print(f"  [ERROR] Retry failed: {e2}. Skipping batch.")

            time.sleep(_RATE_DELAY)

    print("\n[PubMed] Fetch complete.")


if __name__ == "__main__":
    from utils.db import init_db
    init_db()
    fetch_all_queries()
