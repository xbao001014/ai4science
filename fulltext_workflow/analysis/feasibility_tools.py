"""LLM-callable tools for pathology data feasibility verification."""
from __future__ import annotations

from typing import Any, Callable

import config
from analysis.gap_tools import tool_method_disease_combo_gap, _combo_support_papers
from analysis.impact_scoring import aggregate_paper_impact, total_priority_score
from feasibility.client import PathologyDataClient
from feasibility.hypothesis import HypothesisRequest, new_hypothesis_id
from feasibility.http_api import HttpPathologyApi, PathologyHttpError
from feasibility.v11_queries import (
    attribute_distribution,
    disease_patient_count,
    molecular_positivity,
    subtype_distribution,
    text_disease_match_summary,
)

_client = PathologyDataClient()

_LABEL_ALIASES = {
    "overall_survival": "overall_survival_months",
    "os": "overall_survival_months",
    "progression_free_survival": "overall_survival_months",
    "progression_free_survival_months": "overall_survival_months",
    "dfs": "overall_survival_months",
}

_MARKER_ALIASES = {
    "egfr": "EGFR_mutation",
    "egfr_mutation": "EGFR_mutation",
    "alk": "ALK_fusion",
    "alk_fusion": "ALK_fusion",
    "pd-l1": "PD_L1_TPS",
    "pd_l1": "PD_L1_TPS",
    "pd_l1_tps": "PD_L1_TPS",
    "msi": "MSI_status",
    "msi_status": "MSI_status",
    "her2": "HER2",
}

_ANNOTATION_ALIASES = {
    "tumor_region": "tumor_region",
    "tumor_segmentation": "tumor_region",
    "stroma_region": "tumor_region",
    "necrosis_region": "tumor_region",
    "lymph_node_status": "tnm_stage",
}


def _normalize_list(values: list[str] | None, aliases: dict[str, str]) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for v in values:
        key = v.strip().lower().replace("-", "_")
        out.append(aliases.get(key, v))
    return list(dict.fromkeys(out))


def _build_hypothesis_request(
    disease_id: str | None,
    task_type: str = "survival_prediction",
    required_labels: list[str] | None = None,
    required_molecular_markers: list[str] | None = None,
    required_annotations: list[str] | None = None,
    min_followup_months: int | None = None,
    hypothesis_id: str | None = None,
) -> HypothesisRequest | dict:
    if not disease_id or not str(disease_id).strip():
        return {
            "error": "disease_id is required",
            "description": "研究假说可行性评估 (V-01) — missing disease_id",
        }
    return HypothesisRequest(
        hypothesis_id=new_hypothesis_id(hypothesis_id),
        disease_id=str(disease_id).strip(),
        task_type=task_type or "survival_prediction",
        required_labels=_normalize_list(required_labels, _LABEL_ALIASES),
        required_molecular_markers=_normalize_list(required_molecular_markers, _MARKER_ALIASES),
        required_annotations=_normalize_list(required_annotations, _ANNOTATION_ALIASES),
        min_followup_months=min_followup_months,
    )


def tool_pathology_disease_catalog(
    organ_system: str | None = None,
    min_cases: int = 50,
) -> dict:
    result = _client.get_diseases(organ_system=organ_system, min_cases=min_cases)
    return {
        "description": "方信病种目录 (D-01) — Fangxin LIS API",
        "total": result["total_disease_types"],
        "data": result["diseases"],
    }


def tool_pathology_tasks_for_disease(disease_id: str | None = None) -> dict:
    if not disease_id or not str(disease_id).strip():
        return {
            "error": "disease_id is required",
            "description": "病种 AI 任务查询 (D-02) — missing disease_id",
        }
    result = _client.get_tasks(str(disease_id).strip())
    return {
        "description": f"病种 {disease_id} 支持的 AI 任务 (D-02)",
        "disease_id": disease_id,
        "data": result.get("supported_tasks", []),
    }


