"""Phase 0: bootstrap pathology data landscape into SQLite from live API."""
from __future__ import annotations

import time
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

    host = urlparse(config.PATHOLOGY_API_BASE_URL).hostname or config.PATHOLOGY_API_BASE_URL
    print(f"[Bootstrap] Preflight connectivity check ({host}) …", flush=True)
    t0 = time.time()
    preflight = check_api_connectivity()
    if not preflight["ok"]:
        print(f"[Bootstrap] Preflight failed in {time.time() - t0:.1f}s: {preflight['error']}")
        prev = landscape_count()
        return {
            "skipped": False,
            "disease_count": prev,
            "disease_ids": [],
            "loaded": 0,
            "api_error": preflight["error"],
            "kept_existing": prev > 0,
            "host": host,
        }
    print(f"[Bootstrap] Preflight OK in {time.time() - t0:.1f}s", flush=True)

    client = get_pathology_client(use_sqlite_cache=not force)
    if not isinstance(client, ApiPathologyDataClient):
        client = ApiPathologyDataClient(use_sqlite_cache=False)

    max_n = config.PATHOLOGY_BOOTSTRAP_MAX_DISEASES
    min_cases = config.PATHOLOGY_BOOTSTRAP_MIN_CASES
    print(
        f"[Bootstrap] Loading catalog (min_cases={min_cases}, max_diseases={max_n}) …",
        flush=True,
    )
    t_cat = time.time()
    if force or not client._catalog_by_code:
        catalog_diseases = client._load_catalog_from_api(
            min_cases=min_cases,
            progress=True,
        )
    else:
        catalog_diseases = client.get_diseases(min_cases=min_cases)["diseases"]
        print(f"[Bootstrap] Using cached catalog: {len(catalog_diseases)} diseases")
    print(f"[Bootstrap] Catalog phase done in {time.time() - t_cat:.1f}s", flush=True)

    targets = catalog_diseases[:max_n]
    print(
        f"[Bootstrap] Building full landscape for {len(targets)}/{len(catalog_diseases)} "
        f"diseases (≈30–60s each) …",
        flush=True,
    )

    loaded: list[str] = []
    errors: list[str] = []
    pending: list[tuple[str, dict[str, Any]]] = []
    cleared = False

    for i, disease in enumerate(targets, start=1):
        disease_id = disease["disease_id"]
        name = disease.get("name_zh") or disease_id
        print(f"[Bootstrap] Landscape {i}/{len(targets)}: {disease_id} ({name}) …", flush=True)
        t_one = time.time()
        try:
            entry = client.build_landscape_entry(
                disease_id,
                disease_row=catalog_to_disease_row(disease),
            )
            if not cleared:
                print("[Bootstrap] Clearing previous landscape cache …", flush=True)
                clear_landscape()
                cleared = True
            upsert_landscape(disease_id, entry)
            pending.append((disease_id, entry))
            loaded.append(disease_id)
            print(
                f"[Bootstrap] Landscape {i}/{len(targets)}: ok in {time.time() - t_one:.1f}s "
                f"(saved {len(loaded)})",
                flush=True,
            )
        except (ValueError, PathologyHttpError, TimeoutError, OSError) as exc:
            msg = f"{disease_id}: {exc}"
            errors.append(msg)
            print(
                f"[Bootstrap] Skip {msg} ({time.time() - t_one:.1f}s)",
                flush=True,
            )

    if not pending and not cleared:
        print("[Bootstrap] No diseases loaded; existing SQLite landscape unchanged.", flush=True)

    prev = landscape_count()
    result: dict[str, Any] = {
        "skipped": False,
        "disease_count": prev,
        "disease_ids": loaded,
        "loaded": len(loaded),
        "errors": errors,
        "kept_existing": len(loaded) == 0 and prev > 0,
        "host": host,
    }
    if errors and not loaded:
        result["api_error"] = errors[0]
    return result
