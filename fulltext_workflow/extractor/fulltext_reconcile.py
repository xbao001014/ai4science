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
            if len(block) <= budget:
                parts.append(block)
            else:
                ellipsis = "\n...\n"
                if budget <= len(ellipsis):
                    parts.append(block[:budget])
                else:
                    remain = budget - len(ellipsis)
                    head_len = remain // 2
                    tail_len = remain - head_len
                    parts.append(block[:head_len] + ellipsis + block[-tail_len:])
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


def summarize_pass1_entities(pmid: str) -> str:
    """Distinct active entity names by type from Pass 1 relations for a PMID."""
    from db.schema import get_conn

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT e.type, e.name
               FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.status='active'
               ORDER BY e.type, e.name""",
            (pmid,),
        ).fetchall()

    by_type: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["type"], row["name"])
        if key in seen:
            continue
        seen.add(key)
        by_type.setdefault(row["type"], []).append(row["name"])

    return "\n".join(
        f"{etype}: {', '.join(names)}" for etype, names in sorted(by_type.items())
    )


def _dataset_name_matches(object_name: str, payload_name: str) -> bool:
    from extractor.dataset_access import normalize_dataset_name

    return normalize_dataset_name(object_name) == normalize_dataset_name(payload_name)


def _limitation_name_matches(object_name: str, merge_name: str) -> bool:
    from extractor.entity_normalize import normalize_entity_name

    return normalize_entity_name(object_name, "Limitation") == normalize_entity_name(
        merge_name, "Limitation"
    )


def _apply_dataset_actions(
    paper_id: int,
    pmid: str,
    datasets: list[dict[str, str]],
) -> None:
    from db.schema import (
        insert_relation,
        list_relations_for_pmid,
        supersede_relation,
        upsert_entity,
    )
    from extractor.dataset_access import (
        is_literature_platform,
        normalize_dataset_name,
        resolve_dataset_access,
    )

    existing = list_relations_for_pmid(pmid, "USES_DATASET")

    for row in datasets:
        name = row["name"]
        action = row["action"]
        access_hint = row.get("access", "unknown")

        if is_literature_platform(name):
            for rel in existing:
                if rel["status"] != "active":
                    continue
                if _dataset_name_matches(rel["object_name"], name):
                    supersede_relation(rel["id"], None)
            continue

        if action == "drop":
            for rel in existing:
                if rel["status"] != "active":
                    continue
                if _dataset_name_matches(rel["object_name"], name):
                    supersede_relation(rel["id"], None)

        elif action == "keep":
            access = resolve_dataset_access(name, access_hint=access_hint)
            canon = normalize_dataset_name(name)
            upsert_entity(canon, "Dataset", access_class=access)

        elif action == "merge":
            canon = normalize_dataset_name(name)
            access = resolve_dataset_access(canon, access_hint=access_hint)
            entity_id = upsert_entity(canon, "Dataset", access_class=access)
            for rel in existing:
                if rel["status"] != "active":
                    continue
                if _dataset_name_matches(rel["object_name"], name):
                    supersede_relation(rel["id"], None)
            insert_relation(
                "Paper",
                paper_id,
                "USES_DATASET",
                "Dataset",
                entity_id,
                source_pmid=pmid,
                extraction_pass="fulltext_reconcile",
                status="active",
            )


def _apply_limitation_merges(
    paper_id: int,
    pmid: str,
    limitations: list[dict[str, Any]],
) -> None:
    from db.schema import (
        insert_relation,
        list_relations_for_pmid,
        supersede_relation,
        upsert_entity,
    )
    from extractor.entity_normalize import normalize_entity_name

    existing = list_relations_for_pmid(pmid, "REPORTS_LIMITATION")

    for lim in limitations:
        canonical_name = normalize_entity_name(lim["canonical"], "Limitation")
        canonical_id = upsert_entity(canonical_name, "Limitation")
        for merge_name in lim.get("merges") or []:
            for rel in existing:
                if rel["status"] != "active":
                    continue
                if _limitation_name_matches(rel["object_name"], merge_name):
                    supersede_relation(rel["id"], canonical_id)
        insert_relation(
            "Paper",
            paper_id,
            "REPORTS_LIMITATION",
            "Limitation",
            canonical_id,
            source_pmid=pmid,
            evidence_quote=lim.get("quote") or "",
            evidence_section="fulltext_reconcile",
            extraction_pass="fulltext_reconcile",
            status="active",
        )


def _apply_bindings(pmid: str, bindings: list[dict[str, str]]) -> None:
    from db.schema import upsert_entity, upsert_paper_entity_binding
    from extractor.dataset_access import (
        is_literature_platform,
        normalize_dataset_name,
        resolve_dataset_access,
    )
    from extractor.entity_normalize import normalize_entity_name

    for row in bindings:
        method = normalize_entity_name(row.get("method") or "", "Method")
        disease = normalize_entity_name(row.get("disease") or "", "Disease")
        if not method and not disease:
            continue
        method_id = upsert_entity(method, "Method") if method else None
        disease_id = upsert_entity(disease, "Disease") if disease else None
        dataset_id = None
        dataset_name = (row.get("dataset") or "").strip()
        if dataset_name and not is_literature_platform(dataset_name):
            canon = normalize_dataset_name(dataset_name)
            access = resolve_dataset_access(canon)
            dataset_id = upsert_entity(canon, "Dataset", access_class=access)
        upsert_paper_entity_binding(
            pmid,
            method_entity_id=method_id,
            disease_entity_id=disease_id,
            dataset_entity_id=dataset_id,
            evidence_quote=row.get("quote") or "",
        )


def apply_reconcile_payload(paper_id: int, pmid: str, payload: dict) -> None:
    """Persist Pass 2 reconcile decisions: datasets, limitations, bindings."""
    normalized = parse_reconcile_payload(payload)
    _apply_dataset_actions(paper_id, pmid, normalized["datasets"])
    _apply_limitation_merges(paper_id, pmid, normalized["limitations"])
    _apply_bindings(pmid, normalized["bindings"])
