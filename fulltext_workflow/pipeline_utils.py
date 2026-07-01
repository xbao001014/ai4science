"""Shared utilities for the idea pipeline CLI."""
from __future__ import annotations

import re


def parse_gap_titles(report_text: str) -> list[str]:
    """Extract research gap titles from debate or static gap reports."""
    titles: list[str] = []
    patterns = [
        r"###\s*研究空白\s*\d+[：:]\s*(.+)",
        r"###\s*Research\s+Gap\s*\d+[：:]\s*(.+)",
        r"###\s*Gap\s*\d+[：:]\s*(.+)",
        r"###\s*研究空白\s*\d+\s*[：:]\s*(.+)",
        r"###\s*候选空白\s*\d+[：:]\s*(.+)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, report_text, re.IGNORECASE):
            t = m.group(1).strip().rstrip("*").strip()
            if t and t not in titles:
                titles.append(t)
    if not titles:
        for m in re.finditer(r"\*+\d+[\.\、]\s*(.+?)\*+", report_text):
            t = m.group(1).strip()
            if 5 < len(t) < 120:
                titles.append(t)
    return titles


def parse_gap_sections(report_text: str) -> list[tuple[str, str]]:
    """Return list of (title, full_section_markdown)."""
    pattern = r"(###\s*(?:研究空白|Research\s+Gap|Gap|候选空白)\s*\d+[：:]\s*.+?)(?=\n###\s*(?:研究空白|Research\s+Gap|Gap|候选空白|##\s)|\Z)"
    sections: list[tuple[str, str]] = []
    for m in re.finditer(pattern, report_text, re.IGNORECASE | re.DOTALL):
        block = m.group(1).strip()
        title_m = re.match(
            r"###\s*(?:研究空白|Research\s+Gap|Gap|候选空白)\s*\d+[：:]\s*(.+)",
            block,
            re.IGNORECASE,
        )
        if title_m:
            title = title_m.group(1).strip().rstrip("*").strip()
            sections.append((title, block))
    if not sections:
        for title in parse_gap_titles(report_text):
            sections.append((title, title))
    return sections
