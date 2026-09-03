"""Generate template-aligned summaries for any curated topic project.

The project directory must contain ``selected_papers.jsonl`` with a PMID per row.
Metadata and evidence text are read from the local KG database; results are
checkpointed under ``method_summaries`` and merged into ``summary_manifest.json``.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MULTIMODAL = ROOT / "multimodal-method-summary"
if str(MULTIMODAL) not in sys.path:
    sys.path.insert(0, str(MULTIMODAL))

from generate_summaries import (  # noqa: E402
    REQUIRED_HEADINGS,
    USER_TEMPLATE,
    build_paper_text,
    call_llm,
    config,
    paper_record,
)


def selected_pmids(project_dir: Path) -> list[str]:
    rows = [
        json.loads(line)
        for line in (project_dir / "selected_papers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [str(row["pmid"]) for row in rows]


def output_path(project_dir: Path, record: dict) -> Path:
    import re

    title = re.sub(r'[<>:"/\\|?*]', "_", record["title"])
    title = re.sub(r"\s+", " ", title).strip().rstrip(".")[:120]
    return project_dir / "method_summaries" / f"PMID_{record['pmid']}_{title}.md"


def complete(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 2500:
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return all(heading in text for heading in REQUIRED_HEADINGS)


def generate_one(project_dir: Path, pmid: str, force: bool) -> dict:
    record = paper_record(pmid)
    target = output_path(project_dir, record)
    if not force and complete(target):
        return {"pmid": pmid, "status": "skipped", "file": target.name}
    metadata = {
        "pmid": record.get("pmid"),
        "doi": record.get("doi"),
        "title": record.get("title"),
        "authors": record.get("authors"),
        "year": record.get("year"),
        "journal": record.get("journal_name"),
        "full_text_status": record.get("full_text_status"),
        "section_count": len(record.get("sections") or []),
        "section_chars": sum(len(row.get("content") or "") for row in record.get("sections") or []),
    }
    prompt = USER_TEMPLATE.format(
        metadata=json.dumps(metadata, ensure_ascii=False, indent=2),
        paper_text=build_paper_text(record),
    )
    content = call_llm(prompt)
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in content]
    if missing:
        raise RuntimeError(f"PMID {pmid} missing headings: {missing}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "pmid": pmid,
        "status": "generated",
        "file": target.name,
        "chars": len(content),
        "source_sections": metadata["section_count"],
        "source_chars": metadata["section_chars"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--pmid", action="append")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    project_dir = args.project_dir.resolve()
    pmids = args.pmid or selected_pmids(project_dir)
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(generate_one, project_dir, pmid, args.force): pmid for pmid in pmids
        }
        for future in as_completed(futures):
            pmid = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {"pmid": pmid, "status": "failed", "error": str(exc)}
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    results.sort(key=lambda row: pmids.index(row["pmid"]))
    manifest = project_dir / "summary_manifest.json"
    old: list[dict] = []
    if manifest.exists():
        old = json.loads(manifest.read_text(encoding="utf-8")).get("results", [])
    by_pmid = {row["pmid"]: row for row in old}
    by_pmid.update({row["pmid"]: row for row in results})
    manifest.write_text(
        json.dumps(
            {"model": config.LLM_MODEL_AGENT, "results": sorted(by_pmid.values(), key=lambda r: r["pmid"])},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    failed = [row for row in results if row["status"] == "failed"]
    print(f"completed={len(results)-len(failed)} failed={len(failed)}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
