"""Batch enrichment of method×disease rows from paper_entity_bindings."""
from __future__ import annotations

from typing import Any

from db.schema import get_conn

_PUBLIC_NAME_CAP = 5


def actionability_hint(binding_paper_cnt: int, public_dataset_cnt: int) -> str:
    if public_dataset_cnt > 0:
        return "public_data"
    if binding_paper_cnt > 0:
        return "bound_no_public"
    return "no_binding"


def actionability_bump(binding_paper_cnt: int, public_dataset_cnt: int) -> float:
    if public_dataset_cnt > 0:
        return 0.5
    if binding_paper_cnt > 0:
        return 0.25
    return 0.0


def enrich_method_disease_rows(
    rows: list[dict[str, Any]],
    *,
    method_key: str = "method",
    disease_key: str = "disease",
) -> list[dict[str, Any]]:
    if not rows:
        return rows

    pairs = {
        (str(r.get(method_key) or ""), str(r.get(disease_key) or ""))
        for r in rows
    }
    pairs.discard(("", ""))

    stats: dict[tuple[str, str], dict[str, Any]] = {
        p: {"pmids": set(), "public": []} for p in pairs
    }

    if pairs:
        with get_conn() as conn:
            cur = conn.execute(
                """
                SELECT b.source_pmid,
                       em.name AS method,
                       ed.name AS disease,
                       eds.name AS dataset,
                       LOWER(COALESCE(eds.access_class, '')) AS access_class
                FROM paper_entity_bindings b
                JOIN entities em ON b.method_entity_id = em.id AND em.type = 'Method'
                JOIN entities ed ON b.disease_entity_id = ed.id AND ed.type = 'Disease'
                LEFT JOIN entities eds ON b.dataset_entity_id = eds.id AND eds.type = 'Dataset'
                """
            )
            for row in cur.fetchall():
                key = (str(row["method"]), str(row["disease"]))
                if key not in stats:
                    continue
                stats[key]["pmids"].add(str(row["source_pmid"]))
                ds = row["dataset"]
                if ds and row["access_class"] == "public":
                    names = stats[key]["public"]
                    if ds not in names and len(names) < _PUBLIC_NAME_CAP:
                        names.append(str(ds))

    for r in rows:
        key = (str(r.get(method_key) or ""), str(r.get(disease_key) or ""))
        info = stats.get(key, {"pmids": set(), "public": []})
        bcnt = len(info["pmids"])
        pubs = list(info["public"])
        pcnt = len(pubs)
        r["binding_paper_cnt"] = bcnt
        r["public_dataset_names"] = pubs
        r["public_dataset_cnt"] = pcnt
        r["actionability_hint"] = actionability_hint(bcnt, pcnt)
    return rows
