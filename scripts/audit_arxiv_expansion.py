"""Bounded arXiv spot check for pathology AI method preprints."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fulltext_workflow/output/source_expansion_2026-09-23"
ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
ARXIV = "{http://arxiv.org/schemas/atom}"

QUERIES = {
    "pathology_foundation_model": 'all:"pathology" AND all:"foundation model"',
    "wsi_weak_supervision": 'all:"whole slide image" AND all:"weakly supervised"',
    "histopathology_deep_learning": 'all:"histopathology" AND all:"deep learning"',
    "pathology_vision_language": 'all:"digital pathology" AND all:"vision language"',
    "virtual_staining": 'all:"virtual staining" AND all:"deep learning"',
    "spatial_transcriptomics": 'all:"spatial transcriptomics" AND all:"deep learning"',
}


def title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"<[^>]+>", " ", value).lower())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{(ROOT / 'fulltext_workflow/data/kg_fulltext.db').resolve()}?mode=ro", uri=True) as conn:
        known_dois = {(row[0] or "").strip().lower() for row in conn.execute("SELECT doi FROM papers WHERE doi IS NOT NULL")}
        known_titles = {title_key(row[0]) for row in conn.execute("SELECT title FROM papers")}
    epmc = [json.loads(x) for x in (OUT / "europe_pmc_candidates.jsonl").open(encoding="utf-8")]
    epmc_titles = {title_key(row["title"]) for row in epmc}
    epmc_dois = {row["doi"] for row in epmc if row["doi"]}

    records = {}
    counts = []
    for name, query in QUERIES.items():
        start = 0
        total = 0
        fetched = 0
        while start < min(total or 1, 1000):
            response = requests.get("https://export.arxiv.org/api/query", params={
                "search_query": query, "start": start, "max_results": 200,
                "sortBy": "relevance", "sortOrder": "descending",
            }, timeout=90)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            total_el = root.find(f"{OPENSEARCH}totalResults")
            total = int(total_el.text) if total_el is not None else 0
            entries = root.findall(f"{ATOM}entry")
            if not entries:
                break
            for entry in entries:
                arxiv_id = (entry.findtext(f"{ATOM}id") or "").rsplit("/", 1)[-1].split("v")[0]
                title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
                abstract = " ".join((entry.findtext(f"{ATOM}summary") or "").split())
                published = entry.findtext(f"{ATOM}published") or ""
                if not ("2015" <= published[:4] <= "2026"):
                    continue
                doi = (entry.findtext(f"{ARXIV}doi") or "").strip().lower()
                if arxiv_id not in records:
                    records[arxiv_id] = {
                        "arxiv_id": arxiv_id, "doi": doi, "title": title,
                        "abstract": abstract, "published": published[:10], "hit_groups": [],
                    }
                if name not in records[arxiv_id]["hit_groups"]:
                    records[arxiv_id]["hit_groups"].append(name)
                fetched += 1
            start += len(entries)
            time.sleep(3)
        counts.append({"group": name, "total_results_all_years": total, "fetched_in_scope": fetched, "capped": total > start})
        print(name, total, fetched, flush=True)

    status_counts = Counter()
    for row in records.values():
        key = title_key(row["title"])
        doi = row["doi"]
        if (doi and doi in known_dois) or key in known_titles:
            status = "already_in_db_exact_title_or_doi"
        elif (doi and doi in epmc_dois) or key in epmc_titles:
            status = "already_in_europe_pmc_exact_title_or_doi"
        else:
            status = "new_arxiv_candidate_no_pmid"
        row["audit_status"] = status
        status_counts[status] += 1

    with (OUT / "arxiv_candidates.jsonl").open("w", encoding="utf-8") as out:
        for row in records.values():
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    (OUT / "arxiv_summary.json").write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "query_counts": counts, "unique_records": len(records), "status_counts": dict(status_counts),
    }, indent=2), encoding="utf-8")
    print(dict(status_counts), flush=True)


if __name__ == "__main__":
    main()
