"""Generate topic summaries for expansion candidates already present in the DB."""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MULTIMODAL_DIR = ROOT / "multimodal-method-summary"
if str(MULTIMODAL_DIR) not in sys.path:
    sys.path.insert(0, str(MULTIMODAL_DIR))

from generate_summaries import (  # noqa: E402
    REQUIRED_HEADINGS,
    USER_TEMPLATE,
    build_paper_text,
    call_llm,
    complete,
    config,
    paper_record,
)

TOPICS = {
    "multimodal": "multimodal-method-summary",
    "segmentation": "segmentation-method-summary",
    "virtual-staining": "virtual-staining-method-summary",
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def output_path(output_dir: Path, record: dict) -> Path:
    title = re.sub(r'[<>:"/\\|?*]', "_", record["title"])
    title = re.sub(r"\s+", " ", title).strip().rstrip(".")[:120]
    return output_dir / f"PMID_{record['pmid']}_{title}.md"


def generate_one(topic_dir: Path, pmid: str, force: bool) -> dict:
    output_dir = topic_dir / "method_summaries"
    record = paper_record(pmid)
    target = output_path(output_dir, record)
    if not force and complete(target):
        return {"pmid": pmid, "status": "skipped", "file": target.name}
    paper_text = build_paper_text(record)
    if len(paper_text) < 1500:
        raise RuntimeError(f"DB evidence too small: {len(paper_text)} chars")
    metadata = {
        "pmid": record.get("pmid"), "doi": record.get("doi"),
        "title": record.get("title"), "authors": record.get("authors"),
        "year": record.get("year"), "journal": record.get("journal_name"),
        "full_text_status": record.get("full_text_status"),
        "section_count": len(record.get("sections") or []),
        "prompt_evidence_chars": len(paper_text),
    }
    content = call_llm(USER_TEMPLATE.format(
        metadata=json.dumps(metadata, ensure_ascii=False, indent=2),
        paper_text=paper_text,
    ))
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in content]
    if missing:
        raise RuntimeError(f"missing headings: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "pmid": pmid, "status": "generated", "file": target.name,
        "chars": len(content), "source": "local_db_fulltext",
        "source_sections": len(record.get("sections") or []),
        "prompt_evidence_chars": len(paper_text),
    }


def merge_manifest(topic_dir: Path, rows: list[dict]) -> None:
    path = topic_dir / "summary_manifest.json"
    current = {"model": config.LLM_MODEL_AGENT, "results": []}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    by_pmid = {str(row["pmid"]): row for row in current.get("results", [])}
    for row in rows:
        by_pmid[str(row["pmid"])] = row
    current["model"] = config.LLM_MODEL_AGENT
    current["results"] = sorted(by_pmid.values(), key=lambda row: str(row["pmid"]))
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", choices=TOPICS, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    topic_dir = ROOT / TOPICS[args.topic]
    candidates = read_jsonl(topic_dir / "expansion_candidates.jsonl")
    pmids = [str(row["pmid"]) for row in candidates
             if row.get("pmid") and row.get("full_text_status") in {"available", "pdf_available"}]
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(generate_one, topic_dir, pmid, args.force): pmid for pmid in pmids}
        for future in as_completed(futures):
            pmid = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {"pmid": pmid, "status": "failed", "error": str(exc)}
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    merge_manifest(topic_dir, results)
    failed = [row for row in results if row["status"] == "failed"]
    print(f"completed={len(results) - len(failed)} failed={len(failed)}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
