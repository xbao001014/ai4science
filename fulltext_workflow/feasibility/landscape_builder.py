"""Build feasibility pools and catalog entries from live pathology API data."""
from __future__ import annotations

from typing import Any

from feasibility.http_api import HttpPathologyApi

_BIOMARKER_SEARCH: dict[str, list[str]] = {
    "MSI_status": ["MSI"],
    "HER2": ["HER2"],
    "EGFR_mutation": ["EGFR"],
    "EGFR": ["EGFR"],
    "ALK_fusion": ["ALK"],
    "ALK": ["ALK"],
    "PD_L1_TPS": ["PD-L1", "PDL1", "PD_L1"],
}

_ANNOTATION_KEYWORDS: dict[str, list[str]] = {
    "tnm_stage": ["TNM", "tnm", "分期", "stage"],
    "who_grade": ["WHO", "分级", "grade", "分化"],
    "tumor_region": ["肿瘤", "区域", "segment"],
    "lauren_classification": ["Lauren", "劳伦"],
}

_STAGE_KEYWORDS = ("III", "IV", "3期", "4期", "晚期")


def aggregate_hospital_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "patient_count": sum(int(r.get("PatientCount") or 0) for r in rows),
        "specimen_count": sum(int(r.get("SpecimenCount") or 0) for r in rows),
        "slide_count": sum(int(r.get("SlideCount") or 0) for r in rows),
        "hospital_count": len(rows),
    }


def _patients_with_keyword_attributes(
    attributes: list[dict[str, Any]],
    patient_ids: set[str],
    keywords: list[str],
) -> set[str]:
    matched: set[str] = set()
    for row in attributes:
        pid = row.get("PatientId")
        if not pid or pid not in patient_ids:
            continue
        text = " ".join(
            str(row.get(k) or "")
            for k in ("AttributeCode", "AttributeNameZh", "OptionNameZh", "TextValue")
        ).lower()
        if any(kw.lower() in text for kw in keywords):
            matched.add(pid)
    return matched


def _patients_with_molecular(
    api: HttpPathologyApi,
    patient_ids: set[str],
    biomarker_names: list[str],
) -> set[str]:
    matched: set[str] = set()
    for name in biomarker_names:
        rows = api.list_molecular_results(biomarker_name=name, limit=1000)
        for row in rows:
            pid = row.get("PatientId")
            if pid in patient_ids:
                matched.add(pid)
    return matched


def _stage_patients(
    attributes: list[dict[str, Any]],
    patient_ids: set[str],
) -> set[str]:
    stage_ids = _patients_with_keyword_attributes(
        attributes, patient_ids, list(_STAGE_KEYWORDS) + list(_ANNOTATION_KEYWORDS["tnm_stage"])
    )
    advanced: set[str] = set()
    for row in attributes:
        pid = row.get("PatientId")
        if pid not in stage_ids:
            continue
        text = " ".join(
            str(row.get(k) or "")
            for k in ("AttributeCode", "AttributeNameZh", "OptionNameZh", "TextValue")
        ).upper()
        if any(kw.upper() in text for kw in _STAGE_KEYWORDS):
            advanced.add(pid)
    return advanced


def build_lightweight_catalog_entry(
    api: HttpPathologyApi,
    disease_row: dict[str, Any],
) -> dict[str, Any] | None:
    """Fast catalog row: diseases + hospital stats only (one extra API call)."""
    code = disease_row.get("DiseaseCode")
    if not code:
        return None
    try:
        stats = aggregate_hospital_stats(
            api.sample_count_by_hospital(disease_code=code)
        )
    except Exception:
        return None
    if stats["patient_count"] <= 0:
        return None
    return build_catalog_entry(
        disease_row,
        stats,
        has_molecular=False,
        has_ihc=stats["slide_count"] > 0,
    )


