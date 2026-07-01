"""LLM extraction from PDF sections (PyMuPDF parser, same prompts as JATS channel)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from compare_test.config import PDF_EXTRACTION_CACHE
from compare_test.extract_common import extract_triples_from_sections
from compare_test.pdf_parser import extract_pdf_text, split_into_sections


def _load_cache() -> dict[str, Any]:
    path = Path(PDF_EXTRACTION_CACHE)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {"papers": {}}


def _save_cache(data: dict[str, Any]) -> None:
    path = Path(PDF_EXTRACTION_CACHE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_from_pdf(
    pmid: str,
    title: str,
    pdf_path: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    cache = _load_cache()
    if not force and pmid in cache.get("papers", {}):
        return cache["papers"][pmid]

    full_text = extract_pdf_text(pdf_path)
    sections = split_into_sections(full_text)
    all_triples, section_stats = extract_triples_from_sections(
        title,
        sections,
        granularity="pdf",
    )

    result = {
        "pmid": pmid,
        "pdf_path": pdf_path,
        "parser": "pymupdf",
        "text_chars": len(full_text),
        "section_count": len(sections),
        "sections_parsed": section_stats,
        "triples": all_triples,
    }
    cache.setdefault("papers", {})[pmid] = result
    _save_cache(cache)
    return result
