"""
fetcher/pmc_fetcher.py
Resolve PubMed -> PMC links and fetch full text via Europe PMC REST API
(with Entrez elink as fallback). Parse JATS into document_sections.
"""
from __future__ import annotations

import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from typing import Any

import requests
from Bio import Entrez
from tqdm import tqdm

import config
from db.schema import (
    delete_paper_sections,
    get_papers_needing_fulltext,
    insert_sections,
    mark_fulltext_status,
)

Entrez.email = config.PUBMED_EMAIL
Entrez.api_key = config.PUBMED_API_KEY or None

_RATE_DELAY = 0.5
_EPMC_BATCH = 25
_ELINK_BATCH = 25
_EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_EPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
_TIMEOUT = 60
_ENTREZ_TIMEOUT = 90


@contextmanager
def _entrez_timeout(seconds: float):
    """Biopython Entrez uses urllib without a default socket timeout — can hang forever."""
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old)

_SECTION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("introduction", ["introduction", "background", "overview"]),
    ("methods", ["method", "material", "patient", "study design", "experimental"]),
    ("results", ["result", "finding", "outcome"]),
    ("discussion", ["discussion", "interpretation"]),
    ("limitations", ["limitation", "weakness", "shortcoming"]),
    ("future_work", ["future work", "future direction", "perspective", "conclusion"]),
]


