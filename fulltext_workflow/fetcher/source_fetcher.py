"""Europe PMC and arXiv discovery using the project's enabled topic groups."""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any

import requests

import config
from db.paper_sources import upsert_source_paper
from db.schema import get_conn
from fetcher.pubmed_fetcher import _fetch_batch

EPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"


def translate_query(pubmed_query: str, source: str) -> str:
    """Preserve Boolean groups while mapping PubMed title/abstract fields."""
    if source not in {"europepmc", "arxiv"}:
        raise ValueError(source)
    field = "TITLE_ABS" if source == "europepmc" else "all"
    tokens = re.split(r"(\s+(?:AND|OR|NOT)\s+|[()])", pubmed_query)
    converted = []
    for token in tokens:
        if "[Title/Abstract]" in token:
            phrase = token.strip().replace("[Title/Abstract]", "").strip('"')
            converted.append(f'{field}:"{phrase}"')
        else:
            converted.append(token)
    return "".join(converted)


def matches_title_abstract(pubmed_query: str, title: str, abstract: str) -> bool:
    """Apply the configured Boolean query to candidate title/abstract text."""
    haystack = re.sub(r"[^a-z0-9]+", " ", f"{title} {abstract}".lower())
    haystack = f" {haystack.strip()} "
    query = pubmed_query.replace(" NOT (", " AND NOT (")
    tokens = re.split(r"(\s+(?:AND|OR|NOT)\s+|[()])", query)
    expression = []
    for token in tokens:
        if "[Title/Abstract]" in token:
            phrase = token.strip().replace("[Title/Abstract]", "").strip('"')
            normalized = re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
            expression.append(str(bool(normalized and f" {normalized} " in haystack)))
        else:
            expression.append(token.lower())
    safe = "".join(expression)
    if re.sub(r"\b(?:true|false|and|or|not)\b|[()\s]", "", safe, flags=re.I):
        raise ValueError("Unexpected token in search query")
    return bool(eval(safe, {"__builtins__": {}}, {}))


def pathology_domain_relevant(title: str, abstract: str) -> bool:
    """Reject broad-query hits about speech pathology or generic model failures."""
    text = f"{title} {abstract}".lower()
    cues = (
        "histopatholog", "digital patholog", "computational patholog",
        "pathology image", "pathological image", "pathology report",
        "whole slide", "whole-slide", "wsi", "histology", "histologic",
        "cytolog", "microscop", "tissue", "nuclei", "nucleus",
        "spatial transcriptom", "spatial omics", "pathologist",
    )
    return any(cue in text for cue in cues)


def _get(session: requests.Session, url: str, params: dict[str, Any]) -> requests.Response:
    for attempt in range(5):
        try:
            response = session.get(url, params=params, timeout=90)
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(3 * 2**attempt, 30))
                continue
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(min(3 * 2**attempt, 30))
    raise RuntimeError(f"request failed: {url}")


def _epmc_page(session: requests.Session, query: str, cursor: str, size: int) -> dict:
    params = {"query": query, "format": "json", "resultType": "core", "pageSize": size, "cursorMark": cursor}
    for attempt in range(5):
        payload = _get(session, EPMC_API, params).json()
        if "hitCount" in payload:
            return payload
        # Europe PMC intermittently returns HTTP 200 {"version":"6.9"}.
        time.sleep(min(2 * 2**attempt, 20))
    raise RuntimeError("Europe PMC returned a response without hitCount")


def _clean_markup(value: str | None) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", value or "")).split())


def _epmc_record(item: dict) -> dict:
    first_date = str(item.get("firstPublicationDate") or "")[:10]
    year = int(first_date[:4]) if first_date[:4].isdigit() else None
    return {
        "pmid": str(item.get("pmid") or ""),
        "pmc_id": str(item.get("pmcid") or ""),
        "doi": str(item.get("doi") or ""),
        "title": _clean_markup(item.get("title")),
        "abstract": _clean_markup(item.get("abstractText")),
        "pub_date": first_date,
        "year": year,
        "date_precision": "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", first_date) else "unknown",
        "journal_name": item.get("journalTitle") or "",
        "authors": [
            {"name": author.get("fullName") or ""}
            for author in (item.get("authorList") or {}).get("author", [])
        ],
        "pub_types": ["Preprint"] if item.get("source") == "PPR" else [],
        "open_access": item.get("isOpenAccess") == "Y",
    }


