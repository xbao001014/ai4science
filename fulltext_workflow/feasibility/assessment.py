"""Shared V-01 / V-02 feasibility assessment logic."""
from __future__ import annotations

from typing import Any

import config
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

_LABEL_POOL_KEYS = {
    "overall_survival_months": "has_survival_label",
    "death_event": "has_death_event",
    "disease_free_survival": "has_survival_label",
}

_ANNOTATION_POOL_KEYS = {
    "tnm_stage": "has_tnm_stage",
    "who_grade": "has_who_grade",
    "histological_grade": "has_who_grade",
    "tumor_region": "has_tumor_region",
    "lauren_classification": "has_who_grade",
}

# Keys that were historically ratio-estimated; never trust numeric values in cache.
_ALWAYS_UNVERIFIABLE_POOL_KEYS = frozenset({
    "has_survival_label",
    "has_death_event",
    "meets_followup_6m",
    "meets_followup_12m",
    "meets_followup_24m",
    "all_survival_no_msi",
    "all_survival_tnm_no_msi",
    "all_msi_survival_tnm_stage_III_IV",
})


def _is_unverifiable_pool_key(
    key: str,
    provenance: dict[str, str] | None,
) -> bool:
    if key in _ALWAYS_UNVERIFIABLE_POOL_KEYS:
        return True
    if provenance and provenance.get(key) == "unverifiable":
        return True
    return False


