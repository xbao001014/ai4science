"""Helpers for grouping document sections before LLM extraction."""
from __future__ import annotations

from typing import Any


def _field(sec: Any, key: str, default: str = "") -> str:
    """Read a column from sqlite3.Row or dict."""
    try:
        val = sec[key]
    except (KeyError, IndexError, TypeError):
        return default
    if val is None:
        return default
    return val if isinstance(val, str) else str(val)


def merge_sections_by_type(sections: list[Any]) -> list[dict]:
    """One job per section_type; merge fragmented rows (e.g. many `other` chunks)."""
    grouped: dict[str, list[Any]] = {}
    for sec in sections:
        content = _field(sec, "content").strip()
        if not content:
            continue
        grouped.setdefault(_field(sec, "section_type"), []).append(sec)

    merged: list[dict] = []
    for sec_type, group in grouped.items():
        content = "\n\n".join(_field(s, "content").strip() for s in group)
        title = next((_field(s, "title") for s in group if _field(s, "title")), sec_type)
        merged.append(
            {
                "section_type": sec_type,
                "title": title or sec_type,
                "content": content,
            }
        )
    return merged
