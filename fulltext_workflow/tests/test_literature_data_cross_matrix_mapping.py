"""Regression tests for Fangxin disease mapping in the cross matrix."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import analysis.feasibility_tools as feasibility_tools  # noqa: E402


class _CatalogClient:
    def get_diseases(self, **_kwargs):
        return {
            "total_disease_types": 3,
            "diseases": [
                {
                    "disease_id": "C_CA",
                    "name_en": "",
                    "name_zh": "肠癌",
                    "total_cases": 2709,
                },
                {
                    "disease_id": "C_XR",
                    "name_en": "",
                    "name_zh": "肠息肉",
                    "total_cases": 12066,
                },
                {
                    "disease_id": "W_XR",
                    "name_en": "",
                    "name_zh": "胃息肉",
                    "total_cases": 14789,
                },
            ],
        }


def test_cross_matrix_uses_curated_colorectal_code_with_blank_english_names(
    monkeypatch,
):
    monkeypatch.setattr(feasibility_tools, "_client", _CatalogClient())
    monkeypatch.setattr(
        feasibility_tools,
        "tool_method_disease_combo_gap",
        lambda focus=None: {
            "gaps": [
                {
                    "method": "random forest",
                    "disease": "t1 colorectal cancer",
                    "paper_cnt": 0,
                    "gap": "unexplored",
                }
            ]
        },
    )

    row = feasibility_tools.tool_literature_data_cross_matrix(
        focus="colorectal cancer"
    )["data"][0]

    assert row["disease_id"] == "C_CA"
    assert row["cohort_size"] == 2709


def test_cross_matrix_does_not_match_unknown_disease_via_blank_name(monkeypatch):
    monkeypatch.setattr(feasibility_tools, "_client", _CatalogClient())
    monkeypatch.setattr(
        feasibility_tools,
        "tool_method_disease_combo_gap",
        lambda focus=None: {
            "gaps": [
                {
                    "method": "test method",
                    "disease": "unknown pathology condition",
                    "paper_cnt": 0,
                    "gap": "unexplored",
                }
            ]
        },
    )

    row = feasibility_tools.tool_literature_data_cross_matrix()["data"][0]

    assert row["disease_id"] is None
    assert row["cohort_size"] == 0
    assert row["data_support"] == "low"
