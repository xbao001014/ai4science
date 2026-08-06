"""API-faithful assessment: no floors; unverifiable requirements listed."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.feasibility_tools import (  # noqa: E402
    normalize_feasibility_field_lists,
)
from feasibility.assessment import assess_feasibility_from_pools  # noqa: E402
from feasibility.hypothesis import HypothesisRequest  # noqa: E402


def test_normalize_moves_tnm_and_grade_out_of_labels():
    out = normalize_feasibility_field_lists(
        required_labels=[
            "disease_free_survival_months",
            "overall_survival_months",
            "survival_status",
            "tnm_stage",
            "histological_grade",
        ],
        required_annotations=[],
    )
    assert "tnm_stage" not in out["required_labels"]
    assert "who_grade" in out["required_annotations"]
    assert "tnm_stage" in out["required_annotations"]
    assert "overall_survival_months" in out["required_labels"]
    assert "death_event" in out["required_labels"]


def test_flag_off_sparse_tnm_still_tightens(monkeypatch):
    import config

    monkeypatch.setattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", False)
    pools = {
        "cohort_base": 2709,
        "has_wsi": 2709,
        "has_tnm_stage": 1,
        "has_who_grade": 1,
        "enumerated_patients": 560,
    }
    req = HypothesisRequest(
        disease_id="C_CA",
        task_type="grade_classification",
        required_labels=[],
        required_annotations=["tnm_stage", "who_grade"],
        min_followup_months=0,
    )
    result = assess_feasibility_from_pools(req, pools)
    assert result["available_cohort_size"] == 1
    assert result["feasibility_score"] == 0.0
    assert result.get("annotation_assumption") in (None, {})


def test_flag_on_zero_tumor_region_assumes_has_wsi(monkeypatch):
    import config

    monkeypatch.setattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", True)
    pools = {
        "cohort_base": 12066,
        "has_wsi": 12066,
        "has_tumor_region": 0,
        "enumerated_patients": 930,
    }
    req = HypothesisRequest(
        disease_id="C_XR",
        task_type="segmentation",
        required_labels=[],
        required_annotations=["tumor_region"],
        min_followup_months=0,
    )
    result = assess_feasibility_from_pools(req, pools)
    assert result["available_cohort_size"] == 12066
    assert result["feasibility_score"] == 1.0
    aa = result["annotation_assumption"]
    assert aa["assumed_from_wsi"] == ["tumor_region"]
    assert aa["observed"] == []
    assert aa["raw_observed"]["tumor_region"] == 0
    assert aa["assumed_count"] == 12066
    assert result["breakdown"]["has_tumor_region"] == 12066


def test_flag_on_sparse_observed_listed_under_observed(monkeypatch):
    import config

    monkeypatch.setattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", True)
    pools = {
        "cohort_base": 2709,
        "has_wsi": 2709,
        "has_tnm_stage": 1,
    }
    req = HypothesisRequest(
        disease_id="C_CA",
        task_type="classification",
        required_labels=[],
        required_annotations=["tnm_stage"],
        min_followup_months=0,
    )
    result = assess_feasibility_from_pools(req, pools)
    assert result["available_cohort_size"] == 2709
    aa = result["annotation_assumption"]
    assert aa["observed"] == ["tnm_stage"]
    assert aa["assumed_from_wsi"] == []
    assert aa["raw_observed"]["tnm_stage"] == 1
    assert result["breakdown"]["has_tnm_stage"] == 2709


def test_no_wsi_does_not_assume(monkeypatch):
    import config

    monkeypatch.setattr(config, "FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI", True)
    pools = {"cohort_base": 100, "has_wsi": 0, "has_tumor_region": 0}
    req = HypothesisRequest(
        disease_id="X",
        task_type="segmentation",
        required_annotations=["tumor_region"],
    )
    result = assess_feasibility_from_pools(req, pools)
    assert result["available_cohort_size"] == 0
    assert result.get("annotation_assumption") in (None, {})


def test_survival_and_followup_are_unverifiable_even_if_stale_cache_has_numbers():
    pools = {
        "cohort_base": 2709,
        "has_wsi": 2709,
        # Stale estimate-era cache values — must not shrink cohort or inflate score.
        "has_survival_label": 2302,
        "has_death_event": 2302,
        "meets_followup_24m": 1760,
        "all_survival_no_msi": 2031,
    }
    coverage = {"enumerated": 560, "catalog_total": 2709}
    req = HypothesisRequest(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["overall_survival_months", "death_event"],
        required_annotations=[],
        min_followup_months=24,
    )
    result = assess_feasibility_from_pools(
        req, pools, patient_list_coverage=coverage
    )
    assert result["available_cohort_size"] == 2709
    assert result["feasibility_score"] == 1.0
    unverified = set(result["unverified_requirements"])
    assert "overall_survival_months" in unverified
    assert "death_event" in unverified
    assert "min_followup_months" in unverified
    assert result["patient_list_coverage"] == coverage
    assert "has_overall_survival_months" not in result["breakdown"]
