"""Generate template-aligned summaries from manually supplied full-text PDFs.

This complements ``generate_summaries.py``: metadata still comes from the local
knowledge-graph database, while the evidence text is extracted from the verified
PDF named for each PMID. Results are checkpointed and merged into the existing
summary manifest.
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pypdf import PdfReader

from generate_summaries import (
    MANIFEST_PATH,
    OUTPUT_DIR,
    REQUIRED_HEADINGS,
    USER_TEMPLATE,
    call_llm,
    complete,
    config,
    output_path,
    paper_record,
)

PROJECT_DIR = Path(__file__).resolve().parent
PDF_DIR = PROJECT_DIR / "manual_papers"

PDFS = {
    "31797610": "31797610_PAGE-Net_PSB2020.pdf",
    "32881682": "32881682_10.1109_TMI.2020.3021387.pdf",
    "34275655": "34275655_10.1016_j.ygyno.2021.07.015.pdf",
    "35944502": "35944502_10.1016_j.ccell.2022.07.004.pdf",
    "36682215": "36682215_10.1016_j.compmedimag.2022.102176.pdf",
    "37030860": "37030860_10.1109_TMI.2023.3263010.pdf",
    "38504017": "38504017_CONCH_arXiv2307.12914.pdf",
}

PAGE_KEYWORDS = (
    "method", "materials", "architecture", "framework", "fusion", "attention",
    "training", "implementation", "experiment", "results", "ablation",
    "comparison", "dataset", "cohort", "limitation", "discussion", "appendix",
)


def extract_pdf_text(path: Path, max_chars: int = 72000) -> tuple[str, int, int]:
    """Extract page-labelled text, prioritising method/results pages if needed."""
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    source_chars = sum(len(text) for text in pages)

    chunks = [f"[PDF page {i + 1}]\n{text}" for i, text in enumerate(pages) if text]
    if sum(len(chunk) for chunk in chunks) <= max_chars:
        return "\n\n".join(chunks), len(reader.pages), source_chars

    # Always retain the opening pages and references/conclusion tail. Rank the
    # remaining pages for method and experiment evidence, then restore page order.
    chosen = {0, 1, max(0, len(pages) - 2), max(0, len(pages) - 1)}
    ranked: list[tuple[int, int]] = []
    for index, text in enumerate(pages):
        lowered = text.lower()
        score = sum(lowered.count(word) for word in PAGE_KEYWORDS)
        ranked.append((-score, index))

    used = sum(len(chunks_i) for i, chunks_i in enumerate(
        [f"[PDF page {i + 1}]\n{text}" for i, text in enumerate(pages)]
    ) if i in chosen)
    for _, index in sorted(ranked):
        if index in chosen or not pages[index]:
            continue
        page_chunk = f"[PDF page {index + 1}]\n{pages[index]}"
        if used + len(page_chunk) > max_chars:
            continue
        chosen.add(index)
        used += len(page_chunk)

    selected = [
        f"[PDF page {i + 1}]\n{pages[i]}"
        for i in sorted(chosen)
        if pages[i]
    ]
    return "\n\n".join(selected), len(reader.pages), source_chars


def generate_one(pmid: str, force: bool = False) -> dict:
    if pmid not in PDFS:
        raise KeyError(f"No manual PDF mapping for PMID {pmid}")
    pdf_path = PDF_DIR / PDFS[pmid]
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    record = paper_record(pmid)
    target = output_path(record)
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
        raise RuntimeError(f"PMID {pmid} missing headings: {missing}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
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


def merge_manifest(results: list[dict]) -> None:
    current = {"model": config.LLM_MODEL_AGENT, "results": []}
    if MANIFEST_PATH.exists():
        current = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    by_pmid = {row["pmid"]: row for row in current.get("results", [])}
    for row in results:
        by_pmid[row["pmid"]] = row
    current["model"] = config.LLM_MODEL_AGENT
    current["results"] = sorted(by_pmid.values(), key=lambda row: row["pmid"])
    MANIFEST_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pmid", action="append", help="Generate selected PMID(s)")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    pmids = args.pmid or list(PDFS)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(generate_one, pmid, args.force): pmid for pmid in pmids}
        for future in as_completed(futures):
            pmid = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"pmid": pmid, "status": "failed", "error": str(exc)}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)

    results.sort(key=lambda row: pmids.index(row["pmid"]))
    merge_manifest(results)
    failed = [row for row in results if row["status"] == "failed"]
    print(f"completed={len(results) - len(failed)} failed={len(failed)}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
