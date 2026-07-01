"""Pathology LIS client — live API (default) with mock fallback for tests."""
from __future__ import annotations

from typing import Any

import config
from db.schema import get_all_landscape
from feasibility.assessment import (
    assess_feasibility_from_pools,
    feasibility_status,
    gap_analysis_from_pools,
)
from feasibility.hypothesis import HypothesisRequest
from feasibility.http_api import HttpPathologyApi, PathologyHttpError
from feasibility.landscape_builder import (
    aggregate_hospital_stats,
    build_catalog_entry,
    build_feasibility_pools,
    infer_annotations,
    infer_followup,
    infer_molecular_markers,
    infer_tasks,
)
from feasibility.mock_client import MockPathologyDataClient

_MARKER_POOL_KEYS = {
    "MSI_status": "has_msi_status",
    "HER2": "has_her2",
    "EGFR_mutation": "has_egfr",
    "EGFR": "has_egfr",
    "ALK_fusion": "has_alk",
    "ALK": "has_alk",
    "PD_L1_TPS": "has_pd_l1",
}


class ApiPathologyDataClient:
    """Client backed by http://ai.gzfxyl.cn pathology query API."""

    def __init__(
        self,
        api: HttpPathologyApi | None = None,
        *,
        use_sqlite_cache: bool = True,
    ) -> None:
        self._api = api or HttpPathologyApi()
        self._catalog_by_code: dict[str, dict[str, Any]] = {}
        self._disease_data: dict[str, dict[str, Any]] = {}
        if use_sqlite_cache:
            self._hydrate_from_sqlite()

    def _hydrate_from_sqlite(self) -> None:
        for row in get_all_landscape():
            disease_id = row["disease_id"]
            payload = row.get("payload") or {}
            catalog = payload.get("catalog") or {}
            if catalog:
                self._catalog_by_code[disease_id] = catalog
            pools = payload.get("feasibility_pools") or {}
            self._disease_data[disease_id] = {
                "sample_size": payload.get("sample_size") or {},
                "tasks": payload.get("tasks") or [],
                "annotations": payload.get("annotations") or [],
                "followup": payload.get("followup") or {},
                "molecular_markers": (payload.get("molecular") or {}).get(
                    "molecular_markers", []
                ),
                "feasibility_pools": pools,
                "wsi_specs": payload.get("wsi_specs") or {},
            }

    def search_diseases(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        from feasibility.landscape_builder import build_lightweight_catalog_entry

        rows = self._api.list_diseases(keyword=keyword, limit=limit)
        out: list[dict[str, Any]] = []
        for row in rows:
            code = row.get("DiseaseCode")
            if not code:
                continue
            if code in self._catalog_by_code:
                out.append(self._catalog_by_code[code])
                continue
            catalog = build_lightweight_catalog_entry(self._api, row)
            if catalog:
                self._catalog_by_code[code] = catalog
                out.append(catalog)
        return out[:limit]

    def get_diseases(
        self,
        organ_system: str | None = None,
        min_cases: int = 50,
    ) -> dict[str, Any]:
        if not self._catalog_by_code:
            self._load_catalog_from_api(min_cases=min_cases)

        diseases = list(self._catalog_by_code.values())
        if organ_system:
            diseases = [
                d for d in diseases
                if (d.get("organ_system") or "").lower() == organ_system.lower()
                or (d.get("organ") or "").lower() == organ_system.lower()
            ]
        if min_cases:
            diseases = [d for d in diseases if d.get("total_cases", 0) >= min_cases]
        return {"total_disease_types": len(diseases), "diseases": diseases}

    def _load_catalog_from_api(self, min_cases: int = 50) -> list[dict[str, Any]]:
        from feasibility.landscape_builder import build_lightweight_catalog_entry

        rows = self._api.list_diseases(limit=1000)
        diseases: list[dict[str, Any]] = []
        for row in rows:
            code = row.get("DiseaseCode")
            if not code or code in self._catalog_by_code:
                if code and code in self._catalog_by_code:
                    catalog = self._catalog_by_code[code]
                    if catalog.get("total_cases", 0) >= min_cases:
                        diseases.append(catalog)
                continue
            catalog = build_lightweight_catalog_entry(self._api, row)
            if not catalog:
                continue
            self._catalog_by_code[code] = catalog
            if catalog.get("total_cases", 0) >= min_cases:
                diseases.append(catalog)
        return diseases

    def get_tasks(self, disease_id: str | None = None) -> dict[str, Any]:
        if disease_id:
            dd = self._ensure_disease(disease_id)
            return {"disease_id": disease_id, "supported_tasks": dd.get("tasks", [])}
        out = [self.get_tasks(did) for did in self._catalog_by_code]
        return {"tasks_by_disease": out}

    def get_sample_size(self, disease_id: str, task_type: str | None = None) -> dict:
        dd = self._ensure_disease(disease_id)
        result = dict(dd.get("sample_size", {}))
        if task_type:
            for t in dd.get("tasks", []):
                if t.get("task_type") == task_type:
                    result["task_cohort_size"] = t.get("cohort_size")
                    break
        return result

    def get_annotation_types(self, disease_id: str) -> dict:
        dd = self._ensure_disease(disease_id)
        return {"disease_id": disease_id, "annotation_types": dd.get("annotations", [])}

    def get_followup_fields(self, disease_id: str) -> dict:
        dd = self._ensure_disease(disease_id)
        return {"disease_id": disease_id, **dd.get("followup", {})}

    def get_molecular_markers(self, disease_id: str) -> dict:
        dd = self._ensure_disease(disease_id)
        markers = dd.get("molecular_markers", [])
        return {
            "disease_id": disease_id,
            "molecular_markers": [
                {k: v for k, v in m.items() if k != "coverage"} for m in markers
            ],
        }

    def get_pairing_rate(self, disease_id: str, markers: list[str]) -> dict:
        pools = self._pools(disease_id)
        wsi = pools.get("has_wsi", 0)
        paired = wsi
        detail: dict[str, int] = {"wsi_only": wsi}
        for marker in markers:
            key = _MARKER_POOL_KEYS.get(marker, f"has_{marker.lower()}")
            cnt = pools.get(key, 0)
            detail[f"wsi_with_{marker}"] = cnt
            paired = min(paired, cnt) if paired else cnt
        return {
            "disease_id": disease_id,
            "query_markers": markers,
            **detail,
            "fully_paired_cohort_size": paired,
            "feasibility_note": (
                f"{paired}例完整配对样本"
                + ("，满足多模态融合研究基本要求（建议≥500例）" if paired >= 500 else "，样本量偏少")
            ),
        }

    def get_wsi_specs(self, disease_id: str) -> dict:
        dd = self._ensure_disease(disease_id)
        return {"disease_id": disease_id, **dd.get("wsi_specs", {})}

    def assess_feasibility(self, request: HypothesisRequest | dict) -> dict[str, Any]:
        req = self._parse_request(request)
        try:
            pools = self._pools(req.disease_id)
        except (ValueError, PathologyHttpError):
            return assess_feasibility_from_pools(req, {}, disease_exists=False)
        return assess_feasibility_from_pools(req, pools)

    def gap_analysis(self, request: HypothesisRequest | dict) -> dict[str, Any]:
        req = self._parse_request(request)
        try:
            pools = self._pools(req.disease_id)
            tasks = self._ensure_disease(req.disease_id).get("tasks", [])
        except (ValueError, PathologyHttpError):
            assess = assess_feasibility_from_pools(req, {}, disease_exists=False)
            return gap_analysis_from_pools(req, {}, assess)
        assess = assess_feasibility_from_pools(req, pools)
        return gap_analysis_from_pools(req, pools, assess, disease_tasks=tasks)

    def build_landscape_entry(
        self,
        disease_code: str,
        *,
        disease_row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if disease_row is None:
            matches = self._api.list_diseases(keyword=disease_code, limit=20)
            disease_row = next(
                (m for m in matches if m.get("DiseaseCode") == disease_code),
                None,
            )
            if disease_row is None and matches:
                disease_row = matches[0]
            if disease_row is None:
                raise ValueError(f"Disease not found: {disease_code}")

        stats = aggregate_hospital_stats(
            self._api.sample_count_by_hospital(disease_code=disease_code)
        )
        built = build_feasibility_pools(self._api, disease_code, stats=stats)
        pools = built["pools"]
        catalog = build_catalog_entry(
            disease_row,
            stats,
            has_molecular=any(
                pools.get(k, 0) for k in ("has_msi_status", "has_her2", "has_egfr", "has_alk")
            ),
            has_ihc=built["ihc_slide_rows"] > 0,
        )
        total = catalog["total_cases"]
        disease_data = {
            "sample_size": {
                "disease_id": disease_code,
                "total_cases": total,
                "total_wsi_slides": catalog["total_wsi_slides"],
                "cases_with_wsi": pools.get("has_wsi", total),
                "cases_with_followup": pools.get("has_survival_label", 0),
            },
            "tasks": infer_tasks(pools, catalog),
            "annotations": infer_annotations(pools, total),
            "followup": infer_followup(pools, total),
            "molecular_markers": infer_molecular_markers(pools, total),
            "feasibility_pools": pools,
            "wsi_specs": {
                "he_slide_rows": built["he_slide_rows"],
                "ihc_slide_rows": built["ihc_slide_rows"],
                "pass_rate": None,
            },
        }

        self._catalog_by_code[disease_code] = catalog
        self._disease_data[disease_code] = disease_data

        return {
            "disease_id": disease_code,
            "catalog": catalog,
            "tasks": disease_data["tasks"],
            "sample_size": disease_data["sample_size"],
            "annotations": disease_data["annotations"],
            "followup": disease_data["followup"],
            "molecular": self.get_molecular_markers(disease_code),
            "feasibility_pools": pools,
            "wsi_specs": disease_data["wsi_specs"],
            "data_source": "fangxin_api",
        }

    def _ensure_disease(self, disease_id: str) -> dict[str, Any]:
        if disease_id in self._disease_data:
            return self._disease_data[disease_id]
        self.build_landscape_entry(disease_id)
        return self._disease_data[disease_id]

    def _pools(self, disease_id: str) -> dict[str, int]:
        return self._ensure_disease(disease_id).get("feasibility_pools", {})

    @staticmethod
    def _parse_request(request: HypothesisRequest | dict) -> HypothesisRequest:
        if isinstance(request, dict):
            return HypothesisRequest(**{k: v for k, v in request.items() if k != "gap_title"})
        return request

    def feasibility_status(self, score: float) -> str:
        return feasibility_status(score)


def get_pathology_client(
    *,
    use_sqlite_cache: bool = True,
    **kwargs: Any,
) -> ApiPathologyDataClient | MockPathologyDataClient:
    provider = (config.PATHOLOGY_DATA_PROVIDER or "api").lower()
    if provider == "mock":
        return MockPathologyDataClient(**kwargs)
    return ApiPathologyDataClient(use_sqlite_cache=use_sqlite_cache, **kwargs)


class PathologyDataClient:
    """Factory wrapper — returns live API client unless PATHOLOGY_DATA_PROVIDER=mock."""

    def __new__(cls, **kwargs: Any) -> ApiPathologyDataClient | MockPathologyDataClient:
        return get_pathology_client(**kwargs)