def fetch_europepmc(*, since_days: int = 0, group_name: str | None = None, limit_per_group: int | None = None) -> dict[str, int]:
    """Import MED/PPR records; new MED records are re-fetched from PubMed XML."""
    today = date.today()
    start = date(config.SEARCH_YEAR_START, 1, 1)
    end = min(today, date(config.SEARCH_YEAR_END, 12, 31))
    if since_days > 0:
        start = max(start, today - timedelta(days=since_days))
    if start > end:
        return {"seen": 0, "created": 0, "matched": 0, "skipped": 0}
    with get_conn() as conn:
        known_pmids = {str(row[0]) for row in conn.execute("SELECT pmid FROM papers WHERE pmid IS NOT NULL")}
    session = requests.Session()
    session.headers["User-Agent"] = "PathologyAI-KG/1.0 (research literature discovery)"
    stats = {"seen": 0, "created": 0, "matched": 0, "skipped": 0}
    for group in config.get_enabled_groups():
        if group_name and group["name"] != group_name:
            continue
        cap = min(group.get("max_results", config.MAX_RESULTS_PER_QUERY), limit_per_group or config.MAX_RESULTS_PER_QUERY)
        query = translate_query(group["query"], "europepmc")
        query += f" AND FIRST_PDATE:[{start.isoformat()} TO {end.isoformat()}]"
        cursor, fetched = "*", 0
        while fetched < cap:
            payload = _epmc_page(session, query, cursor, min(200, cap - fetched))
            batch = payload.get("resultList", {}).get("result", [])
            if not batch:
                break
            fresh_pmids = [str(item["pmid"]) for item in batch
                           if item.get("source") == "MED" and item.get("pmid")
                           and str(item["pmid"]) not in known_pmids]
            pubmed_records: dict[str, dict] = {}
            if fresh_pmids:
                try:
                    pubmed_records = {row["pmid"]: row for row in _fetch_batch(list(dict.fromkeys(fresh_pmids)))}
                except Exception as exc:
                    print(f"[Europe PMC] PubMed enrichment failed for {group['name']}: {exc}")
            for item in batch:
                stats["seen"] += 1
                source = item.get("source")
                if source not in {"MED", "PPR"}:
                    stats["skipped"] += 1
                    continue
                external_id = str(item.get("id") or "")
                data = _epmc_record(item)
                if source == "MED" and data["pmid"] in pubmed_records:
                    data.update(pubmed_records[data["pmid"]])
                    data["pmc_id"] = data.get("pmc_id") or str(item.get("pmcid") or "")
                if (not data["title"] or not data["abstract"] or not external_id
                        or not matches_title_abstract(group["query"], data["title"], data["abstract"])
                        or not pathology_domain_relevant(data["title"], data["abstract"])):
                    stats["skipped"] += 1
                    continue
                _, created = upsert_source_paper(
                    data, source="europepmc", external_id=f"{source}:{external_id}", group=group["name"]
                )
                stats["created" if created else "matched"] += 1
                if data["pmid"]:
                    known_pmids.add(data["pmid"])
            fetched += len(batch)
            next_cursor = payload.get("nextCursorMark")
            if fetched >= int(payload.get("hitCount", 0)) or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        print(f"[Europe PMC] {group['name']}: fetched={fetched}, hits={payload.get('hitCount', 0)}")
    return stats


def _arxiv_record(entry: ET.Element) -> tuple[str, dict]:
    url = entry.findtext(f"{ATOM}id") or ""
    arxiv_id = re.sub(r"v\d+$", "", url.rsplit("/", 1)[-1])
    published = (entry.findtext(f"{ATOM}published") or "")[:10]
    categories = [c.get("term", "") for c in entry.findall(f"{ATOM}category") if c.get("term")]
    return arxiv_id, {
        "title": " ".join((entry.findtext(f"{ATOM}title") or "").split()),
        "abstract": " ".join((entry.findtext(f"{ATOM}summary") or "").split()),
        "doi": entry.findtext(f"{ARXIV_NS}doi") or "",
        "pub_date": published,
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "date_precision": "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", published) else "unknown",
        "pub_types": ["Preprint"],
        "keywords": categories,
        "authors": [
            {"name": " ".join((author.findtext(f"{ATOM}name") or "").split())}
            for author in entry.findall(f"{ATOM}author")
        ],
        "open_access": True,
    }


def fetch_arxiv(*, since_days: int = 0, group_name: str | None = None, limit_per_group: int | None = None) -> dict[str, int]:
    """Import arXiv title/abstract records, preserving real arXiv IDs."""
    today = date.today()
    earliest = date(config.SEARCH_YEAR_START, 1, 1)
    latest = min(today, date(config.SEARCH_YEAR_END, 12, 31))
    if since_days > 0:
        earliest = max(earliest, today - timedelta(days=since_days))
    if earliest > latest:
        return {"seen": 0, "created": 0, "matched": 0, "skipped": 0}
    session = requests.Session()
    session.headers["User-Agent"] = "PathologyAI-KG/1.0 (research literature discovery)"
    stats = {"seen": 0, "created": 0, "matched": 0, "skipped": 0}
    for group in config.get_enabled_groups():
        if group_name and group["name"] != group_name:
            continue
        cap = min(group.get("max_results", config.MAX_RESULTS_PER_QUERY), limit_per_group or config.MAX_RESULTS_PER_QUERY)
        query = translate_query(group["query"], "arxiv")
        offset = 0
        while offset < cap:
            response = _get(session, ARXIV_API, {
                "search_query": query, "start": offset,
                "max_results": min(200, cap - offset),
                "sortBy": "submittedDate", "sortOrder": "descending",
            })
            root = ET.fromstring(response.content)
            entries = root.findall(f"{ATOM}entry")
            if not entries:
                break
            older = False
            for entry in entries:
                stats["seen"] += 1
                arxiv_id, data = _arxiv_record(entry)
                pub_date = data["pub_date"]
                if pub_date and pub_date < earliest.isoformat():
                    older = True
                    stats["skipped"] += 1
                    continue
                if (not pub_date or pub_date > latest.isoformat() or not data["title"]
                        or not data["abstract"] or not pathology_domain_relevant(data["title"], data["abstract"])
                        or not matches_title_abstract(
                            group["query"], data["title"], data["abstract"]
                        )):
                    stats["skipped"] += 1
                    continue
                _, created = upsert_source_paper(
                    data, source="arxiv", external_id=arxiv_id, group=group["name"]
                )
                stats["created" if created else "matched"] += 1
            offset += len(entries)
            if older or len(entries) < min(200, cap - (offset - len(entries))):
                break
            time.sleep(3)
        print(f"[arXiv] {group['name']}: fetched={offset}")
    return stats
