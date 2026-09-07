"""Deterministic, privacy-bounded Method embedding inputs and dry-run plans."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import config
from db.schema import get_conn


INPUT_FORMAT_VERSION = "method_embedding_input/v1"
_SPACE_RE = re.compile(r"\s+")
_SECTION_PRIORITY = {
    "methods": 0,
    "results": 1,
    "discussion": 2,
    "abstract": 3,
}


@dataclass(frozen=True)
class MethodEmbeddingInput:
    method_entity_id: int
    text: str
    input_sha256: str
    context_quality: str
    input_chars: int
    input_bytes: int
    estimated_tokens: int


def _clean_inline(value: Any, max_chars: int | None = None) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc" or ch in "\t\n")
    text = _SPACE_RE.sub(" ", text).strip()
    if max_chars is not None:
        text = text[:max_chars].rstrip()
    return text


def _parse_aliases(value: Any) -> list[str]:
    if not value:
        return []
    candidates: list[Any]
    try:
        parsed = json.loads(str(value))
        candidates = parsed if isinstance(parsed, list) else [parsed]
    except (TypeError, ValueError, json.JSONDecodeError):
        candidates = re.split(r"[;,|]", str(value))
    clean = {_clean_inline(candidate) for candidate in candidates}
    clean.discard("")
    return sorted(clean, key=lambda item: (item.casefold(), item))[:8]


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text.encode("utf-8")) / 3.0))


def _context_rank(row: dict[str, Any]) -> tuple[int, str, int]:
    section = _clean_inline(row.get("evidence_section")).lower()
    return (
        _SECTION_PRIORITY.get(section, 9),
        _clean_inline(row.get("source_pmid")),
        int(row.get("relation_id") or 0),
    )


def _build_one(
    entity: dict[str, Any],
    contexts: list[dict[str, Any]],
    *,
    max_chars: int,
) -> MethodEmbeddingInput | None:
    name = _clean_inline(entity.get("name"))
    if not name:
        return None
    aliases = [alias for alias in _parse_aliases(entity.get("aliases")) if alias.casefold() != name.casefold()]
    role = _clean_inline(entity.get("method_role")) or "unknown"
    lines = [
        f"format: {INPUT_FORMAT_VERSION}",
        f"method: {name}",
        f"aliases: {', '.join(aliases)}" if aliases else "aliases:",
        f"role: {role}",
    ]

    selected: list[dict[str, Any]] = []
    seen_pmids: set[str] = set()
    for row in sorted(contexts, key=_context_rank):
        pmid = _clean_inline(row.get("source_pmid"))
        if not pmid or pmid in seen_pmids:
            continue
        seen_pmids.add(pmid)
        selected.append(row)
        if len(selected) >= 3:
            break

    has_title = False
    has_evidence = False
    if selected:
        lines.append("contexts:")
    for row in selected:
        pmid = _clean_inline(row.get("source_pmid"))
        title = _clean_inline(row.get("title"), 400)
        evidence = _clean_inline(row.get("evidence_quote"), 400)
        has_title = has_title or bool(title)
        has_evidence = has_evidence or bool(evidence)
        lines.append(f"- pmid: {pmid}")
        if title:
            lines.append(f"  title: {title}")
        if evidence:
            lines.append(f"  evidence: {evidence}")

    normalized = "\n".join(lines).strip()
    if len(normalized) > max_chars:
        normalized = normalized[:max_chars].rstrip()
    if not normalized:
        return None
    context_quality = "evidence" if has_evidence else ("title_only" if has_title else "name_only")
    encoded = normalized.encode("utf-8")
    return MethodEmbeddingInput(
        method_entity_id=int(entity["id"]),
        text=normalized,
        input_sha256=hashlib.sha256(encoded).hexdigest(),
        context_quality=context_quality,
        input_chars=len(normalized),
        input_bytes=len(encoded),
        estimated_tokens=_estimate_tokens(normalized),
    )


def load_method_embedding_inputs(
    *,
    limit: int | None = None,
    max_chars: int | None = None,
) -> list[MethodEmbeddingInput]:
    """Load Methods used by an active APPLIES_METHOD edge, ordered by entity id."""
    resolved_limit = -1 if limit is None or int(limit) <= 0 else int(limit)
    with get_conn() as conn:
        entity_rows = conn.execute(
            """SELECT e.id, e.name, e.aliases, e.method_role
               FROM entities e
               WHERE e.type='Method'
                 AND EXISTS (
                   SELECT 1 FROM relations r
                   WHERE r.object_id=e.id
                     AND r.object_type='Method'
                     AND r.relation='APPLIES_METHOD'
                     AND COALESCE(r.status, 'active')='active'
                 )
               ORDER BY e.id
               LIMIT ?""",
            (resolved_limit,),
        ).fetchall()
        entities = [dict(row) for row in entity_rows]
        if not entities:
            return []

        ids = [int(row["id"]) for row in entities]
        context_rows: list[dict[str, Any]] = []
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            marks = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""SELECT r.object_id AS method_entity_id,
                           r.id AS relation_id, r.source_pmid, p.title,
                           COALESCE(NULLIF(re.evidence_section, ''), r.evidence_section) AS evidence_section,
                           COALESCE(NULLIF(re.evidence_quote, ''), r.evidence_quote) AS evidence_quote
                    FROM relations r
                    LEFT JOIN papers p ON p.pmid=r.source_pmid
                    LEFT JOIN relation_evidence re ON re.id = (
                        SELECT re2.id FROM relation_evidence re2
                        WHERE re2.relation_id=r.id
                        ORDER BY CASE lower(COALESCE(re2.evidence_section, ''))
                                   WHEN 'methods' THEN 0 WHEN 'results' THEN 1
                                   WHEN 'discussion' THEN 2 WHEN 'abstract' THEN 3
                                   ELSE 9 END,
                                 re2.id
                        LIMIT 1
                    )
                    WHERE r.object_id IN ({marks})
                      AND r.object_type='Method'
                      AND r.relation='APPLIES_METHOD'
                      AND COALESCE(r.status, 'active')='active'
                    ORDER BY r.object_id, r.id""",
                tuple(chunk),
            ).fetchall()
            context_rows.extend(dict(row) for row in rows)

    by_entity: dict[int, list[dict[str, Any]]] = {}
    for row in context_rows:
        by_entity.setdefault(int(row["method_entity_id"]), []).append(row)
    cap = max_chars if max_chars is not None else config.EMBEDDING_CONTEXT_MAX_CHARS
    built = [
        item
        for entity in entities
        if (item := _build_one(entity, by_entity.get(int(entity["id"]), []), max_chars=cap))
        is not None
    ]
    return built


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    return int(ordered[index])