def _text_content(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _classify_section(title: str, sec_type_attr: str) -> str:
    combined = f"{sec_type_attr} {title}".lower()
    for section_type, keywords in _SECTION_KEYWORDS:
        for kw in keywords:
            if kw in combined:
                return section_type
    return "other"


def _parse_abstract_sections(root: ET.Element) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    abstract_el = root.find(".//abstract")
    if abstract_el is None:
        return sections

    parts = abstract_el.findall("sec")
    if parts:
        for idx, sec in enumerate(parts):
            title = _text_content(sec.find("title"))
            content = _text_content(sec)
            sections.append(
                {
                    "section_type": _classify_section(title, sec.get("sec-type", "")),
                    "title": title or "Abstract section",
                    "content": content,
                    "order_idx": idx,
                }
            )
    else:
        content = _text_content(abstract_el)
        if content:
            sections.append(
                {
                    "section_type": "abstract",
                    "title": "Abstract",
                    "content": content,
                    "order_idx": 0,
                }
            )
    return sections


def _parse_body_sections(body: ET.Element, start_order: int) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    order = start_order

    def walk(sec_el: ET.Element, depth: int = 0) -> None:
        nonlocal order
        title = _text_content(sec_el.find("title"))
        sec_type_attr = sec_el.get("sec-type", "")

        paras = [_text_content(p) for p in sec_el.findall("p")]
        direct_content = " ".join(p for p in paras if p)

        children = sec_el.findall("sec")
        if direct_content and (depth == 0 or len(direct_content) > 80):
            sections.append(
                {
                    "section_type": _classify_section(title, sec_type_attr),
                    "title": title or f"Section {order}",
                    "content": direct_content,
                    "order_idx": order,
                }
            )
            order += 1

        for child in children:
            walk(child, depth + 1)

    for top_sec in body.findall("sec"):
        walk(top_sec, 0)

    return sections


def _jats_article_ids(root: ET.Element) -> dict[str, str]:
    """Read pmid/doi embedded in JATS (authoritative for the XML body)."""
    ids: dict[str, str] = {}
    article_meta = root.find(".//article-meta")
    if article_meta is None:
        return ids
    for aid in article_meta.findall("article-id"):
        id_type = aid.get("pub-id-type", "")
        text = (aid.text or "").strip()
        if id_type == "pmid" and text:
            ids["pmid"] = text
        elif id_type == "doi" and text:
            ids["doi"] = text.lower()
        elif id_type in ("pmcid", "pmc") and text:
            ids["pmcid"] = text
    return ids


def _jats_matches_paper(root: ET.Element, pmid: str, doi: str | None) -> bool:
    """Reject Europe PMC XML when embedded ids do not match the requested paper."""
    ids = _jats_article_ids(root)
    xml_pmid = ids.get("pmid", "")
    if xml_pmid and xml_pmid != str(pmid):
        return False
    paper_doi = (doi or "").strip().lower()
    xml_doi = ids.get("doi", "")
    if paper_doi and xml_doi and xml_doi != paper_doi:
        return False
    return True


def parse_pmc_jats(xml_bytes: bytes) -> tuple[str, list[dict[str, Any]]]:
    """Return (pmc_id, sections) from PMC/Europe PMC JATS XML."""
    root = ET.fromstring(xml_bytes)
    pmc_id = ""
    article_meta = root.find(".//article-meta")
    if article_meta is not None:
        for aid in article_meta.findall("article-id"):
            if aid.get("pub-id-type") in ("pmcid", "pmc"):
                pmc_id = (aid.text or "").strip()
                break

    sections = _parse_abstract_sections(root)
    body = root.find(".//body")
    if body is not None:
        sections.extend(_parse_body_sections(body, start_order=len(sections)))

    if not sections:
        full_text = _text_content(root)
        if full_text:
            sections.append(
                {
                    "section_type": "other",
                    "title": "Full text",
                    "content": full_text[:50000],
                    "order_idx": 0,
                }
            )

    return pmc_id, sections


def _epmc_lookup_batch(pmids: list[str]) -> dict[str, str]:
    """Return pmid -> pmcid (e.g. PMC10808150) via Europe PMC search."""
    if not pmids:
        return {}
    query = " OR ".join(f"EXT_ID:{p}" for p in pmids)
    full_query = f"({query}) AND SRC:MED AND (HAS_PMC:Y OR IN_PMC:Y)"
    mapping: dict[str, str] = {}

    for attempt in range(3):
        try:
            resp = requests.get(
                _EPMC_SEARCH,
                params={
                    "query": full_query,
                    "format": "json",
                    "pageSize": len(pmids),
                    "resultType": "core",
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            results = resp.json().get("resultList", {}).get("result", [])
            for item in results:
                pmid = str(item.get("pmid", ""))
                pmcid = item.get("pmcid") or ""
                if pmid and pmcid and pmid in pmids:
                    mapping[pmid] = pmcid
            return mapping
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [WARN] Europe PMC lookup failed: {e}")
    return mapping


def _fetch_fulltext_xml(pmcid: str) -> bytes | None:
    url = _EPMC_FULLTEXT.format(pmcid=pmcid)
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            if resp.content and b"<article" in resp.content[:500]:
                return resp.content
            return None
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [WARN] fullTextXML fetch failed for {pmcid}: {e}")
    return None


def _elink_pmid_to_pmc_entrez(pmids: list[str]) -> dict[str, str]:
    """Fallback: NCBI elink pmid -> PMC numeric id."""
    if not pmids:
        return {}
    mapping: dict[str, str] = {}
    for attempt in range(3):
        try:
            with _entrez_timeout(_ENTREZ_TIMEOUT):
                handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmids)
                records = Entrez.read(handle)
                handle.close()
            for record in records:
                src_ids = record.get("IdList", [])
                if not src_ids:
                    continue
                pmid = str(src_ids[0])
                for ls in record.get("LinkSetDb", []):
                    if ls.get("DbTo") == "pmc":
                        for link in ls.get("Link", []):
                            numeric = str(link.get("Id", ""))
                            if numeric:
                                mapping[pmid] = f"PMC{numeric}"
                            break
            return mapping
        except Exception as e:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            else:
                print(f"  [WARN] Entrez elink fallback failed: {e}")
    return mapping


def _store_fulltext(
    pmid: str,
    paper_id: int,
    pmcid: str,
    xml_bytes: bytes,
    cache_xml: bool,
    doi: str | None = None,
) -> bool:
    root = ET.fromstring(xml_bytes)
    ids = _jats_article_ids(root)
    if not _jats_matches_paper(root, pmid, doi):
        xml_pmid = ids.get("pmid", "?")
        xml_doi = ids.get("doi", "?")
        print(
            f"  [WARN] PMID {pmid}: JATS id mismatch "
            f"(xml pmid={xml_pmid}, doi={xml_doi}; requested doi={doi or '?'}). Skipping."
        )
        mark_fulltext_status(paper_id, "jats_unavailable", pmc_id=pmcid)
        return False

    if cache_xml:
        os.makedirs(config.RAW_PMC_DIR, exist_ok=True)
        cache_path = os.path.join(config.RAW_PMC_DIR, f"{pmid}.xml")
        with open(cache_path, "wb") as f:
            f.write(xml_bytes)

    pmc_id, sections = parse_pmc_jats(xml_bytes)
    if not pmc_id:
        pmc_id = pmcid

    if not sections:
        mark_fulltext_status(paper_id, "jats_unavailable", pmc_id=pmc_id)
        return False

    delete_paper_sections(paper_id)
    insert_sections(paper_id, sections)
    mark_fulltext_status(paper_id, "available", pmc_id=pmc_id)
    return True


def fetch_jats_fulltext(cache_xml: bool = True) -> None:
    """Fetch Europe PMC JATS for papers with full_text_status=pending."""
    pending = get_papers_needing_fulltext()
    print(f"[PMC/JATS] {len(pending)} papers need JATS fetch.")

    if not pending:
        return

    pmid_to_paper: dict[str, dict] = {str(r["pmid"]): dict(r) for r in pending}
    all_pmids = list(pmid_to_paper.keys())

    pmid_to_pmcid: dict[str, str] = {}
    epmc_batches = range(0, len(all_pmids), _EPMC_BATCH)
    print(
        f"[PMC/JATS] Resolving PMC IDs via Europe PMC "
        f"({len(all_pmids)} papers, {len(epmc_batches)} batches)…",
        flush=True,
    )
    for i in tqdm(epmc_batches, desc="  Europe PMC lookup", unit="batch"):
        batch = all_pmids[i : i + _EPMC_BATCH]
        pmid_to_pmcid.update(_epmc_lookup_batch(batch))
        time.sleep(_RATE_DELAY)

    missing = [p for p in all_pmids if p not in pmid_to_pmcid]
    if missing:
        elink_batches = range(0, len(missing), _ELINK_BATCH)
        print(
            f"[PMC/JATS] Entrez elink fallback for {len(missing)} papers "
            f"({len(elink_batches)} batches, timeout={_ENTREZ_TIMEOUT}s)…",
            flush=True,
        )
        for i in tqdm(elink_batches, desc="  Entrez elink", unit="batch"):
            batch = missing[i : i + _ELINK_BATCH]
            pmid_to_pmcid.update(_elink_pmid_to_pmc_entrez(batch))
            time.sleep(_RATE_DELAY)

    print(f"[PMC] {len(pmid_to_pmcid)} / {len(all_pmids)} papers linked to PMC.")

    fetched = 0
    for pmid, paper in tqdm(pmid_to_paper.items(), desc="  Fetching full text", unit="paper"):
        paper_id = paper["id"]
        pmcid = pmid_to_pmcid.get(pmid)

        if not pmcid:
            mark_fulltext_status(paper_id, "jats_unavailable")
            continue

        xml_bytes = _fetch_fulltext_xml(pmcid)
        if not xml_bytes:
            mark_fulltext_status(paper_id, "jats_unavailable", pmc_id=pmcid)
            continue

        try:
            if _store_fulltext(
                pmid, paper_id, pmcid, xml_bytes, cache_xml, doi=paper.get("doi")
            ):
                fetched += 1
        except Exception as e:
            print(f"  [WARN] PMID {pmid} parse failed: {e}")
            mark_fulltext_status(paper_id, "jats_unavailable", pmc_id=pmcid)

        time.sleep(0.2)

    print(f"[PMC/JATS] JATS fetch complete. {fetched} papers with sections stored.")


# Backward-compatible alias
fetch_all_fulltext = fetch_jats_fulltext
