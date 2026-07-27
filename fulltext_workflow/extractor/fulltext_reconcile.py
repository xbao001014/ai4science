"""Pass 2 fulltext reconcile: assemble truncated text and parse LLM JSON."""
from __future__ import annotations

from typing import Any

_SECTION_PRIORITY: tuple[str, ...] = (
    "methods",
    "results",
    "discussion",
    "limitations",
    "future_work",
    "abstract",
    "introduction",
    "other",
)
_PRIORITY_RANK = {name: idx for idx, name in enumerate(_SECTION_PRIORITY)}
_VALID_DATASET_ACTIONS = frozenset({"keep", "merge", "drop"})

RECONCILE_SYSTEM = """You are a biomedical knowledge-graph reconciler. Read the Pass 1 entity summary and full paper text, then output JSON only (no markdown, no commentary).

Return exactly this shape:
{
  "datasets": [
    {"name": "...", "access": "public|restricted|unknown", "action": "keep|merge|drop", "reason": "..."}
  ],
  "bindings": [
    {"method": "...", "disease": "...", "dataset": "...", "quote": "..."}
  ],
  "limitations": [
    {"canonical": "...", "merges": ["..."], "quote": "..."}
  ]
}

Rules:
- Drop literature platforms and bibliographic indexes (PubMed, GEO as a portal, PMC, etc.) — they are not experimental datasets.
- Do not mark a dataset public unless it is a well-known public research dataset named in the paper; when unsure use unknown.
- Do not set `access` to `public` for dataset names that are not on the known public alias list (unlisted names must stay `unknown`).
- merge: collapse aliases to one canonical dataset name already implied by Pass 1 or known public aliases.
- bindings: one row per method–disease–dataset claim; dataset may be empty when no named set is stated.
- limitations: canonical short phrase; merges lists section-level fragments to supersede.
- Omit empty arrays when nothing applies; use [] not null for lists.
"""


def _section_rank(section_type: str) -> int:
    return _PRIORITY_RANK.get(section_type.lower(), len(_SECTION_PRIORITY))


def _field(sec: dict[str, Any], key: str, default: str = "") -> str:
    val = sec.get(key, default)
    if val is None:
        return default
    return val if isinstance(val, str) else str(val)


def assemble_reconcile_text(sections: list[dict], *, max_chars: int) -> str:
    """Concatenate sections in priority order, truncating to max_chars."""
    if max_chars <= 0:
        return ""

    ordered = sorted(sections, key=lambda s: _section_rank(_field(s, "section_type")))
    parts: list[str] = []
    used = 0

    for sec in ordered:
        content = _field(sec, "content").strip()
        if not content:
            continue
        section_type = _field(sec, "section_type") or "other"
        block = f"## {section_type}\n{content}"
        sep = 2 if parts else 0
        if used + sep + len(block) <= max_chars:
            parts.append(block)
            used += sep + len(block)
            continue
        budget = max_chars - used - sep
        if budget > 0:
            parts.append(block[:budget])
        break

    return "\n\n".join(parts)


def _parse_dataset_rows(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        action = str(row.get("action") or "").strip().lower()
        if action not in _VALID_DATASET_ACTIONS:
            continue
        out.append(
            {
                "name": name,
                "access": str(row.get("access") or "unknown").strip().lower() or "unknown",
                "action": action,
                "reason": str(row.get("reason") or "").strip(),
            }
        )
    return out


def _parse_binding_rows(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        method = str(row.get("method") or "").strip()
        disease = str(row.get("disease") or "").strip()
        if not method or not disease:
            continue
        out.append(
            {
                "method": method,
                "disease": disease,
                "dataset": str(row.get("dataset") or "").strip(),
                "quote": str(row.get("quote") or "").strip(),
            }
        )
    return out


def _parse_limitation_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        canonical = str(row.get("canonical") or "").strip()
        if not canonical:
            continue
        merges_raw = row.get("merges")
        merges: list[str] = []
        if isinstance(merges_raw, list):
            merges = [str(m).strip() for m in merges_raw if str(m).strip()]
        out.append(
            {
                "canonical": canonical,
                "merges": merges,
                "quote": str(row.get("quote") or "").strip(),
            }
        )
    return out


def parse_reconcile_payload(raw: dict) -> dict:
    """Validate and normalize Pass 2 reconcile JSON."""
    if not isinstance(raw, dict):
        raw = {}
    return {
        "datasets": _parse_dataset_rows(raw.get("datasets")),
        "bindings": _parse_binding_rows(raw.get("bindings")),
        "limitations": _parse_limitation_rows(raw.get("limitations")),
    }


def call_reconcile_llm(text: str, entity_summary: str) -> dict:
    from extractor.llm_client import llm_call_structured

    user = f"ENTITY SUMMARY (Pass1):\n{entity_summary}\n\nFULLTEXT:\n{text}"
    return parse_reconcile_payload(llm_call_structured(RECONCILE_SYSTEM, user))
