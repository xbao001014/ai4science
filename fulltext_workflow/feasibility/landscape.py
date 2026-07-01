"""Phase 0: bootstrap pathology data landscape into SQLite from live API."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import config
from db.schema import clear_landscape, get_all_landscape, landscape_count, upsert_landscape
from feasibility.client import ApiPathologyDataClient, get_pathology_client
from feasibility.http_api import HttpPathologyApi, PathologyHttpError


def catalog_to_disease_row(catalog: dict[str, Any]) -> dict[str, Any]:
    """Map internal catalog dict to API disease row for build_landscape_entry."""
    return {
        "DiseaseCode": catalog.get("disease_id"),
        "DiseaseId": catalog.get("disease_db_id"),
        "DiseaseNameZh": catalog.get("name_zh", ""),
        "Organ": catalog.get("organ", ""),
        "OrganSystem": catalog.get("organ_system", ""),
        "Description": catalog.get("description"),
    }


def check_api_connectivity() -> dict[str, Any]:
    """Quick preflight: can we resolve and reach the pathology API host?"""
    api = HttpPathologyApi()
    host = urlparse(config.PATHOLOGY_API_BASE_URL).hostname or config.PATHOLOGY_API_BASE_URL
    try:
        rows = api.list_diseases(limit=1)
        return {"ok": True, "host": host, "sample_rows": len(rows)}
    except PathologyHttpError as exc:
        return {"ok": False, "host": host, "error": str(exc)}


def bootstrap_landscape(force: bool = False) -> dict[str, Any]:
    """
    Query Fangxin pathology API for each disease with sufficient cohort size
    and persist aggregated landscape to pathology_landscape table.

    On --force: always scans the live API (ignores SQLite cache for catalog).
    If the API is unreachable, existing landscape rows are kept.
    """
    if not force and landscape_count() > 0:
        existing = get_all_landscape()
        return {
            "skipped": True,
            "reason": "landscape already populated",
            "disease_count": len(existing),
        }

    preflight = check_api_connectivity()
    if not preflight["ok"]:
        prev = landscape_count()
        return {
            "skipped": False,
            "disease_count": prev,
            "disease_ids": [],
            "loaded": 0,
            "api_error": preflight["error"],
            "kept_existing": prev > 0,
        }

    client = get_pathology_client(use_sqlite_cache=not force)
    if not isinstance(client, ApiPathologyDataClient):
        client = ApiPathologyDataClient(use_sqlite_cache=False)

    if force or not client._catalog_by_code:
        catalog_diseases = client._load_catalog_from_api(
            min_cases=config.PATHOLOGY_BOOTSTRAP_MIN_CASES,
        )
    else:
        catalog_diseases = client.get_diseases(
            min_cases=config.PATHOLOGY_BOOTSTRAP_MIN_CASES,
        )["diseases"]

    loaded: list[str] = []
    errors: list[str] = []
    pending: list[tuple[str, dict[str, Any]]] = []

    for disease in catalog_diseases[: config.PATHOLOGY_BOOTSTRAP_MAX_DISEASES]:
        disease_id = disease["disease_id"]
        try:
            entry = client.build_landscape_entry(
                disease_id,
                disease_row=catalog_to_disease_row(disease),
            )
            pending.append((disease_id, entry))
            loaded.append(disease_id)
        except (ValueError, PathologyHttpError) as exc:
            msg = f"{disease_id}: {exc}"
            errors.append(msg)
            print(f"[Bootstrap] Skip {msg}")

    if pending:
        clear_landscape()
        for disease_id, entry in pending:
            upsert_landscape(disease_id, entry)

    prev = landscape_count()
    result: dict[str, Any] = {
        "skipped": False,
        "disease_count": prev,
        "disease_ids": loaded,
        "loaded": len(loaded),
        "errors": errors,
        "kept_existing": len(loaded) == 0 and prev > 0,
    }
    if errors and not loaded:
        result["api_error"] = errors[0]
    return result