def tool_feasibility_assess(
    disease_id: str | None = None,
    task_type: str = "survival_prediction",
    required_labels: list[str] | None = None,
    required_molecular_markers: list[str] | None = None,
    required_annotations: list[str] | None = None,
    min_followup_months: int | None = None,
    hypothesis_id: str | None = None,
) -> dict:
    built = _build_hypothesis_request(
        disease_id=disease_id,
        task_type=task_type,
        required_labels=required_labels,
        required_molecular_markers=required_molecular_markers,
        required_annotations=required_annotations,
        min_followup_months=min_followup_months,
        hypothesis_id=hypothesis_id,
    )
    if isinstance(built, dict):
        return built
    result = _client.assess_feasibility(built)
    result["description"] = "研究假说可行性评估 (V-01)"
    result["status"] = _client.feasibility_status(result.get("feasibility_score", 0))
    return result


def tool_data_gap_analysis(
    disease_id: str | None = None,
    task_type: str = "survival_prediction",
    required_labels: list[str] | None = None,
    required_molecular_markers: list[str] | None = None,
    required_annotations: list[str] | None = None,
    min_followup_months: int | None = None,
    hypothesis_id: str | None = None,
) -> dict:
    built = _build_hypothesis_request(
        disease_id=disease_id,
        task_type=task_type,
        required_labels=required_labels,
        required_molecular_markers=required_molecular_markers,
        required_annotations=required_annotations,
        min_followup_months=min_followup_months,
        hypothesis_id=hypothesis_id,
    )
    if isinstance(built, dict):
        return built
    result = _client.gap_analysis(built)
    result["description"] = "数据缺口分析 (V-02)"
    return result


def tool_literature_data_cross_matrix(focus: str | None = None) -> dict:
    combo = tool_method_disease_combo_gap(focus=focus)
    catalog = _client.get_diseases(min_cases=50)
    disease_cases = {
        d["disease_id"]: d["total_cases"]
        for d in catalog["diseases"]
    }
    name_to_id: dict[str, str] = {}
    for d in catalog["diseases"]:
        name_to_id[d["name_en"].lower()] = d["disease_id"]
        name_to_id[d["name_zh"]] = d["disease_id"]

    rows: list[dict] = []
    for gap in combo.get("gaps", [])[:30]:
        disease_name = gap.get("disease", "")
        disease_id = None
        for name, did in name_to_id.items():
            if name.lower() in disease_name.lower() or disease_name.lower() in name.lower():
                disease_id = did
                break
        cohort_size = disease_cases.get(disease_id or "", 0)
        lit_gap = gap.get("gap", "")
        data_support = "high" if cohort_size >= 500 else "medium" if cohort_size >= 200 else "low"

        support = (
            _combo_support_papers(gap.get("method", ""), disease_name)
            if gap.get("paper_cnt", 0) > 0
            else []
        )
        impact = aggregate_paper_impact(support)
        impact_score = impact["impact_score"]
        priority_score = total_priority_score(lit_gap, cohort_size, impact_score)

        rows.append({
            "method": gap.get("method"),
            "disease": disease_name,
            "disease_id": disease_id,
            "literature_gap": lit_gap,
            "literature_paper_cnt": gap.get("paper_cnt", 0),
            "cohort_size": cohort_size,
            "mock_cohort_size": cohort_size,
            "data_support": data_support,
            "avg_cite": impact["avg_cite"],
            "avg_if": impact["avg_if"],
            "impact_score": impact_score,
            "impact_tier": impact["impact_tier"],
            "cross_priority_score": priority_score,
        })

    rows.sort(key=lambda r: r["cross_priority_score"], reverse=True)
    return {
        "description": (
            "Literature gap × Fangxin LIS cohort × citation/IF impact "
            "(cross_priority_score = weighted sum)"
        ),
        "data": rows,
    }


