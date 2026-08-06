"""Tests for observed-only feasibility pool building (API-faithful)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from feasibility.landscape_builder import build_feasibility_pools  # noqa: E402


class _FakeApi:
    def sample_count_by_hospital(self, disease_code: str = ""):
        return [
            {
                "PatientCount": 2709,
                "SpecimenCount": 3000,
                "SlideCount": 37037,
            }
        ]

    def list_patients(self, disease_code: str = "", limit: int = 1000):
        return [{"PatientId": f"p{i}"} for i in range(560)]

    def list_disease_attributes(self, limit: int = 1000):
        return []

    def list_molecular_results(self, biomarker_name: str = "", limit: int = 1000):
        return []


def test_cohort_base_from_hospital_stats_not_list_length():
    built = build_feasibility_pools(_FakeApi(), "C_CA")
    pools = built["pools"]
    assert built["cohort_base"] == 2709
    assert pools["has_wsi"] == 2709
    assert built["patient_list_coverage"] == {
        "enumerated": 560,
        "catalog_total": 2709,
    }
    assert "has_survival_label" not in pools
    assert "meets_followup_12m" not in pools
    assert built["pool_provenance"]["has_survival_label"] == "unverifiable"
    assert built["pool_provenance"]["meets_followup_12m"] == "unverifiable"


def test_missing_annotation_attrs_are_zero_not_floored():
    pools = build_feasibility_pools(_FakeApi(), "C_CA")["pools"]
    assert pools["has_tumor_region"] == 0
    assert pools["has_tnm_stage"] == 0
    assert pools["has_who_grade"] == 0


def test_sparse_tnm_keeps_observed_count():
    api = _FakeApi()

    def attrs(limit: int = 1000):
        return [
            {
                "PatientId": "p0",
                "AttributeNameZh": "TNM分期",
                "OptionNameZh": "stage",
                "TextValue": "II",
            }
        ]

    api.list_disease_attributes = attrs  # type: ignore[method-assign]
    pools = build_feasibility_pools(api, "C_CA")["pools"]
    assert pools["has_tnm_stage"] == 1


def test_tumor_region_uses_real_count_when_present():
    api = _FakeApi()

    def attrs(limit: int = 1000):
        return [
            {
                "PatientId": f"p{i}",
                "AttributeNameZh": "肿瘤区域",
                "OptionNameZh": "tumor",
                "TextValue": "segment",
            }
            for i in range(20)
        ]

    api.list_disease_attributes = attrs  # type: ignore[method-assign]
    pools = build_feasibility_pools(api, "C_CA")["pools"]
    assert pools["has_tumor_region"] == 20
