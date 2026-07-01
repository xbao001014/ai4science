"""Evolution Agent: refine hypotheses using V-02 gap analysis suggestions."""
from __future__ import annotations

import re
from typing import Any

from feasibility.client import PathologyDataClient
from feasibility.hypothesis import HypothesisRequest

_client = PathologyDataClient()


def evolve_hypothesis(
    request: HypothesisRequest,
    gap_result: dict[str, Any],
    max_iterations: int = 2,
) -> tuple[HypothesisRequest, list[dict[str, Any]]]:
    """
    Rule-based evolution using alternative_hypothesis_suggestions from V-02.

    Returns (refined_request, evolution_log).
    """
    log: list[dict[str, Any]] = []
    current = request

    for iteration in range(1, max_iterations + 1):
        assess = _client.assess_feasibility(current)
        score = assess.get("feasibility_score", 0)
        status = _client.feasibility_status(score)

        log.append({
            "iteration": iteration,
            "action": "assess",
            "feasibility_score": score,
            "status": status,
            "available_cohort_size": assess.get("available_cohort_size"),
        })

        if score >= 0.8:
            break

        if score < 0.2:
            log.append({"iteration": iteration, "action": "reject", "reason": "score below 0.2"})
            break

        gap = gap_result if iteration == 1 else _client.gap_analysis(current)
        suggestions = gap.get("alternative_hypothesis_suggestions", [])
        refined = _apply_suggestions(current, suggestions)
        if refined.model_dump() == current.model_dump():
            log.append({"iteration": iteration, "action": "no_change", "suggestions": suggestions})
            break

        log.append({
            "iteration": iteration,
            "action": "refine",
            "suggestions_applied": suggestions[:2],
            "before": current.to_api_body(),
            "after": refined.to_api_body(),
        })
        current = refined

    return current, log


def _apply_suggestions(
    req: HypothesisRequest,
    suggestions: list[str],
) -> HypothesisRequest:
    text = " ".join(suggestions).lower()
    new = req.model_copy(deep=True)

    if any(k in text for k in ("去除msi", "remove msi", "不依赖msi", "纯形态学")):
        new.required_molecular_markers = [
            m for m in new.required_molecular_markers
            if m.lower() not in ("msi_status", "msi")
        ]

    if any(k in text for k in ("去除her2", "不依赖her2")):
        new.required_molecular_markers = [
            m for m in new.required_molecular_markers if m.upper() != "HER2"
        ]

    if "grade_classification" in text or "分级" in text:
        new.task_type = "grade_classification"
        new.required_labels = []
        new.required_molecular_markers = []
        if not new.required_annotations:
            new.required_annotations = ["who_grade"]

    if "segmentation" in text or "分割" in text:
        new.task_type = "region_segmentation"
        new.required_labels = []
        new.required_molecular_markers = []
        new.min_followup_months = None

    m = re.search(r"切换任务类型为\s*(\w+)", " ".join(suggestions))
    if m:
        new.task_type = m.group(1)

    if any(k in text for k in ("缩短随访", "放宽随访")) and new.min_followup_months:
        new.min_followup_months = max(6, (new.min_followup_months or 12) - 6)

    if "stage" in text or "分期" in text:
        new.subgroup_filters = {}

    if not new.required_molecular_markers and not new.required_labels:
        new.task_type = "survival_prediction"
        new.required_labels = ["overall_survival_months", "death_event"]
        new.min_followup_months = new.min_followup_months or 12

    return new