def _require_disease_id(disease_id: str | None, description: str) -> dict | None:
    if not disease_id or not str(disease_id).strip():
        return {"error": "disease_id is required", "description": description}
    return None


def tool_disease_cohort_stats(disease_id: str | None = None) -> dict:
    err = _require_disease_id(disease_id, "V1.1 §7.1/7.2 cohort stats")
    if err:
        return err
    try:
        api = HttpPathologyApi()
        stats = disease_patient_count(api, disease_code=str(disease_id).strip())
        return {"description": "V1.1 disease patient/specimen/slide stats", **stats}
    except PathologyHttpError as exc:
        return {"error": str(exc), "description": "V1.1 cohort stats"}


def tool_subtype_distribution(disease_id: str | None = None) -> dict:
    err = _require_disease_id(disease_id, "V1.1 §7.4 subtype distribution")
    if err:
        return err
    try:
        api = HttpPathologyApi()
        result = subtype_distribution(api, disease_code=str(disease_id).strip())
        return {"description": "V1.1 §7.4 subtype distribution", **result}
    except PathologyHttpError as exc:
        return {"error": str(exc), "description": "V1.1 subtype distribution"}


def tool_attribute_distribution(
    disease_id: str | None = None,
    attribute_keyword: str | None = None,
) -> dict:
    err = _require_disease_id(disease_id, "V1.1 §7.3 attribute distribution")
    if err:
        return err
    try:
        api = HttpPathologyApi()
        result = attribute_distribution(
            api,
            disease_code=str(disease_id).strip(),
            attribute_keyword=attribute_keyword,
        )
        return {"description": "V1.1 §7.3 attribute distribution", **result}
    except PathologyHttpError as exc:
        return {"error": str(exc), "description": "V1.1 attribute distribution"}


def tool_molecular_positivity(
    disease_id: str | None = None,
    biomarker_name: str = "HER2",
) -> dict:
    err = _require_disease_id(disease_id, "V1.1 §7.8 molecular positivity")
    if err:
        return err
    try:
        api = HttpPathologyApi()
        result = molecular_positivity(
            api,
            disease_code=str(disease_id).strip(),
            biomarker_name=biomarker_name or "HER2",
        )
        return {"description": "V1.1 §7.8 molecular/IHC positivity", **result}
    except PathologyHttpError as exc:
        return {"error": str(exc), "description": "V1.1 molecular positivity"}


def tool_text_disease_matches(
    disease_id: str | None = None,
    pending_only: bool = False,
) -> dict:
    try:
        api = HttpPathologyApi()
        result = text_disease_match_summary(
            api,
            disease_code=str(disease_id).strip() if disease_id else None,
            pending_only=pending_only,
        )
        return {"description": "V1.1 §7.5–7.7 text disease matches", **result}
    except PathologyHttpError as exc:
        return {"error": str(exc), "description": "V1.1 text disease matches"}


FEASIBILITY_TOOLS: dict[str, Callable[..., dict]] = {
    "pathology_disease_catalog": tool_pathology_disease_catalog,
    "pathology_tasks_for_disease": tool_pathology_tasks_for_disease,
    "feasibility_assess": tool_feasibility_assess,
    "data_gap_analysis": tool_data_gap_analysis,
    "literature_data_cross_matrix": tool_literature_data_cross_matrix,
    "disease_cohort_stats": tool_disease_cohort_stats,
    "subtype_distribution": tool_subtype_distribution,
    "attribute_distribution": tool_attribute_distribution,
    "molecular_positivity": tool_molecular_positivity,
    "text_disease_matches": tool_text_disease_matches,
}

