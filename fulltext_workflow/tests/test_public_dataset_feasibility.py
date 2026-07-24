"""Tests for V-03 public dataset feasibility."""
from __future__ import annotations

import analysis.public_dataset_feasibility as pdf
from analysis.feasibility_tools import FEASIBILITY_TOOLS, FEASIBILITY_TOOL_SCHEMAS


def test_alias_hit_known_benchmarks():
    assert pdf.alias_hit("Camelyon17") is True
    assert pdf.alias_hit("TCGA-BRCA") is True
    assert pdf.alias_hit("random hospital slides 2024") is False


def test_assess_none_when_no_topic_papers(monkeypatch):
    monkeypatch.setattr(
        pdf,
        "resolve_topic_pmids",
        lambda kw: ([], "no_match"),
    )
    out = pdf.assess_public_datasets("totally unknown topic xyz")
    assert out["status"] == "NONE"
    assert out["topic_paper_cnt"] == 0
    assert out["recommended_public"] == []
    assert out["public_coverage_score"] == 0.0


def test_assess_ok_via_alias_without_focus_in_name(monkeypatch):
    """Dataset name has no focus token; selected via topic PMIDs."""
    monkeypatch.setattr(
        pdf,
        "resolve_topic_pmids",
        lambda kw: (["1001", "1002", "1003"], "full_phrase"),
    )

    def fake_query(pmids):
        assert pmids == ["1001", "1002", "1003"]
        return [
            {
                "dataset": "camelyon17",
                "access_class": "public",
                "used_by_papers": 2,
                "example_pmids": ["1001", "1002"],
            },
            {
                "dataset": "in-house cohort",
                "access_class": "private",
                "used_by_papers": 1,
                "example_pmids": ["1003"],
            },
        ]

    monkeypatch.setattr(pdf, "_query_datasets_for_pmids", fake_query)
    out = pdf.assess_public_datasets("breast cancer metastasis")
    assert out["status"] == "OK"
    assert out["recommended_public"][0]["dataset"] == "camelyon17"
    assert out["recommended_public"][0]["alias_hit"] is True
    assert out["other_datasets"][0]["access_class"] == "private"
    assert out["public_coverage_score"] > 0


def test_assess_weak_public_without_alias_or_coverage(monkeypatch):
    monkeypatch.setattr(
        pdf,
        "resolve_topic_pmids",
        lambda kw: (["2001"], "full_phrase"),
    )
    monkeypatch.setattr(
        pdf,
        "_query_datasets_for_pmids",
        lambda pmids: [
            {
                "dataset": "obscure-open-slides",
                "access_class": "public",
                "used_by_papers": 1,
                "example_pmids": ["2001"],
            }
        ],
    )
    out = pdf.assess_public_datasets("rare disease")
    assert out["status"] == "WEAK"
    assert out["recommended_public"]


def test_assess_none_only_private(monkeypatch):
    monkeypatch.setattr(
        pdf,
        "resolve_topic_pmids",
        lambda kw: (["3001"], "full_phrase"),
    )
    monkeypatch.setattr(
        pdf,
        "_query_datasets_for_pmids",
        lambda pmids: [
            {
                "dataset": "our hospital wsi",
                "access_class": "private",
                "used_by_papers": 4,
                "example_pmids": ["3001"],
            }
        ],
    )
    out = pdf.assess_public_datasets("some topic")
    assert out["status"] == "NONE"


def test_tool_registered():
    assert "public_dataset_assess" in FEASIBILITY_TOOLS
    names = [s["function"]["name"] for s in FEASIBILITY_TOOL_SCHEMAS]
    assert "public_dataset_assess" in names
