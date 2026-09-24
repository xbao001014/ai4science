"""Source-grounded paper-local annotations for weekly hotspot display."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from analysis.method_synonyms import resolve_method_canonical
from db.schema import get_conn


def _recent_mentions(window_days: int) -> list[dict[str, Any]]:
    window = max(1, int(window_days))
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT m.entity_type, m.surface_name, m.explicit_long_form,
                      m.qualifiers_json, m.resolution_status, m.source_pmid,
                      e.name AS entity_name, re.evidence_quote, re.context_text
               FROM entity_mentions m
               JOIN relations r ON r.id=m.relation_id
               JOIN entities e ON e.id=m.entity_id
               JOIN relation_evidence re ON re.id=m.relation_evidence_id
               WHERE COALESCE(r.status,'active')='active'
                 AND m.source_pmid IN (
                   SELECT COALESCE(p.source_key,p.pmid) FROM papers p
                   WHERE p.date_precision IN ('day','month')
                     AND p.pub_date IS NOT NULL
                     AND date(p.pub_date) BETWEEN date('now', ?) AND date('now')
                 )""",
            (f"-{window} days",),
        ).fetchall()
    return [dict(row) for row in rows]


def attach_hotspot_annotations(
    payload: dict[str, Any], *, window_days: int,
) -> list[dict[str, Any]]:
    """Enrich visible Method/Disease rows; return capped source detail records."""
    method_boards = ("new_methods", "emerging_methods", "active_methods")
    methods = {
        str(row.get("name") or "") for board in method_boards
        for row in payload.get(board, [])
    }
    diseases = {str(row.get("name") or "") for row in payload.get("heating_diseases", [])}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple] = set()
    for mention in _recent_mentions(window_days):
        entity_type = str(mention["entity_type"])
        name = str(mention["entity_name"])
        if entity_type == "Method":
            name = resolve_method_canonical(name)
            if name not in methods:
                continue
        elif entity_type == "Disease":
            if name not in diseases:
                continue
        else:
            continue
        marker = (
            entity_type, name, mention["source_pmid"], mention["surface_name"],
            mention["explicit_long_form"], mention["qualifiers_json"],
        )
        if marker in seen:
            continue
        seen.add(marker)
        try:
            qualifiers = json.loads(mention["qualifiers_json"] or "[]")
        except (TypeError, ValueError):
            qualifiers = []
        grouped[(entity_type, name)].append({
            "type": entity_type,
            "name": name,
            "surface_name": mention["surface_name"],
            "explicit_long_form": mention["explicit_long_form"] or "",
            "disease_qualifiers": ", ".join(
                f"{q.get('kind')}: {q.get('phrase')}" for q in qualifiers
                if isinstance(q, dict) and q.get("phrase")
            ),
            "source_pmid": mention["source_pmid"],
            "evidence_quote": mention["evidence_quote"],
            "context_text": mention["context_text"] or "",
        })

    details: list[dict[str, Any]] = []
    for records in grouped.values():
        records.sort(key=lambda record: (
            -int(bool(record["explicit_long_form"])),
            -int(bool(record["disease_qualifiers"])),
            str(record["source_pmid"]),
        ))
    for board in (*method_boards, "heating_diseases"):
        for row in payload.get(board, []):
            entity_type = "Disease" if board == "heating_diseases" else "Method"
            records = grouped.get((entity_type, str(row.get("name") or "")), [])
            pmids = sorted({str(r["source_pmid"]) for r in records})
            form_pairs: dict[tuple[str, str], str] = {}
            meanings: dict[str, set[str]] = defaultdict(set)
            for record in records:
                surface = str(record["surface_name"] or "").strip()
                full = str(record["explicit_long_form"] or "").strip()
                if not surface or not full or surface.casefold() == full.casefold():
                    continue
                form_pairs.setdefault((surface.casefold(), full.casefold()), f"{surface} → {full}")
                meanings[surface.casefold()].add(full.casefold())
            forms = sorted(form_pairs.values(), key=str.casefold)
            surface_names = sorted({str(r["surface_name"]) for r in records
                                    if str(r["surface_name"]).casefold()
                                    != str(row.get("name") or "").casefold()})
            qualifiers = sorted({part.strip() for record in records
                                 for part in str(record["disease_qualifiers"]).split(", ")
                                 if part.strip()})
            row["annotated_papers"] = len(pmids)
            row["paper_full_forms"] = "; ".join(forms[:3])
            row["paper_surface_names"] = "; ".join(surface_names[:4])
            row["disease_qualifiers"] = "; ".join(qualifiers[:4])
            row["annotation_pmids"] = ", ".join(pmids[:5])
            row["annotation_status"] = (
                "同一缩写多种全称，待核" if any(len(values) > 1 for values in meanings.values()) else
                "论文级注释，未消歧" if records else "暂无注释"
            )
            if board in ("new_methods", "emerging_methods", "heating_diseases"):
                details.extend(records[:3])
    unique_details = []
    detail_keys = set()
    for record in details:
        marker = (
            record["type"], record["name"], record["source_pmid"],
            record["surface_name"], record["evidence_quote"],
        )
        if marker not in detail_keys:
            detail_keys.add(marker)
            unique_details.append(record)
    return unique_details
