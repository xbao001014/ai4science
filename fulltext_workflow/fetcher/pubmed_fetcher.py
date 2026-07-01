"""
fetcher/pubmed_fetcher.py
Fetch literature from PubMed via Entrez (same query groups as main pipeline).
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

from Bio import Entrez
from tqdm import tqdm

import config
from db.schema import (
    get_conn,
    link_paper_author,
    link_paper_journal,
    upsert_author,
    upsert_journal,
    upsert_paper,
)

Entrez.email = config.PUBMED_EMAIL
Entrez.api_key = config.PUBMED_API_KEY or None

_BATCH_SIZE = 200
_RATE_DELAY = 0.34


def _existing_pmids() -> set[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT pmid FROM papers WHERE pmid IS NOT NULL").fetchall()
    return {r["pmid"] for r in rows}


def _build_date_filter() -> str:
    return f"{config.SEARCH_YEAR_START}/01/01:{config.SEARCH_YEAR_END}/12/31[PDAT]"


def _build_search_term(query: str, since_days: int | None = None) -> str:
    """Compose PubMed query: topic + publication-year window + optional EDAT window."""
    parts = [f"({query})", f"({_build_date_filter()})"]
    days = since_days if since_days is not None else config.FETCH_EDAT_DAYS
    if days and days > 0:
        parts.append(f'("last {int(days)} days"[EDAT])')
    return " AND ".join(parts)


def _search_pmids(query: str, max_results: int, since_days: int | None = None) -> list[str]:
    full_query = _build_search_term(query, since_days)
    esearch_kwargs: dict[str, Any] = {
        "db": "pubmed",
        "term": full_query,
        "retmax": max_results,
        "usehistory": "y",
    }
    days = since_days if since_days is not None else config.FETCH_EDAT_DAYS
    if days and days > 0:
        esearch_kwargs["sort"] = "pub_date"
        esearch_kwargs["sort_order"] = "desc"
    handle = Entrez.esearch(**esearch_kwargs)
    record = Entrez.read(handle)
    handle.close()
    return list(record.get("IdList", []))


def _parse_date(article: ET.Element) -> tuple[str, int]:
    pub_date_el = article.find(".//PubDate")
    if pub_date_el is None:
        return "", 0
    year = pub_date_el.findtext("Year", "")
    month = pub_date_el.findtext("Month", "01")
    day = pub_date_el.findtext("Day", "01")
    month_map = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    }
    month_num = month_map.get(month, month.zfill(2) if month.isdigit() else "01")
    day_num = day.zfill(2) if day.isdigit() else "01"
    iso_date = f"{year}-{month_num}-{day_num}" if year else ""
    return iso_date, int(year) if year.isdigit() else 0


def _parse_single_article(
    medline_citation: ET.Element, pub_med_data: ET.Element
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    data["pmid"] = medline_citation.findtext("PMID", "")

    article = medline_citation.find("Article")
    if article is None:
        return data

    data["title"] = article.findtext("ArticleTitle", "").strip()

    abstract_parts = article.findall(".//AbstractText")
    abstract_texts = []
    for part in abstract_parts:
        label = part.get("Label", "")
        text = "".join(part.itertext()).strip()
        if label:
            abstract_texts.append(f"{label}: {text}")
        else:
            abstract_texts.append(text)
    data["abstract"] = " ".join(abstract_texts).strip()

    pub_date_str, year_int = _parse_date(article)
    data["pub_date"] = pub_date_str
    data["year"] = year_int

    journal_el = article.find("Journal")
    if journal_el is not None:
        data["journal_name"] = journal_el.findtext("Title", "")
        data["journal_abbr"] = journal_el.findtext("ISOAbbreviation", "")
        issn_el = journal_el.find("ISSN")
        data["issn"] = issn_el.text if issn_el is not None else ""

    doi = ""
    for id_el in pub_med_data.findall(".//ArticleId"):
        if id_el.get("IdType") == "doi":
            doi = id_el.text or ""
            break
    data["doi"] = doi.strip()

    pub_types = [pt.text for pt in medline_citation.findall(".//PublicationType") if pt.text]
    data["pub_types"] = pub_types

    mesh_terms = [
        mh.findtext("DescriptorName", "")
        for mh in medline_citation.findall(".//MeshHeading")
    ]
    data["mesh_terms"] = [m for m in mesh_terms if m]

    keywords = [kw.text for kw in medline_citation.findall(".//Keyword") if kw.text]
    data["keywords"] = keywords

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
                parsed = _parse_single_article(
                    medline, pubmed_data or ET.Element("PubmedData")
                )
                if parsed.get("title"):
                    results.append(parsed)
            except Exception as e:
                pmid = medline.findtext("PMID", "?")
                print(f"  [WARN] Parse error for PMID {pmid}: {e}")
    return results


def _store_articles(articles: list[dict[str, Any]], group_name: str, existing: set[str]) -> None:
    for art in articles:
        art["source_queries"] = [group_name]
        art["full_text_status"] = "pending"
        paper_id = upsert_paper(art)

        if art.get("journal_name"):
            jid = upsert_journal(
                art["journal_name"],
                art.get("journal_abbr", ""),
                art.get("issn", ""),
            )
            link_paper_journal(paper_id, jid)

        for order, author in enumerate(art.get("authors", []), start=1):
            aid = upsert_author(
                author["name"],
                author.get("affiliation", ""),
                author.get("orcid", ""),
            )
            link_paper_author(paper_id, aid, order)

        existing.add(art.get("pmid", ""))


def fetch_all_queries(resume: bool = True, since_days: int | None = None) -> None:
    """Run all enabled query groups from search_queries.py."""
    existing = _existing_pmids() if resume else set()
    groups = config.get_enabled_groups()
    days = since_days if since_days is not None else config.FETCH_EDAT_DAYS
    scope = (
        f"last {days} days [EDAT], years {config.SEARCH_YEAR_START}-{config.SEARCH_YEAR_END}"
        if days and days > 0
        else f"years {config.SEARCH_YEAR_START}-{config.SEARCH_YEAR_END}"
    )
    print(
        f"[PubMed] {len(existing)} papers already in DB — "
        f"{len(groups)} query groups, {scope}."
    )

    for group in groups:
        name = group["name"]
        query = group["query"]
        max_results = group.get("max_results", config.MAX_RESULTS_PER_QUERY)
        print(f"\n[PubMed] Query group: {name}")
        print(f"  Query: {query[:120]}...")
        if days and days > 0:
            print(f"  EDAT window: last {days} days")

        all_pmids = _search_pmids(query, max_results, since_days=days)
        new_pmids = [p for p in all_pmids if p not in existing]
        print(f"  Found {len(all_pmids)} PMIDs, {len(new_pmids)} new to fetch.")

        if not new_pmids:
            continue

        batches = [new_pmids[i : i + _BATCH_SIZE] for i in range(0, len(new_pmids), _BATCH_SIZE)]
        for batch in tqdm(batches, desc=f"  Fetching {name}", unit="batch"):
            try:
                articles = _fetch_batch(batch)
                _store_articles(articles, name, existing)
            except Exception as e:
                print(f"\n  [ERROR] Batch failed: {e}. Retrying after 5s...")
                time.sleep(5)
                try:
                    articles = _fetch_batch(batch)
                    _store_articles(articles, name, existing)
                except Exception as e2:
                    print(f"  [ERROR] Retry failed: {e2}.")

            time.sleep(_RATE_DELAY)

    print("\n[PubMed] Fetch complete.")