def build_embedding_plan(
    *,
    limit: int | None = None,
    provider: str = config.EMBEDDING_PROVIDER,
    model: str = config.EMBEDDING_MODEL,
    dimensions: int = config.EMBEDDING_DIMENSIONS,
    batch_size: int = config.EMBEDDING_BATCH_SIZE,
) -> dict[str, Any]:
    from analysis.embedding_store import cached_hashes

    inputs = load_method_embedding_inputs(limit=limit)
    hits = cached_hashes(
        [item.input_sha256 for item in inputs],
        provider=provider,
        model=model,
        dimensions=dimensions,
    )
    misses = len(inputs) - len(hits)
    tokens = sum(item.estimated_tokens for item in inputs if item.input_sha256 not in hits)
    lengths = [item.input_chars for item in inputs]
    qualities = {"evidence": 0, "title_only": 0, "name_only": 0}
    for item in inputs:
        qualities[item.context_quality] = qualities.get(item.context_quality, 0) + 1
    return {
        "scope": "active_applies_method",
        "estimate_only": True,
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
        "batch_size": batch_size,
        "candidate_methods": len(inputs),
        "constructable_inputs": len(inputs),
        "context_quality": qualities,
        "cache_hits": len(hits),
        "cache_misses": misses,
        "estimated_sync_requests": math.ceil(misses / batch_size) if misses else 0,
        "estimated_tokens": tokens,
        "estimated_cost_cny": round(
            tokens / 1_000_000 * config.EMBEDDING_ESTIMATED_CNY_PER_MTOK, 6
        ),
        "input_chars": {
            "p50": _percentile(lengths, 0.50),
            "p95": _percentile(lengths, 0.95),
            "max": max(lengths, default=0),
        },
    }
