"""MinerU PDF → markdown → document_sections (same taxonomy as JATS parser)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import config
from fetcher.mineru_device import apply_mineru_env

_HEADING_MAP: list[tuple[str, re.Pattern[str]]] = [
    ("abstract", re.compile(r"abstract", re.I)),
    ("introduction", re.compile(r"introduction|background", re.I)),
    ("methods", re.compile(r"methods|materials?\s+and\s+methods|methodology", re.I)),
    ("results", re.compile(r"results|findings", re.I)),
    ("discussion", re.compile(r"discussion", re.I)),
    ("limitations", re.compile(r"limitations?", re.I)),
    (
        "future_work",
        re.compile(r"conclusions?|future\s+work|future\s+directions?", re.I),
    ),
]

_MIN_SECTION_CHARS = 120
_MAX_SECTION_CHARS = 12000


def _classify_heading(title: str) -> str:
    for sec_type, pat in _HEADING_MAP:
        if pat.search(title.strip()):
            return sec_type
    return "other"


def _find_markdown_file(output_dir: Path, stem: str) -> Path | None:
    candidates = [
        output_dir / f"{stem}.md",
        output_dir / stem / f"{stem}.md",
        output_dir / stem / "auto" / f"{stem}.md",
    ]
    for path in candidates:
        if path.is_file():
            return path
    for path in output_dir.rglob("*.md"):
        if path.stem == stem or stem in path.stem:
            return path
    return None


def _clean_md_chunk(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def split_markdown_into_sections(md_text: str) -> list[dict[str, Any]]:
    if not md_text.strip():
        return []

    parts = re.split(r"^(#{1,3})\s+(.+?)\s*$", md_text, flags=re.MULTILINE)
    sections: list[dict[str, Any]] = []
    order = 0

    if parts and parts[0].strip():
        content = _clean_md_chunk(parts[0])
        if len(content) >= _MIN_SECTION_CHARS:
            sections.append(
                {
                    "section_type": "other",
                    "title": "Preamble",
                    "content": content[:_MAX_SECTION_CHARS],
                    "order_idx": order,
                }
            )
            order += 1

    i = 1
    while i + 2 < len(parts):
        title = parts[i + 1].strip()
        body = parts[i + 2]
        sec_type = _classify_heading(title)
        content = _clean_md_chunk(body)
        if len(content) >= _MIN_SECTION_CHARS:
            sections.append(
                {
                    "section_type": sec_type,
                    "title": title,
                    "content": content[:_MAX_SECTION_CHARS],
                    "order_idx": order,
                }
            )
            order += 1
        i += 3

    if not sections and md_text.strip():
        sections.append(
            {
                "section_type": "other",
                "title": "Full document",
                "content": _clean_md_chunk(md_text)[:50000],
                "order_idx": 0,
            }
        )

    return sections


def run_mineru_parse(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    lang: str | None = None,
    backend: str | None = None,
) -> Path:
    apply_mineru_env()

    from mineru.cli.common import do_parse

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = pdf_path.stem
    do_parse(
        output_dir=str(output_dir),
        pdf_file_names=[stem],
        pdf_bytes_list=[pdf_path.read_bytes()],
        p_lang_list=[lang or config.MINERU_LANG],
        backend=backend or config.MINERU_BACKEND,
        parse_method="auto",
        formula_enable=True,
        table_enable=True,
        f_dump_md=True,
        f_dump_content_list=False,
        f_dump_middle_json=False,
        f_dump_model_output=False,
        f_dump_orig_pdf=False,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
    )

    md_path = _find_markdown_file(output_dir, stem)
    if md_path is None:
        raise FileNotFoundError(f"MinerU did not produce markdown for {pdf_path}")
    return md_path


def pdf_to_sections(
    pdf_path: str | Path,
    pmid: str,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Parse PDF with MinerU; cache markdown under raw/mineru_output/{pmid}/."""
    pdf_path = Path(pdf_path)
    out_base = Path(config.MINERU_OUTPUT_DIR) / pmid
    cache_meta = out_base / "meta.json"
    md_cached = out_base / f"{pdf_path.stem}.md"

    if not force and cache_meta.exists() and md_cached.exists():
        md_text = md_cached.read_text(encoding="utf-8", errors="replace")
        return split_markdown_into_sections(md_text)

    out_base.mkdir(parents=True, exist_ok=True)
    md_path = run_mineru_parse(pdf_path, out_base)
    md_text = md_path.read_text(encoding="utf-8", errors="replace")
    md_cached.write_text(md_text, encoding="utf-8")

    meta = {
        "pmid": pmid,
        "pdf_path": str(pdf_path),
        "mineru_md": str(md_path),
        "backend": config.MINERU_BACKEND,
        "device": os.environ.get("MINERU_DEVICE_MODE", "cpu"),
        "md_chars": len(md_text),
    }
    cache_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return split_markdown_into_sections(md_text)
