"""In-process mock pathology client for offline tests (landscape.json fixtures)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config
from feasibility.assessment import (
    assess_feasibility_from_pools,
    feasibility_status,
    gap_analysis_from_pools,
)
from feasibility.hypothesis import HypothesisRequest

_MARKER_POOL_KEYS = {
    "MSI_status": "has_msi_status",
    "msi_status": "has_msi_status",
    "HER2": "has_her2",
    "her2": "has_her2",
    "EGFR_mutation": "has_egfr",
    "egfr_mutation": "has_egfr",
    "EGFR": "has_egfr",
    "ALK_fusion": "has_alk",
    "alk_fusion": "has_alk",
    "ALK": "has_alk",
    "PD_L1_TPS": "has_pd_l1",
    "PD-L1": "has_pd_l1",
    "pd_l1": "has_pd_l1",
}


class MockPathologyDataClient:
    """Mock client reading JSON fixtures; implements D-01 through V-02."""

    def __init__(self, data_path: str | Path | None = None) -> None:
        path = Path(data_path or config.MOCK_DATA_DIR) / "landscape.json"
        with open(path, encoding="utf-8") as f:
            self._data = json.load(f)
        self._by_id = {d["disease_id"]: d for d in self._data["diseases"]}

    def search_diseases(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        key = keyword.lower()
        out = []
        for disease in self._data["diseases"]:
            hay = f"{disease['disease_id']} {disease.get('name_zh','')} {disease.get('name_en','')}".lower()
            if key in hay:
                out.append(disease)
        return out[:limit]

    def get_diseases(
        self,
        organ_system: str | None = None,
        min_cases: int = 50,
    ) -> dict[str, Any]:
        diseases = self._data["diseases"]
        if organ_system:
            diseases = [d for d in diseases if d.get("organ_system") == organ_system]
        if min_cases:
            diseases = [d for d in diseases if d.get("total_cases", 0) >= min_cases]
        return {"total_disease_types": len(diseases), "diseases": diseases}

    def get_tasks(self, disease_id: str | None = None) -> dict[str, Any]:
        if disease_id:
            dd = self._disease_data(disease_id)
            return {
                "disease_id": disease_id,
                "supported_tasks": dd.get("tasks", []),
            }
        out: list[dict] = []
        for did in self._by_id:
            out.append(self.get_tasks(did))
        return {"tasks_by_disease": out}

    def get_sample_size(self, disease_id: str, task_type: str | None = None) -> dict:
        dd = self._disease_data(disease_id)
        result = dict(dd.get("sample_size", {}))
        if task_type:
            for t in dd.get("tasks", []):
                if t.get("task_type") == task_type:
                    result["task_cohort_size"] = t.get("cohort_size")
                    break
        return result

    def get_annotation_types(self, disease_id: str) -> dict:
        dd = self._disease_data(disease_id)
        return {
            "disease_id": disease_id,
            "annotation_types": dd.get("annotations", []),
        }

    def get_followup_fields(self, disease_id: str) -> dict:
        dd = self._disease_data(disease_id)
        return {"disease_id": disease_id, **dd.get("followup", {})}

    def get_molecular_markers(self, disease_id: str) -> dict:
        dd = self._disease_data(disease_id)
        markers = dd.get("molecular_markers", [])
        return {
            "disease_id": disease_id,
            "molecular_markers": [
                {k: v for k, v in m.items() if k != "coverage"}
                for m in markers
            ],
        }

    def get_pairing_rate(self, disease_id: str, markers: list[str]) -> dict:
        pools = self._pools(disease_id)
        wsi = pools.get("has_wsi", 0)
        paired = wsi
        detail: dict[str, int] = {"wsi_only": wsi}
        for m in markers:
            key = _MARKER_POOL_KEYS.get(m, f"has_{m.lower()}")
            cnt = pools.get(key, 0)
            detail[f"wsi_with_{m}"] = cnt
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
        dd = self._disease_data(disease_id)
        specs = dd.get("wsi_specs", {})
        return {"disease_id": disease_id, **specs}

    def assess_feasibility(self, request: HypothesisRequest | dict) -> dict[str, Any]:
        req = self._parse_request(request)
        if req.disease_id not in self._by_id:
            return assess_feasibility_from_pools(req, {}, disease_exists=False)
        return assess_feasibility_from_pools(req, self._pools(req.disease_id))

    def gap_analysis(self, request: HypothesisRequest | dict) -> dict[str, Any]:
        req = self._parse_request(request)
        if req.disease_id not in self._by_id:
            assess = assess_feasibility_from_pools(req, {}, disease_exists=False)
            return gap_analysis_from_pools(req, {}, assess)
        pools = self._pools(req.disease_id)
        assess = assess_feasibility_from_pools(req, pools)
        tasks = self._disease_data(req.disease_id).get("tasks", [])
        return gap_analysis_from_pools(req, pools, assess, disease_tasks=tasks)

    def build_landscape_entry(self, disease_id: str) -> dict[str, Any]:
        return {
            "disease_id": disease_id,
            "catalog": next(d for d in self._data["diseases"] if d["disease_id"] == disease_id),
            "tasks": self.get_tasks(disease_id)["supported_tasks"],
            "sample_size": self.get_sample_size(disease_id),
            "annotations": self.get_annotation_types(disease_id)["annotation_types"],
            "followup": self.get_followup_fields(disease_id),
            "molecular": self.get_molecular_markers(disease_id),
            "feasibility_pools": self._pools(disease_id),
        }

    def load_landscape_entry(self, disease_id: str, entry: dict[str, Any]) -> None:
        """Hydrate in-memory disease_data from a cached SQLite payload."""
        if disease_id in self._data.get("disease_data", {}):
            return
        catalog = entry.get("catalog") or {}
        pools = entry.get("feasibility_pools") or {}
        total = catalog.get("total_cases") or pools.get("has_wsi", 0)
        self._data.setdefault("disease_data", {})[disease_id] = {
            "sample_size": entry.get("sample_size")
            or {
                "disease_id": disease_id,
                "total_cases": total,
                "total_wsi_slides": catalog.get("total_wsi_slides", 0),
                "cases_with_wsi": pools.get("has_wsi", total),
            },
            "tasks": entry.get("tasks") or [],
            "annotations": entry.get("annotations") or [],
            "followup": entry.get("followup") or {},
            "molecular_markers": (entry.get("molecular") or {}).get("molecular_markers", []),
            "feasibility_pools": pools,
            "wsi_specs": entry.get("wsi_specs") or {},
        }
        if disease_id not in self._by_id and catalog:
            self._by_id[disease_id] = catalog
            self._data.setdefault("diseases", []).append(catalog)

    def _disease_data(self, disease_id: str) -> dict:
        if disease_id not in self._data.get("disease_data", {}):
            raise ValueError(f"Unknown disease_id: {disease_id}")
        return self._data["disease_data"][disease_id]

    def _pools(self, disease_id: str) -> dict[str, int]:
        return self._disease_data(disease_id).get("feasibility_pools", {})

    @staticmethod
    def _parse_request(request: HypothesisRequest | dict) -> HypothesisRequest:
        if isinstance(request, dict):
            return HypothesisRequest(**{k: v for k, v in request.items() if k != "gap_title"})
        return request

    def feasibility_status(self, score: float) -> str:
        return feasibility_status(score)
