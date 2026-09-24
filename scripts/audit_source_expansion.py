"""Audit Europe PMC discovery against the local pathology-AI paper database.

Read-only for the KG database. Writes candidate JSONL and a summary JSON.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from search_queries import get_enabled_groups  # noqa: E402

API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def epmc_query(pubmed_query: str, start: int, end: int) -> str:
    # Keep Boolean structure; Europe PMC's TITLE_ABS is the closest field to
    # PubMed Title/Abstract. The two search engines still tokenize differently.
    tokens = re.split(r"(\s+(?:AND|OR|NOT)\s+|[()])", pubmed_query)
    result = []
    for token in tokens:
        if "[Title/Abstract]" in token:
            term = token.strip().replace("[Title/Abstract]", "").strip('"')
            result.append(f'TITLE_ABS:"{term}"')
        else:
            result.append(token)
    return "".join(result) + f" AND FIRST_PDATE:[{start}-01-01 TO {end}-12-31]"


def get_json(session: requests.Session, params: dict) -> dict:
    for attempt in range(5):
        try:
            response = session.get(API, params=params, timeout=90)
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(3 * 2**attempt, 30))
                continue
            response.raise_for_status()
            payload = response.json()
            # Europe PMC occasionally responds HTTP 200 with only
            # {"version":"6.9"} for complex searches. This is not zero hits.
            if "hitCount" not in payload:
                time.sleep(min(3 * 2**attempt, 30))
                continue
            return payload
        except (requests.RequestException, ValueError):
            if attempt == 4:
                raise
            time.sleep(min(3 * 2**attempt, 30))
    raise RuntimeError("Europe PMC request failed")


def normalize_doi(value: str | None) -> str:
    return (value or "").strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "fulltext_workflow/data/kg_fulltext.db")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-per-group", type=int, default=2000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as conn:
        known_pmids = {str(row[0]) for row in conn.execute("SELECT pmid FROM papers WHERE pmid IS NOT NULL")}
        known_dois = {normalize_doi(row[0]) for row in conn.execute("SELECT doi FROM papers WHERE doi IS NOT NULL AND doi != ''")}

    session = requests.Session()
    session.headers.update({"User-Agent": "PathologyAI-KG-source-audit/1.0 (research audit)"})
    grouped_counts = []
    records: dict[str, dict] = {}
    errors = []
    for group in get_enabled_groups():
        name = group["name"]
        query = epmc_query(group["query"], args.start, args.end)
        cap = min(int(group.get("max_results", args.limit_per_group)), args.limit_per_group)
        fetched = 0
        cursor = "*"
        hit_count = None
        try:
            while fetched < cap:
                payload = get_json(session, {
                    "query": query, "format": "json", "resultType": "core",
                    "pageSize": min(200, cap - fetched), "cursorMark": cursor,
                })
                hit_count = payload.get("hitCount", 0)
                batch = payload.get("resultList", {}).get("result", [])
                if not batch:
                    break
                for item in batch:
                    pmid = str(item.get("pmid") or "").strip()
                    doi = normalize_doi(item.get("doi"))
                    source = item.get("source") or ""
                    external_id = str(item.get("id") or "")
                    key = f"pmid:{pmid}" if pmid else (f"doi:{doi}" if doi else f"{source}:{external_id}")
                    row = records.get(key)
                    if row is None:
                        row = {
                            "source": source, "external_id": external_id, "pmid": pmid,
                            "pmcid": item.get("pmcid") or "", "doi": doi,
                            "title": item.get("title") or "",
                            "abstract": re.sub(r"<[^>]+>", " ", item.get("abstractText") or "").strip(),
                            "first_publication_date": item.get("firstPublicationDate") or "",
                            "pub_year": item.get("pubYear") or "",
                            "is_open_access": item.get("isOpenAccess") or "",
                            "hit_groups": [],
                        }
                        records[key] = row
                    row["hit_groups"].append(name)
                fetched += len(batch)
                next_cursor = payload.get("nextCursorMark")
                if fetched >= hit_count or not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
            grouped_counts.append({"group": name, "hit_count": hit_count, "fetched": fetched, "capped": bool(hit_count and hit_count > fetched)})
            print(f"{name}: hits={hit_count}, fetched={fetched}", flush=True)
        except Exception as exc:
            errors.append({"group": name, "error": str(exc), "fetched": fetched})
            print(f"{name}: ERROR {exc}", flush=True)

    counts = Counter()
    by_source = defaultdict(Counter)
    for row in records.values():
        pmid, doi = row["pmid"], row["doi"]
        if (pmid and pmid in known_pmids) or (doi and doi in known_dois):
            status = "already_in_db"
        elif pmid and row["title"] and row["abstract"]:
            status = "new_pmid_with_abstract"
        elif pmid and row["title"]:
            status = "new_pmid_no_abstract"
        elif doi and row["title"] and row["abstract"]:
            status = "new_no_pmid_with_abstract"
        else:
            status = "new_insufficient_metadata"
        row["audit_status"] = status
        counts[status] += 1
        by_source[row["source"]][status] += 1

    candidate_path = args.output / "europe_pmc_candidates.jsonl"
    with candidate_path.open("w", encoding="utf-8") as out:
        for row in sorted(records.values(), key=lambda r: (r["audit_status"], r["pmid"], r["doi"])):
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"year_start": args.start, "year_end": args.end, "enabled_groups": len(get_enabled_groups()), "limit_per_group": args.limit_per_group},
        "database": {"path": str(args.db), "known_pmids": len(known_pmids), "known_dois": len(known_dois)},
        "source": "Europe PMC REST search, resultType=core, TITLE_ABS and FIRST_PDATE",
        "group_counts": grouped_counts,
        "unique_records": len(records),
        "status_counts": dict(counts),
        "source_counts": {k: dict(v) for k, v in by_source.items()},
        "errors": errors,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"unique_records": len(records), "status_counts": counts, "errors": errors}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
