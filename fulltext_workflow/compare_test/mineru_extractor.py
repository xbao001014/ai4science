"""LLM extraction from MinerU-parsed PDF sections."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from compare_test.config import MINERU_EXTRACTION_CACHE
from compare_test.extract_common import extract_triples_from_sections
from compare_test.mineru_parser import parse_pdf_with_mineru


def _load_cache() -> dict[str, Any]:
    path = Path(MINERU_EXTRACTION_CACHE)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {"papers": {}}


def _save_cache(data: dict[str, Any]) -> None:
    path = Path(MINERU_EXTRACTION_CACHE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_from_mineru_pdf(
    pmid: str,
    title: str,
    pdf_path: str,
    *,
    force: bool = False,
    lang: str = "en",
    backend: str = "pipeline",
) -> dict[str, Any]:
    cache = _load_cache()
    if not force and pmid in cache.get("papers", {}):
        return cache["papers"][pmid]

    sections, mineru_meta = parse_pdf_with_mineru(
        pdf_path,
        pmid,
        lang=lang,
        backend=backend,
        force=force,
    )
    all_triples, section_stats = extract_triples_from_sections(
        title,
        sections,
        granularity="mineru_pdf",
    )

    result = {
        "pmid": pmid,
        "pdf_path": pdf_path,
        "parser": "mineru",
        "mineru_backend": backend,
        "text_chars": mineru_meta.get("md_chars", 0),
        "section_count": len(sections),
        "sections_parsed": section_stats,
        "triples": all_triples,
        "mineru_meta": mineru_meta,
    }
    cache.setdefault("papers", {})[pmid] = result
    _save_cache(cache)
    return result
