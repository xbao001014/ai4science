"""Structured hypothesis request aligned with pathology_data_api_spec V-01/V-02."""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


def new_hypothesis_id(hypothesis_id: str | None = None) -> str:
    """Return a valid hypothesis id without requiring disease_id."""
    if hypothesis_id:
        return hypothesis_id
    return f"H-{uuid.uuid4().hex[:8]}"


class HypothesisRequest(BaseModel):
    hypothesis_id: str = Field(default_factory=lambda: f"H-{uuid.uuid4().hex[:8]}")
    disease_id: str
    task_type: str = "survival_prediction"
    required_labels: list[str] = Field(default_factory=list)
    required_molecular_markers: list[str] = Field(default_factory=list)
    required_annotations: list[str] = Field(default_factory=list)
    min_followup_months: int | None = None
    subgroup_filters: dict[str, list[str]] = Field(default_factory=dict)
    gap_title: str = ""
    gap_text: str = ""

    def to_api_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "hypothesis_id": self.hypothesis_id,
            "disease_id": self.disease_id,
            "task_type": self.task_type,
            "required_labels": self.required_labels,
            "required_molecular_markers": self.required_molecular_markers,
            "required_annotations": self.required_annotations,
        }
        if self.min_followup_months is not None:
            body["min_followup_months"] = self.min_followup_months
        if self.subgroup_filters:
            body["subgroup_filters"] = self.subgroup_filters
        return body

    @classmethod
    def from_gap(
        cls,
        gap_title: str,
        disease_id: str,
        gap_text: str = "",
        task_type: str = "survival_prediction",
    ) -> HypothesisRequest:
        """Build a default hypothesis from a research gap title."""
        labels: list[str] = []
        markers: list[str] = []
        annotations: list[str] = []
        min_followup: int | None = None
        text_lower = (gap_title + " " + gap_text).lower()

        if any(k in text_lower for k in ("survival", "生存", "prognos", "os ", "dfs")):
            task_type = "survival_prediction"
            labels = ["overall_survival_months", "death_event"]
            min_followup = 12
        elif any(k in text_lower for k in ("segment", "分割", "region")):
            task_type = "region_segmentation"
            annotations = ["tumor_region"]
        elif any(k in text_lower for k in ("grade", "分级", "who")):
            task_type = "grade_classification"
            annotations = ["who_grade"]
        elif any(k in text_lower for k in ("molecular", "分子", "msi", "her2", "pd-l1", "pd_l1")):
            task_type = "molecular_subtype_classification"
            if "msi" in text_lower:
                markers = ["MSI_status"]
            if "her2" in text_lower:
                markers = ["HER2"]

        if "tnm" in text_lower or "stage" in text_lower or "分期" in text_lower:
            annotations = list(set(annotations + ["tnm_stage"]))

        return cls(
            disease_id=disease_id,
            task_type=task_type,
            required_labels=labels,
            required_molecular_markers=markers,
            required_annotations=annotations,
            min_followup_months=min_followup,
            gap_title=gap_title,
            gap_text=gap_text,
        )
