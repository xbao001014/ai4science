"""Generate template-aligned summaries for manually supplied topic PDFs.

The topic is selected explicitly. PDF discovery is PMID-based, while metadata
comes from the read-only project database. Each completed paper is checkpointed
and merged into the topic summary manifest.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
MULTIMODAL_DIR = ROOT / "multimodal-method-summary"
if str(MULTIMODAL_DIR) not in sys.path:
    sys.path.insert(0, str(MULTIMODAL_DIR))

from generate_summaries import (  # noqa: E402
    REQUIRED_HEADINGS,
    USER_TEMPLATE,
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

PAGE_KEYWORDS = (
    "method", "materials", "architecture", "framework", "training",
    "implementation", "experiment", "results", "ablation", "comparison",
    "dataset", "cohort", "limitation", "discussion", "appendix",
)


def pdf_map(pdf_dir: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for path in sorted(pdf_dir.glob("*.pdf")):
        match = re.match(r"(\d{7,9})(?:_|\.|$)", path.name)
        if match and "supplement" not in path.stem.lower():
            mapping[match.group(1)] = path
    return mapping


def extract_pdf_text(path: Path, max_chars: int = 72000) -> tuple[str, int, int]:
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    source_chars = sum(len(text) for text in pages)
    if source_chars < 1500:
        raise RuntimeError(f"PDF text extraction too small: {source_chars} chars")

    chunks = [f"[PDF page {i + 1}]\n{text}" for i, text in enumerate(pages) if text]
    if sum(map(len, chunks)) <= max_chars:
        return "\n\n".join(chunks), len(reader.pages), source_chars

    chosen = {0, 1, max(0, len(pages) - 2), max(0, len(pages) - 1)}
    ranked: list[tuple[int, int]] = []
    for index, text in enumerate(pages):
        lowered = text.lower()
        ranked.append((-sum(lowered.count(word) for word in PAGE_KEYWORDS), index))
    used = sum(len(f"[PDF page {i + 1}]\n{pages[i]}") for i in chosen if pages[i])
    for _, index in sorted(ranked):
        if index in chosen or not pages[index]:
            continue
        chunk = f"[PDF page {index + 1}]\n{pages[index]}"
        if used + len(chunk) <= max_chars:
            chosen.add(index)
            used += len(chunk)
    selected = [f"[PDF page {i + 1}]\n{pages[i]}" for i in sorted(chosen) if pages[i]]
    return "\n\n".join(selected), len(reader.pages), source_chars


def output_path(output_dir: Path, record: dict) -> Path:
    title = re.sub(r'[<>:"/\\|?*]', "_", record["title"])
    title = re.sub(r"\s+", " ", title).strip().rstrip(".")[:120]
    return output_dir / f"PMID_{record['pmid']}_{title}.md"


def generate_one(topic_dir: Path, pmid: str, pdf_path: Path, force: bool) -> dict:
    output_dir = topic_dir / "method_summaries"
    record = paper_record(pmid)
    target = output_path(output_dir, record)
    if not force and complete(target):
        return {"pmid": pmid, "status": "skipped", "file": target.name}

    paper_text, page_count, source_chars = extract_pdf_text(pdf_path)
    metadata = {
        "pmid": record.get("pmid"),
        "doi": record.get("doi"),
        "title": record.get("title"),
        "authors": record.get("authors"),
        "year": record.get("year"),
        "journal": record.get("journal_name"),
        "full_text_status": "manual PDF verified",
        "pdf_file": pdf_path.name,
        "pdf_pages": page_count,
        "pdf_extracted_chars": source_chars,
        "prompt_evidence_chars": len(paper_text),
    }
    prompt = USER_TEMPLATE.format(
        metadata=json.dumps(metadata, ensure_ascii=False, indent=2),
        paper_text=paper_text,
    )
    content = call_llm(prompt)
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in content]
    if missing:
        raise RuntimeError(f"missing headings: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "pmid": pmid,
        "status": "generated",
        "file": target.name,
        "chars": len(content),
        "source": "manual_pdf",
        "source_file": pdf_path.name,
        "source_pages": page_count,
        "source_chars": source_chars,
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
    parser.add_argument("--pmid", action="append")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    topic_dir = ROOT / TOPICS[args.topic]
    mapping = pdf_map(topic_dir / "manual_papers")
    pmids = args.pmid or list(mapping)
    missing = [pmid for pmid in pmids if pmid not in mapping]
    if missing:
        raise SystemExit(f"missing PDFs for PMIDs: {', '.join(missing)}")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(generate_one, topic_dir, pmid, mapping[pmid], args.force): pmid
            for pmid in pmids
        }
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
