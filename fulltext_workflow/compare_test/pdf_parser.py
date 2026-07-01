"""Parse PDF text into pseudo-sections (regex split on embedded headings)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

# Order matters: more specific first
_SECTION_SPLITS: list[tuple[str, re.Pattern[str]]] = [
    ("abstract", re.compile(r"\babstract\b", re.I)),
    ("introduction", re.compile(r"\b(?:introduction|background)\b", re.I)),
    ("methods", re.compile(r"\b(?:methods|materials?\s+and\s+methods|methodology)\b", re.I)),
    ("results", re.compile(r"\b(?:results|findings)\b", re.I)),
    ("discussion", re.compile(r"\b(?:discussion|interpretation)\b", re.I)),
    ("limitations", re.compile(r"\b(?:limitations?|study\s+limitations?)\b", re.I)),
    (
        "future_work",
        re.compile(r"\b(?:conclusion|conclusions|future\s+work|future\s+directions?)\b", re.I),
    ),
]

_MIN_SECTION_CHARS = 120
_MAX_SECTION_CHARS = 12000
_SKIP_AFTER_START = 500  # ignore header/footer matches in first N chars


def extract_pdf_text(pdf_path: str | Path) -> str:
    path = Path(pdf_path)
    if not path.exists():
        return ""
    doc = fitz.open(str(path))
    try:
        parts = []
        for page in doc:
            parts.append(page.get_text("text"))
        return re.sub(r"\n{3,}", "\n\n", "\n".join(parts)).strip()
    finally:
        doc.close()


def _find_section_anchors(text: str) -> list[tuple[int, str, str]]:
    """Return sorted (offset, section_type, matched_text) anchors."""
    anchors: list[tuple[int, str, str]] = []
    seen_offsets: set[int] = set()

    for section_type, pattern in _SECTION_SPLITS:
        for match in pattern.finditer(text):
            pos = match.start()
            if pos < _SKIP_AFTER_START and section_type != "abstract":
                continue
            # Avoid duplicate anchors within 40 chars
            if any(abs(pos - s) < 40 for s in seen_offsets):
                continue
            seen_offsets.add(pos)
            anchors.append((pos, section_type, match.group(0)))

    anchors.sort(key=lambda x: x[0])
    return anchors


def split_into_sections(full_text: str) -> list[dict[str, Any]]:
    if not full_text.strip():
        return []

    anchors = _find_section_anchors(full_text)
    sections: list[dict[str, Any]] = []

    if len(anchors) >= 2:
        # Keep first anchor per section type (reduces in-text false positives)
        first_by_type: dict[str, tuple[int, str, str]] = {}
        for pos, sec_type, label in anchors:
            if sec_type not in first_by_type:
                first_by_type[sec_type] = (pos, sec_type, label)
        ordered = sorted(first_by_type.values(), key=lambda x: x[0])

        for i, (pos, sec_type, label) in enumerate(ordered):
            end = ordered[i + 1][0] if i + 1 < len(ordered) else len(full_text)
            content = re.sub(r"\s+", " ", full_text[pos:end]).strip()
            if len(content) >= _MIN_SECTION_CHARS:
                sections.append(
                    {
                        "section_type": sec_type,
                        "title": label.strip(),
                        "content": content[:_MAX_SECTION_CHARS],
                        "order_idx": len(sections),
                    }
                )

    if not sections:
        # Line-based fallback
        sections = _split_by_lines(full_text)

    if not sections and full_text.strip():
        sections.append(
            {
                "section_type": "other",
                "title": "Full PDF text",
                "content": full_text[:50000],
                "order_idx": 0,
            }
        )

    return sections


def _split_by_lines(full_text: str) -> list[dict[str, Any]]:
    line_patterns = [
        ("abstract", re.compile(r"^\s*abstract\s*$", re.I)),
        ("introduction", re.compile(r"^\s*(introduction|background)\s*$", re.I)),
        ("methods", re.compile(r"^\s*(methods|materials?\s+and\s+methods)\s*$", re.I)),
        ("results", re.compile(r"^\s*(results|findings)\s*$", re.I)),
        ("discussion", re.compile(r"^\s*discussion\s*$", re.I)),
        ("limitations", re.compile(r"^\s*limitations?\s*$", re.I)),
    ]
    lines = full_text.splitlines()
    sections: list[dict[str, Any]] = []
    current_type = "other"
    current_title = "Body"
    current_lines: list[str] = []

    def flush() -> None:
        content = re.sub(r"\s+", " ", " ".join(current_lines)).strip()
        if len(content) >= _MIN_SECTION_CHARS:
            sections.append(
                {
                    "section_type": current_type,
                    "title": current_title,
                    "content": content[:_MAX_SECTION_CHARS],
                    "order_idx": len(sections),
                }
            )

    for line in lines:
        detected = None
        for sec_type, pat in line_patterns:
            if pat.match(line.strip()):
                detected = sec_type
                break
        if detected:
            flush()
            current_type = detected
            current_title = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    flush()
    return sections