FEASIBILITY_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "pathology_disease_catalog",
            "description": "Query Fangxin disease catalog (D-01). Returns cohort sizes and data modalities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "organ_system": {
                        "type": "string",
                        "description": "digestive / respiratory / gynecological etc.",
                    },
                    "min_cases": {"type": "integer", "description": "Minimum case threshold"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pathology_tasks_for_disease",
            "description": "Supported AI task types for a disease (D-02).",
            "parameters": {
                "type": "object",
                "properties": {
                    "disease_id": {"type": "string", "description": "e.g. GC-ADC, NSCLC-ADC"},
                },
                "required": ["disease_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "feasibility_assess",
            "description": (
                "Assess hypothesis feasibility against Fangxin LIS data (V-01). "
                "Returns feasibility_score, available_cohort_size, recommendation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "disease_id": {"type": "string"},
                    "task_type": {"type": "string"},
                    "required_labels": {"type": "array", "items": {"type": "string"}},
                    "required_molecular_markers": {"type": "array", "items": {"type": "string"}},
                    "required_annotations": {"type": "array", "items": {"type": "string"}},
                    "min_followup_months": {"type": "integer"},
                    "hypothesis_id": {"type": "string"},
                },
                "required": ["disease_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "data_gap_analysis",
            "description": (
                "When feasibility is marginal, analyze data bottlenecks (V-02) "
                "and return alternative_hypothesis_suggestions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "disease_id": {"type": "string"},
                    "task_type": {"type": "string"},
                    "required_labels": {"type": "array", "items": {"type": "string"}},
                    "required_molecular_markers": {"type": "array", "items": {"type": "string"}},
                    "required_annotations": {"type": "array", "items": {"type": "string"}},
                    "min_followup_months": {"type": "integer"},
                    "hypothesis_id": {"type": "string"},
                },
                "required": ["disease_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "literature_data_cross_matrix",
            "description": (
                "Cross literature method-disease gaps with Fangxin cohort sizes "
                "and citation/IF impact_score. High cross_priority_score = gap + data + impact."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "Optional keyword filter"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disease_cohort_stats",
            "description": "V1.1 §7.1/7.2: patient/specimen/slide counts for a DiseaseCode.",
            "parameters": {
                "type": "object",
                "properties": {"disease_id": {"type": "string"}},
                "required": ["disease_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subtype_distribution",
            "description": "V1.1 §7.4: subtype patient distribution for a disease.",
            "parameters": {
                "type": "object",
                "properties": {"disease_id": {"type": "string"}},
                "required": ["disease_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "attribute_distribution",
            "description": "V1.1 §7.3: attribute/option distribution (stage, grade, severity…).",
            "parameters": {
                "type": "object",
                "properties": {
                    "disease_id": {"type": "string"},
                    "attribute_keyword": {"type": "string"},
                },
                "required": ["disease_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "molecular_positivity",
            "description": "V1.1 §7.8: IHC/molecular positivity rate within a disease cohort.",
            "parameters": {
                "type": "object",
                "properties": {
                    "disease_id": {"type": "string"},
                    "biomarker_name": {"type": "string"},
                },
                "required": ["disease_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "text_disease_matches",
            "description": "V1.1 §7.5–7.7: text disease hit/mapping/pending-review summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "disease_id": {"type": "string"},
                    "pending_only": {"type": "boolean"},
                },
                "required": [],
            },
        },
    },
]


def build_combined_idea_tools() -> tuple[dict[str, Any], list[dict]]:
    """Merge idea KG tools with feasibility tools."""
    from idea_agent import IDEA_TOOLS, IDEA_TOOL_SCHEMAS

    tools = {**IDEA_TOOLS, **FEASIBILITY_TOOLS}
    schemas = IDEA_TOOL_SCHEMAS + FEASIBILITY_TOOL_SCHEMAS
    return tools, schemas


def build_gap_feasibility_tools() -> tuple[dict[str, Any], list[dict]]:
    """Merge gap debate tools with feasibility tools."""
    from analysis.graph_tools import GAP_TOOLS, GAP_TOOL_SCHEMAS

    tools = {**GAP_TOOLS, **FEASIBILITY_TOOLS}
    schemas = GAP_TOOL_SCHEMAS + FEASIBILITY_TOOL_SCHEMAS
    return tools, schemas