def assess_feasibility_from_pools(
    req: HypothesisRequest,
    pools: dict[str, int],
    *,
    disease_exists: bool = True,
    pool_provenance: dict[str, str] | None = None,
    patient_list_coverage: dict[str, int] | None = None,
) -> dict[str, Any]:
    if not disease_exists:
        return {
            "hypothesis_id": req.hypothesis_id,
            "error": f"disease_id not found: {req.disease_id}",
            "feasibility_score": 0.0,
            "recommendation": "INSUFFICIENT",
            "unverified_requirements": [],
            "cohort_base": 0,
            "patient_list_coverage": patient_list_coverage or {},
            "annotation_assumption": None,
        }

    provenance = pool_provenance or {}
    cohort_base = int(
        pools["cohort_base"]
        if pools.get("cohort_base") is not None
        else (pools.get("has_wsi") or 0)
    )
    breakdown: dict[str, int] = {
        "has_wsi": int(pools.get("has_wsi") or cohort_base or 0),
    }
    if pools.get("cohort_base") is not None:
        breakdown["cohort_base"] = cohort_base
    cohort = cohort_base
    unverified: list[str] = []

    ann_observed: list[str] = []
    ann_assumed: list[str] = []
    raw_observed: dict[str, int] = {}
    assume = bool(getattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", False))
    _pools_wsi = pools.get("has_wsi")
    has_wsi = (
        int(_pools_wsi)
        if _pools_wsi is not None
        else int(breakdown.get("has_wsi") or 0)
    )

    for label in req.required_labels:
        key = _LABEL_POOL_KEYS.get(label, f"has_{label}")
        if _is_unverifiable_pool_key(key, provenance) or key not in pools:
            # Labels without an observed pool (incl. estimate-era keys) are unverifiable.
            if key in _ALWAYS_UNVERIFIABLE_POOL_KEYS or key not in pools:
                unverified.append(label)
                continue
        cnt = int(pools[key])
        breakdown[f"has_{label}"] = cnt
        cohort = min(cohort, cnt)

    for ann in req.required_annotations:
        key = _ANNOTATION_POOL_KEYS.get(ann, f"has_{ann}")
        if _is_unverifiable_pool_key(key, provenance):
            unverified.append(ann)
            continue
        raw = int(pools[key]) if key in pools else 0
        raw_observed[ann] = raw
        if assume and has_wsi > 0:
            cnt = has_wsi
            if raw > 0:
                ann_observed.append(ann)
            else:
                ann_assumed.append(ann)
        else:
            cnt = raw
        breakdown[f"has_{ann}"] = cnt
        cohort = min(cohort, cnt)

    for marker in req.required_molecular_markers:
        key = _MARKER_POOL_KEYS.get(marker, f"has_{marker.lower()}")
        if _is_unverifiable_pool_key(key, provenance):
            unverified.append(marker)
            continue
        cnt = int(pools[key]) if key in pools else 0
        breakdown[f"has_{marker}"] = cnt
        cohort = min(cohort, cnt)

    if req.min_followup_months:
        fk = f"meets_followup_{req.min_followup_months}m"
        if _is_unverifiable_pool_key(fk, provenance) or fk not in pools:
            unverified.append("min_followup_months")
        else:
            cnt = int(pools[fk])
            breakdown["meets_followup_threshold"] = cnt
            cohort = min(cohort, cnt)

    stages = (req.subgroup_filters or {}).get("stage", [])
    if stages and any(s in ("III", "IV", "III/IV") for s in stages):
        key = "in_target_stage_III_IV"
        if _is_unverifiable_pool_key(key, provenance):
            unverified.append("stage")
        else:
            cnt = int(pools[key]) if key in pools else 0
            breakdown["in_target_stage"] = cnt
            cohort = min(cohort, cnt)

    if (
        req.required_molecular_markers
        and "MSI_status" in req.required_molecular_markers
        and req.required_labels
        and stages
    ):
        shortcut_key = "all_msi_survival_tnm_stage_III_IV"
        if (
            shortcut_key in pools
            and not _is_unverifiable_pool_key(shortcut_key, provenance)
        ):
            cohort = min(cohort, int(pools[shortcut_key]))

    breakdown["all_criteria_met"] = cohort
    base = max(cohort_base, 1)
    score = round(cohort / base, 2)
    score = min(1.0, max(0.0, score))

    recommendation = recommendation_from_score(score, cohort)
    annotation_assumption = None
    if assume and has_wsi > 0 and (ann_observed or ann_assumed):
        annotation_assumption = {
            "observed": ann_observed,
            "assumed_from_wsi": ann_assumed,
            "raw_observed": raw_observed,
            "assumed_count": has_wsi,
        }
    note = note_from_assessment(
        cohort, score, recommendation, unverified, ann_assumed or None
    )

    coverage = patient_list_coverage or {}
    if not coverage and pools.get("enumerated_patients") is not None:
        coverage = {
            "enumerated": int(pools.get("enumerated_patients") or 0),
            "catalog_total": cohort_base,
        }

    seen: set[str] = set()
    unverified_unique: list[str] = []
    for item in unverified:
        if item not in seen:
            seen.add(item)
            unverified_unique.append(item)

    return {
        "hypothesis_id": req.hypothesis_id,
        "feasibility_score": score,
        "available_cohort_size": cohort,
        "cohort_base": cohort_base,
        "breakdown": breakdown,
        "recommendation": recommendation,
        "note": note,
        "unverified_requirements": unverified_unique,
        "patient_list_coverage": coverage,
        "annotation_assumption": annotation_assumption,
    }


def gap_analysis_from_pools(
    req: HypothesisRequest,
    pools: dict[str, int],
    assess: dict[str, Any],
    *,
    disease_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gaps: list[dict] = []
    suggestions: list[str] = []

    wsi = pools.get("has_wsi") or pools.get("cohort_base") or 1
    for marker in req.required_molecular_markers:
        key = _MARKER_POOL_KEYS.get(marker, f"has_{marker.lower()}")
        if key in _ALWAYS_UNVERIFIABLE_POOL_KEYS:
            gaps.append({
                "field": marker.lower(),
                "current_coverage": None,
                "required_coverage": 0.70,
                "bottleneck_severity": "MEDIUM",
                "suggestion": f"{marker} 接口覆盖不可验证，勿用估算补全",
            })
            continue
        avail = pools.get(key, 0)
        cov = round(avail / max(wsi, 1), 2)
        severity = "HIGH" if cov < 0.5 else "MEDIUM" if cov < 0.7 else "LOW"
        if severity != "LOW":
            gaps.append({
                "field": marker.lower(),
                "current_coverage": cov,
                "required_coverage": 0.70,
                "bottleneck_severity": severity,
                "suggestion": (
                    f"可降级为不依赖{marker}的形态学预测任务，"
                    f"或限定近年病例作为研究队列"
                ),
            })
            suggestions.append(
                f"去除{marker}条件，聚焦纯形态学任务（方信观测样本见 V-01 breakdown）"
            )

    if req.min_followup_months:
        gaps.append({
            "field": f"min_followup_{req.min_followup_months}months",
            "current_eligible": None,
            "after_other_filters": assess["available_cohort_size"],
            "bottleneck_severity": "MEDIUM",
            "suggestion": "随访月数无方信实测计数接口，已标为 unverifiable",
        })

    if not suggestions:
        suggestions.append(
            "仅基于方信可验证观测条件收紧队列；未验证项见 unverified_requirements"
        )
        if disease_tasks:
            alt_task = next(
                (
                    t["task_type"]
                    for t in disease_tasks
                    if t.get("task_type") != req.task_type
                ),
                "grade_classification",
            )
            suggestions.append(f"切换任务类型为 {alt_task} 以提高可用样本量")

    return {
        "hypothesis_id": req.hypothesis_id,
        "gaps": gaps,
        "alternative_hypothesis_suggestions": suggestions[:3],
        "prior_assessment": assess,
    }


def recommendation_from_score(score: float, cohort: int) -> str:
    if score >= config.FEASIBILITY_SCORE_APPROVE and cohort >= 500:
        return "FEASIBLE"
    if score >= config.FEASIBILITY_SCORE_MARGINAL or cohort >= 200:
        return "MARGINAL"
    if score >= config.FEASIBILITY_SCORE_REJECT or cohort >= 50:
        return "RISKY"
    return "INSUFFICIENT"


def note_from_assessment(
    cohort: int,
    score: float,
    recommendation: str,
    unverified: list[str] | None = None,
    assumed_annotations: list[str] | None = None,
) -> str:
    unverified = unverified or []
    suffix = ""
    if unverified:
        suffix = f"；另有未验证要求（不计入交集）: {', '.join(unverified)}"
    if assumed_annotations:
        suffix += f"；标注临时假定(有WSI): {', '.join(assumed_annotations)}"

    if recommendation == "FEASIBLE":
        train = int(cohort * 0.8)
        return (
            f"{cohort}例满足已验证条件，建议80/20训练测试划分后训练集{train}例，"
            f"可支撑深度学习建模{suffix}"
        )
    if recommendation == "MARGINAL":
        return (
            f"{cohort}例满足已验证条件，建议结合迁移学习或数据增强"
            f"（feasibility_score={score}）{suffix}"
        )
    if recommendation == "RISKY":
        return f"仅{cohort}例满足已验证条件，风险较高，建议调整假说范围{suffix}"
    return f"数据不足（{cohort}例已验证），Idea 降级或舍弃{suffix}"


def feasibility_status(score: float) -> str:
    if score >= config.FEASIBILITY_SCORE_APPROVE:
        return "APPROVED"
    if score >= config.FEASIBILITY_SCORE_MARGINAL:
        return "REFINED"
    if score >= config.FEASIBILITY_SCORE_REJECT:
        return "RISKY"
    return "REJECTED_DATA_INSUFFICIENT"
