"""Tests for idea session feasibility baseline + tool cache guards."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.idea_session_guards import (  # noqa: E402
    canonicalize_feasibility_args,
    compare_feasibility_specs,
)


def test_canonicalize_sorts_dedupes_lists_and_defaults_followup():
    out = canonicalize_feasibility_args(
        disease_id=" C_CA ",
        task_type="survival_prediction",
        required_labels=["vital_status", "Overall_Survival_Months", "vital_status"],
        required_molecular_markers=None,
        required_annotations=[" tumor_region "],
        min_followup_months=None,
        hypothesis_id="should-be-dropped",
    )
    assert out["disease_id"] == "C_CA"
    assert out["task_type"] == "survival_prediction"
    assert out["required_labels"] == ["Overall_Survival_Months", "vital_status"]
    assert out["required_molecular_markers"] == []
    assert out["required_annotations"] == ["tumor_region"]
    assert out["min_followup_months"] == 0
    assert "hypothesis_id" not in out


def test_compare_same_case_insensitive_lists():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    other = canonicalize_feasibility_args(
        disease_id="c_ca",
        task_type="Survival_Prediction",
        required_labels=["VITAL_STATUS"],
        required_annotations=["TUMOR_REGION"],
        min_followup_months=24,
    )
    assert compare_feasibility_specs(base, other) == "same"


def test_compare_tighter_superset_and_higher_followup():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    tighter = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status", "overall_survival_months"],
        required_annotations=["tumor_region", "stroma_region"],
        min_followup_months=36,
    )
    assert compare_feasibility_specs(base, tighter) == "tighter"


def test_compare_relaxed_when_annotations_cleared():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status", "overall_survival_months"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    relaxed = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status", "overall_survival_months"],
        required_annotations=[],
        min_followup_months=24,
    )
    assert compare_feasibility_specs(base, relaxed) == "relaxed"


def test_compare_mixed_tighter_and_looser_is_relaxed():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["a", "b"],
        required_annotations=["x"],
        min_followup_months=24,
    )
    mixed = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["a", "b", "c"],  # tighter
        required_annotations=[],  # looser
        min_followup_months=24,
    )
    assert compare_feasibility_specs(base, mixed) == "relaxed"


def test_compare_disease_id_change_is_relaxed():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        min_followup_months=24,
    )
    other = canonicalize_feasibility_args(
        disease_id="BRCA-IDC",
        task_type="survival_prediction",
        required_labels=["vital_status", "extra"],
        min_followup_months=36,
    )
    assert compare_feasibility_specs(base, other) == "relaxed"
