"""Unit tests for pathology feasibility client (mock fixtures, no LLM)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ["PATHOLOGY_DATA_PROVIDER"] = "mock"

import config

config.PATHOLOGY_DATA_PROVIDER = "mock"

from feasibility.mock_client import MockPathologyDataClient as PathologyDataClient
from feasibility.disease_mapper import map_gap_to_disease
from feasibility.hypothesis import HypothesisRequest
from evolution_agent import evolve_hypothesis
import analysis.feasibility_tools as feasibility_tools

feasibility_tools._client = PathologyDataClient()
evolve_hypothesis.__globals__.setdefault("_client", None)
from feasibility.client import get_pathology_client
# evolution_agent holds module-level client; rebind to mock
import evolution_agent as evolution_agent_mod

evolution_agent_mod._client = PathologyDataClient()


def test_get_diseases():
    client = PathologyDataClient()
    result = client.get_diseases(min_cases=50)
    assert result["total_disease_types"] >= 5
    assert any(d["disease_id"] == "GC-ADC" for d in result["diseases"])


def test_assess_feasibility_gc_survival():
    client = PathologyDataClient()
    req = HypothesisRequest(
        disease_id="GC-ADC",
        task_type="survival_prediction",
        required_labels=["overall_survival_months", "death_event"],
        required_annotations=["tnm_stage"],
        min_followup_months=12,
    )
    result = client.assess_feasibility(req)
    assert "feasibility_score" in result
    assert result["available_cohort_size"] > 0
    assert result["recommendation"] in ("FEASIBLE", "MARGINAL", "RISKY", "INSUFFICIENT")


def test_assess_feasibility_msi_bottleneck():
    client = PathologyDataClient()
    req = HypothesisRequest(
        disease_id="GC-ADC",
        task_type="survival_prediction",
        required_labels=["overall_survival_months"],
        required_molecular_markers=["MSI_status"],
        required_annotations=["tnm_stage"],
        min_followup_months=12,
        subgroup_filters={"stage": ["III", "IV"]},
    )
    result = client.assess_feasibility(req)
    assert result["feasibility_score"] < 0.9
    assert result["breakdown"]["all_criteria_met"] <= 743


def test_gap_analysis_suggestions():
    client = PathologyDataClient()
    req = HypothesisRequest(
        disease_id="GC-ADC",
        required_molecular_markers=["MSI_status"],
        required_labels=["overall_survival_months"],
    )
    gap = client.gap_analysis(req)
    assert "alternative_hypothesis_suggestions" in gap
    assert len(gap["alternative_hypothesis_suggestions"]) >= 1


def test_disease_mapper_gastric():
    client = PathologyDataClient()
    disease_id, conf, reason = map_gap_to_disease(
        "胃腺癌 radiomics 生存预测研究空白", client=client
    )
    assert disease_id == "GC-ADC"
    assert conf >= 0.8


def test_disease_mapper_nsclc():
    disease_id, _, _ = map_gap_to_disease("NSCLC lung adenocarcinoma deep learning gap")
    assert disease_id == "NSCLC-ADC"


def test_gap_disease_hint_npc_does_not_default_to_brca():
    """NPC gaps must not inherit the old BRCA-IDC hard-default."""
    from idea_agent import _gap_anchor_block, _gap_disease_hint

    disease_id, reason = _gap_disease_hint(
        "Nasopharyngeal carcinoma radiomics prognosis deep learning gap"
    )
    assert disease_id != "BRCA-IDC"
    assert "BRCA-IDC" not in reason or "never" in reason.lower()
    block = _gap_anchor_block(
        "Nasopharyngeal carcinoma radiomics prognosis deep learning gap"
    )
    assert "disease_id=BRCA-IDC" not in block or "never" in block.lower()
    assert "Prefer disease_id=BRCA-IDC" not in block
    assert "default for breast-related" not in block
    # Soft rule when unmapped under mock: instruct catalog lookup, do not force BRCA
    if disease_id is None:
        assert "pathology_disease_catalog" in block or "text_disease_matches" in block
        assert "Write the full proposal in **English**" in block or "English" in block


def test_gap_disease_hint_breast_still_maps_brca():
    from idea_agent import _gap_disease_hint

    disease_id, reason = _gap_disease_hint("Breast cancer multifocal pathomics gap")
    assert disease_id == "BRCA-IDC"
    assert disease_id in reason or "breast" in reason.lower() or "乳腺" in reason or "alias" in reason.lower()


def test_evolve_removes_msi():
    client = PathologyDataClient()
    req = HypothesisRequest(
        disease_id="GC-ADC",
        required_molecular_markers=["MSI_status"],
        required_labels=["overall_survival_months"],
        min_followup_months=12,
    )
    gap = client.gap_analysis(req)
    refined, log = evolve_hypothesis(req, gap, max_iterations=2)
    assert "MSI_status" not in refined.required_molecular_markers or len(log) >= 1


def test_tool_feasibility_assess_without_hypothesis_id():
    from analysis.feasibility_tools import tool_feasibility_assess

    result = tool_feasibility_assess(
        disease_id="NSCLC-ADC",
        task_type="survival_prediction",
        required_labels=["overall_survival_months", "death_event"],
        min_followup_months=12,
    )
    assert "error" not in result
    assert result["feasibility_score"] > 0
    assert "hypothesis_id" not in result or result.get("available_cohort_size", 0) > 0


def test_tool_feasibility_assess_missing_disease_id():
    from analysis.feasibility_tools import tool_feasibility_assess

    result = tool_feasibility_assess(disease_id="")
    assert "error" in result


def test_tool_label_alias_normalization():
    from analysis.feasibility_tools import tool_feasibility_assess

    result = tool_feasibility_assess(
        disease_id="NSCLC-ADC",
        required_labels=["overall_survival"],
        required_molecular_markers=["EGFR"],
        min_followup_months=12,
    )
    assert "error" not in result
    assert result["available_cohort_size"] > 0


def test_tool_feasibility_assess_empty_call():
    from analysis.feasibility_tools import tool_feasibility_assess, tool_data_gap_analysis

    assert "error" in tool_feasibility_assess()
    assert "error" in tool_data_gap_analysis()


def test_parse_tool_arguments():
    from analysis.agent_utils import _parse_tool_arguments, _sanitize_tool_arguments

    assert _parse_tool_arguments("") == {}
    assert _parse_tool_arguments("not json") == {}
    assert _parse_tool_arguments('{"disease_id":"GC-ADC"}')["disease_id"] == "GC-ADC"
    assert _sanitize_tool_arguments("invalid") == "{}"
    assert "GC-ADC" in _sanitize_tool_arguments('{"disease_id":"GC-ADC"}')


def test_feasibility_status_thresholds():
    client = PathologyDataClient()
    assert client.feasibility_status(0.85) == "APPROVED"
    assert client.feasibility_status(0.6) == "REFINED"
    assert client.feasibility_status(0.3) == "RISKY"
    assert client.feasibility_status(0.1) == "REJECTED_DATA_INSUFFICIENT"


if __name__ == "__main__":
    tests = [
        test_get_diseases,
        test_assess_feasibility_gc_survival,
        test_assess_feasibility_msi_bottleneck,
        test_gap_analysis_suggestions,
        test_disease_mapper_gastric,
        test_disease_mapper_nsclc,
        test_gap_disease_hint_npc_does_not_default_to_brca,
        test_gap_disease_hint_breast_still_maps_brca,
        test_evolve_removes_msi,
        test_tool_feasibility_assess_without_hypothesis_id,
        test_tool_feasibility_assess_missing_disease_id,
        test_tool_label_alias_normalization,
        test_tool_feasibility_assess_empty_call,
        test_parse_tool_arguments,
        test_feasibility_status_thresholds,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    sys.exit(1 if failed else 0)
