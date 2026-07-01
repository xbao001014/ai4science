"""Shared V-01 / V-02 feasibility assessment logic."""
from __future__ import annotations

from typing import Any, Callable

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
    "tumor_region": "has_tumor_region",
    "lauren_classification": "has_who_grade",
}


def assess_feasibility_from_pools(
    req: HypothesisRequest,
    pools: dict[str, int],
    *,
    disease_exists: bool = True,
) -> dict[str, Any]:
    if not disease_exists:
        return {
            "hypothesis_id": req.hypothesis_id,
            "error": f"disease_id not found: {req.disease_id}",
            "feasibility_score": 0.0,
            "recommendation": "INSUFFICIENT",
        }

    breakdown: dict[str, int] = {"has_wsi": pools.get("has_wsi", 0)}
    cohort = breakdown["has_wsi"]

    for label in req.required_labels:
        key = _LABEL_POOL_KEYS.get(label, f"has_{label}")
        cnt = pools.get(key, breakdown["has_wsi"])
        breakdown[f"has_{label}"] = cnt
        cohort = min(cohort, cnt)

    for ann in req.required_annotations:
        key = _ANNOTATION_POOL_KEYS.get(ann, f"has_{ann}")
        cnt = pools.get(key, breakdown["has_wsi"])
        breakdown[f"has_{ann}"] = cnt
        cohort = min(cohort, cnt)

    for marker in req.required_molecular_markers:
        key = _MARKER_POOL_KEYS.get(marker, f"has_{marker.lower()}")
        cnt = pools.get(key, 0)
        breakdown[f"has_{marker}"] = cnt
        cohort = min(cohort, cnt)

    if req.min_followup_months:
        fk = f"meets_followup_{req.min_followup_months}m"
        cnt = pools.get(fk, pools.get("meets_followup_12m", cohort))
        breakdown["meets_followup_threshold"] = cnt
        cohort = min(cohort, cnt)

    stages = (req.subgroup_filters or {}).get("stage", [])
    if stages and any(s in ("III", "IV", "III/IV") for s in stages):
        cnt = pools.get("in_target_stage_III_IV", cohort)
        breakdown["in_target_stage"] = cnt
        cohort = min(cohort, cnt)

    if (
        req.required_molecular_markers
        and "MSI_status" in req.required_molecular_markers
        and req.required_labels
        and stages
    ):
        shortcut = pools.get("all_msi_survival_tnm_stage_III_IV")
        if shortcut is not None:
            cohort = min(cohort, shortcut)

    if req.required_molecular_markers and not req.required_labels:
        pass
    elif not req.required_molecular_markers and req.required_labels:
        alt = pools.get("all_survival_no_msi")
        if alt is not None:
            cohort_no_msi = alt
            if req.required_annotations:
                for ann in req.required_annotations:
                    key = _ANNOTATION_POOL_KEYS.get(ann)
                    if key:
                        cohort_no_msi = min(cohort_no_msi, pools.get(key, cohort_no_msi))
            cohort = cohort_no_msi

    breakdown["all_criteria_met"] = cohort
    base = max(breakdown["has_wsi"], 1)
    score = round(cohort / base, 2)
    score = min(1.0, max(0.0, score))

    recommendation = recommendation_from_score(score, cohort)
    note = note_from_assessment(cohort, score, recommendation)

    return {
        "hypothesis_id": req.hypothesis_id,
        "feasibility_score": score,
        "available_cohort_size": cohort,
        "breakdown": breakdown,
        "recommendation": recommendation,
        "note": note,
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

    wsi = pools.get("has_wsi", 1)
    for marker in req.required_molecular_markers:
        key = _MARKER_POOL_KEYS.get(marker, f"has_{marker.lower()}")
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
            no_msi = pools.get("all_survival_no_msi", avail)
            suggestions.append(
                f"去除{marker}条件，聚焦纯形态学任务（可用样本约{no_msi}例）"
            )

    if req.min_followup_months:
        fk = pools.get(f"meets_followup_{req.min_followup_months}m", 0)
        gaps.append({
            "field": f"min_followup_{req.min_followup_months}months",
            "current_eligible": fk,
            "after_other_filters": assess["available_cohort_size"],
            "bottleneck_severity": "MEDIUM" if fk < 500 else "LOW",
            "suggestion": "样本量可接受，非主要瓶颈" if fk >= 500 else "考虑缩短随访要求或扩大队列年份",
        })

    if not suggestions:
        surv = pools.get("all_survival_no_msi", pools.get("has_survival_label", 0))
        suggestions.append(f"放宽分子标记条件，聚焦形态学+临床标签（可用约{surv}例）")
        if disease_tasks:
            alt_task = next(
                (t["task_type"] for t in disease_tasks if t.get("task_type") != req.task_type),
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


def note_from_assessment(cohort: int, score: float, recommendation: str) -> str:
    if recommendation == "FEASIBLE":
        train = int(cohort * 0.8)
        return (
            f"{cohort}例满足全部条件，建议80/20训练测试划分后训练集{train}例，"
            "可支撑深度学习建模"
        )
    if recommendation == "MARGINAL":
        return f"{cohort}例可用，建议结合迁移学习或数据增强（feasibility_score={score}）"
    if recommendation == "RISKY":
        return f"仅{cohort}例满足条件，风险较高，建议调整假说范围"
    return f"数据不足（{cohort}例），Idea 降级或舍弃"


def feasibility_status(score: float) -> str:
    if score >= config.FEASIBILITY_SCORE_APPROVE:
        return "APPROVED"
    if score >= config.FEASIBILITY_SCORE_MARGINAL:
        return "REFINED"
    if score >= config.FEASIBILITY_SCORE_REJECT:
        return "RISKY"
    return "REJECTED_DATA_INSUFFICIENT"