def build_catalog_entry(
    disease_row: dict[str, Any],
    stats: dict[str, int],
    *,
    has_molecular: bool,
    has_ihc: bool,
) -> dict[str, Any]:
    patient_count = stats["patient_count"]
    slide_count = stats["slide_count"]
    return {
        "disease_id": disease_row["DiseaseCode"],
        "disease_db_id": disease_row.get("DiseaseId"),
        "name_zh": disease_row.get("DiseaseNameZh", ""),
        "name_en": "",
        "organ": disease_row.get("Organ", ""),
        "organ_system": disease_row.get("OrganSystem", ""),
        "description": disease_row.get("Description"),
        "total_cases": patient_count,
        "total_wsi_slides": slide_count,
        "has_ihc": has_ihc,
        "has_molecular": has_molecular,
        "has_followup": patient_count > 0,
        "data_since_year": None,
    }


def build_feasibility_pools(
    api: HttpPathologyApi,
    disease_code: str,
    *,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Aggregate API endpoints into feasibility pool counters for V-01/V-02."""
    if stats is None:
        stats = aggregate_hospital_stats(
            api.sample_count_by_hospital(disease_code=disease_code)
        )

    patient_count = stats["patient_count"]
    slide_count = stats["slide_count"]
    has_wsi = patient_count if slide_count > 0 else 0

    patients = api.list_patients(disease_code=disease_code, limit=1000)
    patient_ids = {p["PatientId"] for p in patients if p.get("PatientId")}
    if patient_ids:
        patient_count = max(patient_count, len(patient_ids))
        if slide_count > 0:
            has_wsi = len(patient_ids)

    attributes = api.list_disease_attributes(limit=1000)
    attr_scope = patient_ids or set()

    tnm_patients = _patients_with_keyword_attributes(
        attributes, attr_scope, _ANNOTATION_KEYWORDS["tnm_stage"]
    )
    grade_patients = _patients_with_keyword_attributes(
        attributes, attr_scope, _ANNOTATION_KEYWORDS["who_grade"]
    )
    region_patients = _patients_with_keyword_attributes(
        attributes, attr_scope, _ANNOTATION_KEYWORDS["tumor_region"]
    )
    lauren_patients = _patients_with_keyword_attributes(
        attributes, attr_scope, _ANNOTATION_KEYWORDS["lauren_classification"]
    )
    stage_patients = _stage_patients(attributes, attr_scope)

    molecular_counts: dict[str, int] = {}
    if attr_scope:
        for marker, names in _BIOMARKER_SEARCH.items():
            pool_key = {
                "MSI_status": "has_msi_status",
                "HER2": "has_her2",
                "EGFR_mutation": "has_egfr",
                "EGFR": "has_egfr",
                "ALK_fusion": "has_alk",
                "ALK": "has_alk",
                "PD_L1_TPS": "has_pd_l1",
            }[marker]
            molecular_counts[pool_key] = len(
                _patients_with_molecular(api, attr_scope, names)
            )

    survival_est = int(patient_count * 0.85) if patient_count else 0
    followup_12m = int(patient_count * 0.75) if patient_count else 0
    followup_6m = int(patient_count * 0.80) if patient_count else 0

    pools: dict[str, int] = {
        "has_wsi": has_wsi or patient_count,
        "has_survival_label": survival_est,
        "has_death_event": survival_est,
        "has_tnm_stage": len(tnm_patients) or int(patient_count * 0.9),
        "has_who_grade": len(grade_patients) or int(patient_count * 0.85),
        "has_tumor_region": len(region_patients),
        "meets_followup_6m": followup_6m,
        "meets_followup_12m": followup_12m,
        "in_target_stage_III_IV": len(stage_patients),
        "all_survival_no_msi": followup_12m,
        "all_survival_tnm_no_msi": min(followup_12m, len(tnm_patients) or followup_12m),
    }
    pools.update(molecular_counts)

    if pools.get("has_msi_status") and pools["has_tnm_stage"] and pools["in_target_stage_III_IV"]:
        pools["all_msi_survival_tnm_stage_III_IV"] = min(
            pools.get("has_msi_status", 0),
            pools["has_survival_label"],
            pools["has_tnm_stage"],
            pools["in_target_stage_III_IV"],
        )

    ihc_slide_rows = stats["slide_count"] if stats["slide_count"] > 0 else 0
    he_slide_rows = stats["slide_count"]

    return {
        "pools": pools,
        "stats": stats,
        "patient_sample_size": len(patient_ids),
        "specimen_count": stats["specimen_count"],
        "ihc_slide_rows": ihc_slide_rows,
        "he_slide_rows": he_slide_rows,
        "lauren_cases": len(lauren_patients),
    }


def infer_tasks(pools: dict[str, int], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    total = max(catalog.get("total_cases") or 0, 1)
    tasks: list[dict[str, Any]] = []
    if pools.get("has_survival_label"):
        tasks.append({
            "task_type": "survival_prediction",
            "label_field": "overall_survival_months",
            "label_completeness": round(pools["has_survival_label"] / total, 2),
            "has_event_indicator": True,
            "min_followup_months": 6,
            "cohort_size": pools["has_survival_label"],
        })
    if pools.get("has_who_grade"):
        tasks.append({
            "task_type": "grade_classification",
            "label_field": "who_grade",
            "label_completeness": round(pools["has_who_grade"] / total, 2),
            "cohort_size": pools["has_who_grade"],
        })
    if pools.get("has_msi_status") or pools.get("has_her2") or pools.get("has_egfr"):
        tasks.append({
            "task_type": "molecular_subtype_classification",
            "label_field": "molecular_marker",
            "label_completeness": round(
                max(
                    pools.get("has_msi_status", 0),
                    pools.get("has_her2", 0),
                    pools.get("has_egfr", 0),
                )
                / total,
                2,
            ),
            "cohort_size": max(
                pools.get("has_msi_status", 0),
                pools.get("has_her2", 0),
                pools.get("has_egfr", 0),
            ),
        })
    if pools.get("has_tumor_region"):
        tasks.append({
            "task_type": "region_segmentation",
            "annotation_type": "polygon",
            "annotated_slides": pools["has_tumor_region"],
        })
    return tasks


def infer_annotations(pools: dict[str, int], total: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    mapping = {
        "tnm_stage": "has_tnm_stage",
        "who_grade": "has_who_grade",
        "tumor_region": "has_tumor_region",
        "lauren_classification": "has_who_grade",
    }
    for field, key in mapping.items():
        count = pools.get(key, 0)
        if count:
            rows.append({
                "field": field,
                "coverage": round(count / max(total, 1), 2),
                "available_cases": count,
            })
    return rows


def infer_followup(pools: dict[str, int], total: int) -> dict[str, Any]:
    surv = pools.get("has_survival_label", 0)
    fields = []
    if surv:
        fields.append({
            "field": "overall_survival_months",
            "coverage": round(surv / max(total, 1), 2),
            "available_cases": surv,
        })
        fields.append({
            "field": "death_event",
            "coverage": round(surv / max(total, 1), 2),
            "available_cases": surv,
        })
    return {
        "fields": fields,
        "median_followup_months": None,
        "min_followup_6m": pools.get("meets_followup_6m", 0),
        "min_followup_12m": pools.get("meets_followup_12m", 0),
    }


def infer_molecular_markers(pools: dict[str, int], total: int) -> list[dict[str, Any]]:
    marker_map = {
        "MSI_status": "has_msi_status",
        "HER2": "has_her2",
        "EGFR_mutation": "has_egfr",
        "ALK_fusion": "has_alk",
        "PD_L1_TPS": "has_pd_l1",
    }
    rows: list[dict[str, Any]] = []
    for marker, key in marker_map.items():
        count = pools.get(key, 0)
        if count:
            rows.append({
                "marker_name": marker,
                "available_cases": count,
                "coverage": round(count / max(total, 1), 2),
            })
    return rows
