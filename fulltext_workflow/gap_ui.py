"""
gap_ui.py — Streamlit UI for fulltext_workflow Gap Debate + Proposal generation.

Usage (recommended — uses project .venv):
    cd fulltext_workflow
    ..\\.venv\\Scripts\\streamlit.exe run gap_ui.py
    # or:  .\\run_gap_ui.ps1

Plain `streamlit run gap_ui.py` works too if that streamlit belongs to the project venv.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_REPO = _ROOT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ensure_project_venv() -> None:
    """Re-launch via repo .venv when openai is missing (e.g. Anaconda streamlit)."""
    if os.environ.get("GAP_UI_VENV") == "1":
        return
    try:
        import importlib.util
        if importlib.util.find_spec("openai") is not None:
            return
    except Exception:
        pass

    venv_streamlit = _REPO / ".venv" / "Scripts" / "streamlit.exe"
    venv_python = _REPO / ".venv" / "Scripts" / "python.exe"
    if not venv_streamlit.exists():
        return
    try:
        if Path(sys.executable).resolve() == venv_python.resolve():
            return
    except Exception:
        pass

    os.environ["GAP_UI_VENV"] = "1"
    os.execv(
        str(venv_streamlit),
        [str(venv_streamlit), "run", str(_ROOT / "gap_ui.py"), *sys.argv[1:]],
    )


_ensure_project_venv()

import json
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Pathology AI - Research Gap Analysis",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    st.error(
        "Missing dependency: **openai**. Install project requirements and use the project venv:\n\n"
        "```powershell\n"
        "cd fulltext_workflow\n"
        "..\\.venv\\Scripts\\pip.exe install -r ..\\requirements.txt\n"
        "..\\.venv\\Scripts\\streamlit.exe run gap_ui.py\n"
        "```\n\n"
        "Or run: `.\\run_gap_ui.ps1`"
    )
    st.stop()

from gap_agent import stream_gap_debate_agent  # noqa: E402
from idea_agent import stream_idea_agent, IDEA_TOOLS  # noqa: E402
import config  # noqa: E402
from db.schema import db_stats, get_all_landscape, init_db, landscape_count  # noqa: E402
from analysis.feasibility_tools import (  # noqa: E402
    FEASIBILITY_TOOLS,
    tool_attribute_distribution,
    tool_data_gap_analysis,
    tool_disease_cohort_stats,
    tool_feasibility_assess,
    tool_literature_data_cross_matrix,
    tool_molecular_positivity,
    tool_pathology_disease_catalog,
    tool_pathology_tasks_for_disease,
    tool_subtype_distribution,
    tool_text_disease_matches,
)
from feasibility.landscape import bootstrap_landscape  # noqa: E402
from pipeline import assess_gap_feasibility  # noqa: E402
from pipeline_utils import parse_gap_titles  # noqa: E402
from debate_labels import (  # noqa: E402
    DEBATE_FLOW_HELP,
    DEBATE_ROLE_CARDS,
    ROLE_DESCRIPTIONS,
    humanize_debate_report,
    role_display,
)
from analysis.gap_tools import tool_method_disease_combo_gap  # noqa: E402
from utils.tool_result_summary import (  # noqa: E402
    extract_corpus_focus_metrics,
    format_tool_result_summary,
    is_summary_result,
    record_count,
)
from analysis.focus_filter import debate_or_corpus_papers, normalize_focus  # noqa: E402
from utils.tab_state import build_tab_sync_script, normalize_tab_label  # noqa: E402
from viz.gap_viz import (  # noqa: E402
    build_gap_viz_bundle,
    plotly_available,
)

init_db()

ROLE_COLOR = {
    "optimist": "#2ca02c",
    "skeptic": "#d62728",
    "moderator": "#1f77b4",
    "generator": "#9467bd",
    "critic": "#ff7f0e",
}

TOOL_META: dict[str, dict] = {
    "corpus_focus_coverage": {"label": "Focus Corpus Coverage", "category": "Corpus Diagnostics"},
    "author_stated_gaps": {"label": "Author-Stated Gaps", "category": "Full-Text Evidence"},
    "limitation_impact_rank": {"label": "Limitation × Impact", "category": "Impact Weighting"},
    "limitation_temporal_profile": {
        "label": "Limitation Temporal Profile",
        "category": "Temporal Gap",
    },
    "combo_gap_temporal": {"label": "Combo Gap Temporal", "category": "Temporal Gap"},
    "limitation_gap_status": {"label": "Limitation Gap Status", "category": "Temporal Gap"},
    "hotspot_entities": {"label": "Hotspot Entities", "category": "Impact Weighting"},
    "recent_highcite_papers": {"label": "High-Cite Recent Papers", "category": "Impact Weighting"},
    "literature_impact_priority_matrix": {"label": "Lit Impact Matrix", "category": "Impact Weighting"},
    "disease_task_coverage": {"label": "Disease-Task Coverage", "category": "Coverage Gap"},
    "method_disease_combo_gap": {"label": "Method x Disease Combo Gap", "category": "Combination Gap"},
    "metric_evidence_quality": {"label": "Metric Evidence Quality", "category": "Full-Text Evidence"},
    "graph_entity_pagerank": {"label": "Entity PageRank vs Papers", "category": "Graph Analysis"},
    "graph_community_gaps": {"label": "Community Detection Gaps", "category": "Graph Analysis"},
    "graph_disease_method_reach": {"label": "Disease-Method Reachability", "category": "Graph Analysis"},
    "pathology_disease_catalog": {"label": "D-01 Disease Catalog", "category": "Data Feasibility"},
    "pathology_tasks_for_disease": {"label": "D-02 Task Types", "category": "Data Feasibility"},
    "feasibility_assess": {"label": "V-01 Feasibility Assess", "category": "Data Feasibility"},
    "data_gap_analysis": {"label": "V-02 Data Gap Analysis", "category": "Data Feasibility"},
    "literature_data_cross_matrix": {"label": "Lit × Data Matrix", "category": "Data Feasibility"},
    "disease_cohort_stats": {"label": "V1.1 Cohort Stats", "category": "Data Feasibility"},
    "subtype_distribution": {"label": "V1.1 Subtype Dist.", "category": "Data Feasibility"},
    "attribute_distribution": {"label": "V1.1 Attribute Dist.", "category": "Data Feasibility"},
    "molecular_positivity": {"label": "V1.1 Molecular Positivity", "category": "Data Feasibility"},
    "text_disease_matches": {"label": "V1.1 Text Matches", "category": "Data Feasibility"},
    "emerging_gap_opportunities": {"label": "Weekly Hot × Gap", "category": "Weekly Hotspot"},
}

CATEGORY_COLOR = {
    "Corpus Diagnostics": "#009688",
    "Full-Text Evidence": "#795548",
    "Temporal Gap": "#607d8b",
    "Coverage Gap": "#d62728",
    "Combination Gap": "#9467bd",
    "Graph Analysis": "#e377c2",
    "Impact Weighting": "#ff9800",
    "Data Feasibility": "#17a2b8",
    "Weekly Hotspot": "#8bc34a",
}

IDEA_TOOL_META: dict[str, str] = {
    "related_papers": "Related Papers",
    "methods_for_topic": "AI Methods Survey",
    "datasets_for_topic": "Dataset Inventory",
    "metrics_for_topic": "Metrics with Evidence",
    "author_limitations_for_topic": "Author Limitations",
    "modality_coverage_for_topic": "Modality Coverage",
    "recent_papers_for_topic": "Recent Papers",
    "graph_entity_pagerank": "Entity PageRank",
    "graph_community_gaps": "Community Gaps",
    "graph_disease_method_reach": "Disease-Method Reach",
    "pathology_disease_catalog": "D-01 Disease Catalog",
    "pathology_tasks_for_disease": "D-02 Task Types",
    "feasibility_assess": "V-01 Feasibility Assess",
    "data_gap_analysis": "V-02 Data Gap Analysis",
    "literature_data_cross_matrix": "Lit × Data Cross Matrix",
}

FEAS_API_META: dict[str, dict] = {
    "D-01": {
        "name": "Disease catalog",
        "endpoint": f"GET {config.PATHOLOGY_API_BASE_URL}/diseases",
    },
    "D-02": {
        "name": "Task types (inferred from LIS data)",
        "endpoint": "(client-side · landscape cache)",
    },
    "cohort": {
        "name": "Patient / specimen / slide counts",
        "endpoint": "GET …/sample-count-by-hospital + /diseases/patients|slides (V1.1 §7.1–7.2)",
    },
    "subtype": {
        "name": "Subtype distribution",
        "endpoint": "GET …/patients/disease-subtypes (V1.1 §7.4)",
    },
    "attribute": {
        "name": "Attribute distribution",
        "endpoint": "GET …/patients/disease-attributes (V1.1 §7.3)",
    },
    "molecular": {
        "name": "Molecular / IHC positivity",
        "endpoint": "GET …/molecular-results (V1.1 §7.8)",
    },
    "text": {
        "name": "Text disease matches",
        "endpoint": "GET …/text-disease-matches (V1.1 §7.5–7.7)",
    },
    "V-01": {
        "name": "Feasibility assess",
        "endpoint": "(client-side · aggregates LIS GET endpoints)",
    },
    "V-02": {
        "name": "Data gap analysis",
        "endpoint": "(client-side · V-01 + bottleneck rules)",
    },
    "cross": {"name": "Literature × data matrix", "endpoint": "(pipeline tool)"},
}

TASK_TYPE_OPTIONS = [
    "survival_prediction",
    "grade_classification",
    "molecular_subtype_classification",
    "region_segmentation",
]

# Fallback when landscape/API catalog is empty (offline mock tests only)
_MOCK_DISEASE_FALLBACK = ["GC-ADC", "NSCLC-ADC", "CRC-ADC", "HCC", "BRCA-IDC"]
MAIN_TAB_LABELS = [
    "Debate Process",
    "Weekly Hotspot",
    "Visualization",
    "Evidence & Literature",
    "Gap Report",
    "Data Feasibility (Fangxin LIS)",
    "Research Proposal",
]
MAIN_TAB_BY_SLUG = {normalize_tab_label(label): label for label in MAIN_TAB_LABELS}
_DATA_TAB_LABEL = "Data Feasibility (Fangxin LIS)"
_PROPOSAL_TAB_LABEL = "Research Proposal"


@st.cache_data(ttl=120, show_spinner=False)
def load_feasibility_disease_catalog(_landscape_version: int) -> list[dict[str, Any]]:
    """Load disease options from SQLite landscape cache, else live D-01 query."""
    rows = get_all_landscape()
    if rows:
        diseases: list[dict[str, Any]] = []
        for row in rows:
            cat = row.get("payload", {}).get("catalog", {})
            if cat.get("disease_id"):
                diseases.append(cat)
        if diseases:
            diseases.sort(key=lambda d: d.get("total_cases", 0), reverse=True)
            return diseases

    result = tool_pathology_disease_catalog(min_cases=1)
    data = result.get("data") or []
    data.sort(key=lambda d: d.get("total_cases", 0), reverse=True)
    return data


def feasibility_disease_ids(catalog: list[dict[str, Any]]) -> list[str]:
    if catalog:
        return [str(d["disease_id"]) for d in catalog if d.get("disease_id")]
    return list(_MOCK_DISEASE_FALLBACK)


def feasibility_organ_systems(catalog: list[dict[str, Any]]) -> list[str]:
    systems = sorted({d.get("organ_system") or "" for d in catalog if d.get("organ_system")})
    return [""] + systems


def format_disease_option(disease_id: str, catalog: list[dict[str, Any]]) -> str:
    by_id = {str(d.get("disease_id")): d for d in catalog if d.get("disease_id")}
    row = by_id.get(disease_id, {})
    zh = row.get("name_zh") or ""
    cases = row.get("total_cases", 0)
    if zh:
        return f"{disease_id} — {zh} ({cases} cases)"
    return f"{disease_id} ({cases} cases)"


def default_disease_id(catalog: list[dict[str, Any]]) -> str:
    ids = feasibility_disease_ids(catalog)
    return ids[0] if ids else "GC-ADC"


def safe_table(df: pd.DataFrame, height: int | None = None, **_kwargs) -> None:
    if df is None or (hasattr(df, "empty") and df.empty):
        st.caption("(no data)")
        return
    try:
        kw: dict = {"use_container_width": True, "hide_index": True}
        if height:
            kw["height"] = height
        st.dataframe(df, **kw)
    except Exception:
        st.markdown(df.to_html(index=False), unsafe_allow_html=True)


def remember_main_tab(label_or_slug: str) -> None:
    slug = (
        label_or_slug
        if label_or_slug in MAIN_TAB_BY_SLUG
        else normalize_tab_label(label_or_slug)
    )
    if slug not in MAIN_TAB_BY_SLUG:
        return
    st.session_state["active_main_tab"] = slug
    try:
        st.query_params["main_tab"] = slug
    except Exception:
        pass


def remember_main_tab_for(label: str):
    def _remember() -> None:
        remember_main_tab(label)

    return _remember


def get_requested_main_tab() -> str:
    try:
        raw = st.query_params.get("main_tab", "")
    except Exception:
        raw = ""
    slug = str(raw or "").strip().lower()
    if slug in MAIN_TAB_BY_SLUG:
        st.session_state["active_main_tab"] = slug
        return slug
    saved = str(st.session_state.get("active_main_tab", "")).strip().lower()
    if saved in MAIN_TAB_BY_SLUG:
        return saved
    default = normalize_tab_label(MAIN_TAB_LABELS[0])
    st.session_state["active_main_tab"] = default
    return default


def bootstrap_main_tab_state() -> None:
    get_requested_main_tab()


def render_main_tab_sync() -> None:
    slug = get_requested_main_tab()
    try:
        st.query_params["main_tab"] = slug
    except Exception:
        pass
    components.html(
        build_tab_sync_script(MAIN_TAB_LABELS, slug),
        height=0,
        width=0,
    )


def render_feasibility_result(result: dict) -> None:
    """Render V-01 / V-02 API response with metrics."""
    if "error" in result:
        st.error(result["error"])
        return

    desc = result.get("description", "")
    if desc:
        st.caption(desc)

    if "feasibility_score" in result:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Feasibility Score", f"{result.get('feasibility_score', 0):.2f}")
        c2.metric("Cohort Size", result.get("available_cohort_size", "—"))
        c3.metric("Recommendation", result.get("recommendation", "—"))
        c4.metric("Status", result.get("status", "—"))
        if result.get("note"):
            st.info(result["note"])
        breakdown = result.get("breakdown")
        if breakdown:
            with st.expander("Sample breakdown", expanded=True):
                safe_table(pd.DataFrame([breakdown]).T.reset_index().rename(
                    columns={"index": "field", 0: "count"}
                ))

    if result.get("alternative_hypothesis_suggestions"):
        st.markdown("**Alternative suggestions (V-02)**")
        for s in result["alternative_hypothesis_suggestions"]:
            st.markdown(f"- {s}")

    gaps = result.get("gaps")
    if gaps:
        st.markdown("**Data gaps**")
        safe_table(pd.DataFrame(gaps))

    if "data" in result and isinstance(result["data"], list):
        safe_table(pd.DataFrame(result["data"]))
    elif "feasibility_score" not in result and "gaps" not in result:
        st.json(result)


def render_data_feasibility_tab(focus_hint: str = "") -> None:
    """Streamlit tab: Fangxin LIS API / pathology_data_api_spec interfaces."""
    st.subheader("Fangxin Pathology Data APIs (schema V1.1)")
    st.caption(
        f"Live Fangxin LIS via `{config.PATHOLOGY_API_BASE_URL}`. "
        "Aligned with `数据库接口更新V1.1.pdf` query semantics (§7) over existing GET endpoints. "
        "See [api_document.md](../api_document.md)."
    )

    lc = landscape_count()
    disease_catalog = load_feasibility_disease_catalog(lc)
    disease_ids = feasibility_disease_ids(disease_catalog)
    organ_options = feasibility_organ_systems(disease_catalog)

    c0, c1, c2 = st.columns([2, 1, 1])
    with c0:
        st.markdown(
            f"**Phase 0 data landscape** — SQLite `pathology_landscape`: **{lc}** diseases"
        )
        if not disease_catalog:
            st.warning(
                "No cached diseases yet. Click **Bootstrap Landscape** to load from the LIS API."
            )
        else:
            st.caption(
                f"D-01 / V-01 dropdowns use **{len(disease_ids)}** cached diseases "
                f"(top: {format_disease_option(disease_ids[0], disease_catalog)})."
            )
    with c1:
        if st.button(
            "Bootstrap Landscape",
            use_container_width=True,
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            with st.spinner("Fetching diseases + sample stats from LIS API …"):
                res = bootstrap_landscape(force=False)
                load_feasibility_disease_catalog.clear()
                if res.get("skipped"):
                    st.session_state["landscape_msg"] = res.get("reason", "already loaded")
                else:
                    st.session_state["landscape_msg"] = (
                        f"Loaded {res['disease_count']} diseases from API"
                    )
                st.rerun()
    with c2:
        if st.button(
            "Force Reload",
            use_container_width=True,
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            with st.spinner("Force reloading from LIS API …"):
                bootstrap_landscape(force=True)
                load_feasibility_disease_catalog.clear()
                st.session_state["landscape_msg"] = "Force reloaded from API"
                st.rerun()
    if st.session_state.get("landscape_msg"):
        st.success(st.session_state["landscape_msg"])

    if lc > 0:
        with st.expander("Cached landscape snapshot", expanded=False):
            for row in get_all_landscape():
                cat = row["payload"].get("catalog", {})
                v11 = row["payload"].get("v11") or {}
                mol_n = len(v11.get("molecular_positivity") or [])
                st.markdown(
                    f"**{row['disease_id']}** — {cat.get('name_zh', '')} "
                    f"({cat.get('total_cases', 0)} cases) · "
                    f"subtypes={len(v11.get('subtype_distribution') or [])} · "
                    f"attrs={len(v11.get('attribute_distribution') or [])} · "
                    f"markers={mol_n} · updated {row.get('updated_at', '')}"
                )

    st.divider()

    (
        sub_catalog,
        sub_subtype,
        sub_attr,
        sub_mol,
        sub_text,
        sub_v01,
        sub_v02,
        sub_cross,
        sub_gap,
    ) = st.tabs([
        "D-01 / D-02 Catalog",
        "Subtype (§7.4)",
        "Attributes (§7.3)",
        "Molecular (§7.8)",
        "Text Matches (§7.5–7.7)",
        "V-01 Feasibility",
        "V-02 Gap Analysis",
        "Lit × Data Matrix",
        "Quick check from Gap",
    ])

    with sub_catalog:
        st.markdown(f"**{FEAS_API_META['D-01']['name']}** · `{FEAS_API_META['D-01']['endpoint']}`")
        col_a, col_b = st.columns(2)
        with col_a:
            organ = st.selectbox(
                "organ_system (OrganSystem from API)",
                organ_options,
                format_func=lambda x: x or "(all)",
                key="feas_organ",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
        with col_b:
            min_cases = st.number_input(
                "min_cases",
                1,
                5000,
                50,
                step=10,
                key="feas_min_cases",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
        if st.button(
            "Query D-01",
            key="btn_d01",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            d01 = tool_pathology_disease_catalog(
                organ_system=organ or None,
                min_cases=int(min_cases),
            )
            st.session_state["d01_result"] = d01
        if "d01_result" in st.session_state:
            r = st.session_state["d01_result"]
            st.metric("Total disease types", r.get("total", 0))
            render_tool_result("pathology_disease_catalog", r)

        st.divider()
        st.markdown(f"**{FEAS_API_META['D-02']['name']}** · `{FEAS_API_META['D-02']['endpoint']}`")
        d02_id = st.selectbox(
            "disease_id (DiseaseCode)",
            disease_ids,
            format_func=lambda did: format_disease_option(did, disease_catalog),
            key="feas_d02_disease",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        c_d02a, c_d02b = st.columns(2)
        with c_d02a:
            if st.button(
                "Query D-02 tasks",
                key="btn_d02",
                on_click=remember_main_tab_for(_DATA_TAB_LABEL),
            ):
                st.session_state["d02_result"] = tool_pathology_tasks_for_disease(d02_id)
        with c_d02b:
            if st.button(
                "Query cohort stats (§7.1/7.2)",
                key="btn_cohort",
                on_click=remember_main_tab_for(_DATA_TAB_LABEL),
            ):
                st.session_state["cohort_result"] = tool_disease_cohort_stats(d02_id)
        if "d02_result" in st.session_state:
            render_tool_result("pathology_tasks_for_disease", st.session_state["d02_result"])
        if "cohort_result" in st.session_state:
            cr = st.session_state["cohort_result"]
            if "error" in cr:
                st.error(cr["error"])
            else:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Patients", cr.get("patient_count", 0))
                m2.metric("Specimens", cr.get("specimen_count", 0))
                m3.metric("Slides", cr.get("slide_count", 0))
                m4.metric("Hospitals", cr.get("hospital_count", 0))

    with sub_subtype:
        st.markdown(f"**{FEAS_API_META['subtype']['name']}** · `{FEAS_API_META['subtype']['endpoint']}`")
        st_id = st.selectbox(
            "disease_id",
            disease_ids,
            format_func=lambda did: format_disease_option(did, disease_catalog),
            key="subtype_disease",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "Query subtype distribution",
            key="btn_subtype",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            st.session_state["subtype_result"] = tool_subtype_distribution(st_id)
        if "subtype_result" in st.session_state:
            r = st.session_state["subtype_result"]
            if "error" in r:
                st.error(r["error"])
            else:
                st.caption(
                    f"patient_scope={r.get('patient_scope')} · matched_rows={r.get('matched_rows')}"
                )
                dist = r.get("distribution") or []
                if dist:
                    safe_table(pd.DataFrame(dist), height=360)
                else:
                    st.info("No subtype rows for this disease in the current API sample.")

    with sub_attr:
        st.markdown(
            f"**{FEAS_API_META['attribute']['name']}** · `{FEAS_API_META['attribute']['endpoint']}`"
        )
        at_id = st.selectbox(
            "disease_id",
            disease_ids,
            format_func=lambda did: format_disease_option(did, disease_catalog),
            key="attr_disease",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        attr_kw = st.text_input(
            "attribute keyword (optional)",
            value="",
            key="attr_keyword",
            placeholder="分期 / 分级 / severity / Gleason …",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "Query attribute distribution",
            key="btn_attr",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            st.session_state["attr_result"] = tool_attribute_distribution(
                at_id, attribute_keyword=attr_kw or None
            )
        if "attr_result" in st.session_state:
            r = st.session_state["attr_result"]
            if "error" in r:
                st.error(r["error"])
            else:
                st.caption(
                    f"patient_scope={r.get('patient_scope')} · matched_rows={r.get('matched_rows')}"
                )
                dist = r.get("distribution") or []
                if dist:
                    safe_table(pd.DataFrame(dist), height=360)
                else:
                    st.info("No attribute rows matched for this disease / keyword.")

    with sub_mol:
        st.markdown(
            f"**{FEAS_API_META['molecular']['name']}** · `{FEAS_API_META['molecular']['endpoint']}`"
        )
        mol_id = st.selectbox(
            "disease_id",
            disease_ids,
            format_func=lambda did: format_disease_option(did, disease_catalog),
            key="mol_disease",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        biomarker = st.selectbox(
            "biomarker",
            ["HER2", "EGFR", "MSI", "P16", "Ki-67", "PD-L1", "EBER", "P40", "CK"],
            key="mol_biomarker",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "Query positivity",
            type="primary",
            key="btn_mol",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            st.session_state["mol_result"] = tool_molecular_positivity(mol_id, biomarker)
        if "mol_result" in st.session_state:
            r = st.session_state["mol_result"]
            if "error" in r:
                st.error(r["error"])
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Cohort patients", r.get("patient_scope", 0))
                c2.metric("Tested", r.get("tested_patients", 0))
                c3.metric("Positive", r.get("positive_patients", 0))
                c4.metric("Positivity rate", f"{r.get('positivity_rate', 0):.1%}")

    with sub_text:
        st.markdown(f"**{FEAS_API_META['text']['name']}** · `{FEAS_API_META['text']['endpoint']}`")
        st.caption(
            "Uses text_disease_match for NLP/report hit tracing. "
            "Dedicated disease_alias_dict REST is not exposed yet — resolve via matches + disease dict."
        )
        tx_options = ["(all)"] + disease_ids
        tx_id = st.selectbox(
            "disease_id filter",
            tx_options,
            format_func=lambda did: (
                "(all diseases)"
                if did == "(all)"
                else format_disease_option(did, disease_catalog)
            ),
            key="text_disease",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        pending_only = st.checkbox(
            "Pending review only (§7.7)",
            value=False,
            key="text_pending",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "Query text matches",
            key="btn_text",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            st.session_state["text_result"] = tool_text_disease_matches(
                None if tx_id == "(all)" else tx_id,
                pending_only=pending_only,
            )
        if "text_result" in st.session_state:
            r = st.session_state["text_result"]
            if "error" in r:
                st.error(r["error"])
            else:
                st.metric("Total matches", r.get("total_matches", 0))
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("**VerificationStatus**")
                    vs = r.get("verification_status") or {}
                    if vs:
                        safe_table(
                            pd.DataFrame(
                                [{"status": k, "count": v} for k, v in vs.items()]
                            )
                        )
                with col_b:
                    st.markdown("**Top mentions**")
                    mentions = r.get("top_mentions") or []
                    if mentions:
                        safe_table(pd.DataFrame(mentions), height=260)
                sample = r.get("sample") or []
                if sample:
                    with st.expander("Sample rows", expanded=False):
                        safe_table(pd.DataFrame(sample), height=320)

    with sub_v01:
        st.markdown(f"**{FEAS_API_META['V-01']['name']}** · `{FEAS_API_META['V-01']['endpoint']}`")
        st.caption(
            "Aggregates sample counts, patients, attributes and molecular results "
            "from the LIS query API, then computes feasibility_score locally."
        )
        fc1, fc2 = st.columns(2)
        with fc1:
            v01_disease = st.selectbox(
                "disease_id (DiseaseCode)",
                disease_ids,
                format_func=lambda did: format_disease_option(did, disease_catalog),
                key="v01_disease",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
            v01_task = st.selectbox(
                "task_type",
                TASK_TYPE_OPTIONS,
                key="v01_task",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
            v01_followup = st.number_input(
                "min_followup_months",
                0,
                60,
                12,
                key="v01_followup",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
        with fc2:
            v01_labels = st.text_input(
                "required_labels (comma-separated)",
                "overall_survival_months, death_event",
                key="v01_labels",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
            v01_markers = st.text_input(
                "required_molecular_markers",
                "",
                key="v01_markers",
                placeholder="MSI_status, HER2",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
            v01_annotations = st.text_input(
                "required_annotations",
                "",
                key="v01_annotations",
                placeholder="tnm_stage, who_grade",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )

        if st.button(
            "Run V-01 Assess",
            type="primary",
            key="btn_v01",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            labels = [x.strip() for x in v01_labels.split(",") if x.strip()]
            markers = [x.strip() for x in v01_markers.split(",") if x.strip()]
            annotations = [x.strip() for x in v01_annotations.split(",") if x.strip()]
            st.session_state["v01_result"] = tool_feasibility_assess(
                disease_id=v01_disease,
                task_type=v01_task,
                required_labels=labels,
                required_molecular_markers=markers,
                required_annotations=annotations,
                min_followup_months=int(v01_followup) if v01_followup else None,
            )
        if "v01_result" in st.session_state:
            render_feasibility_result(st.session_state["v01_result"])

    with sub_v02:
        st.markdown(f"**{FEAS_API_META['V-02']['name']}** · `{FEAS_API_META['V-02']['endpoint']}`")
        st.caption(
            "Same hypothesis as V-01; highlights data bottlenecks and alternative directions."
        )
        if st.button(
            "Copy from V-01 form & run V-02",
            key="btn_v02_copy",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            labels = [x.strip() for x in st.session_state.get("v01_labels", "").split(",") if x.strip()]
            markers = [x.strip() for x in st.session_state.get("v01_markers", "").split(",") if x.strip()]
            annotations = [x.strip() for x in st.session_state.get("v01_annotations", "").split(",") if x.strip()]
            st.session_state["v02_result"] = tool_data_gap_analysis(
                disease_id=st.session_state.get("v01_disease", default_disease_id(disease_catalog)),
                task_type=st.session_state.get("v01_task", TASK_TYPE_OPTIONS[0]),
                required_labels=labels,
                required_molecular_markers=markers,
                required_annotations=annotations,
                min_followup_months=int(st.session_state.get("v01_followup", 12) or 0) or None,
            )
        if "v02_result" in st.session_state:
            render_feasibility_result(st.session_state["v02_result"])

    with sub_cross:
        st.markdown(f"**{FEAS_API_META['cross']['name']}**")
        cross_focus = st.text_input(
            "Literature focus keyword",
            value=focus_hint,
            key="cross_focus",
            placeholder="e.g. radiomics",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "Build cross matrix",
            key="btn_cross",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            st.session_state["cross_result"] = tool_literature_data_cross_matrix(
                focus=cross_focus or None,
            )
        if "cross_result" in st.session_state:
            r = st.session_state["cross_result"]
            st.caption(r.get("description", ""))
            data = r.get("data", [])
            if data:
                safe_table(pd.DataFrame(data), height=400)
                st.caption(
                    "cross_priority_score = literature gap + LIS cohort + citation/IF impact "
                    "(run enrich-s2 & import-if for full weighting)"
                )
            else:
                st.info("No cross-matrix rows (KG may be empty — run extract first).")

    with sub_gap:
        st.markdown("**Assess a gap from the debate report**")
        report_text = st.session_state.get("report", "")
        parsed_gaps = parse_gap_titles(report_text) if report_text else []
        if parsed_gaps:
            gap_pick = st.selectbox(
                "Select gap from debate report",
                parsed_gaps,
                key="feas_gap_pick",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
            if st.button(
                "Assess selected gap",
                type="primary",
                key="btn_gap_assess",
                on_click=remember_main_tab_for(_DATA_TAB_LABEL),
            ):
                fr = assess_gap_feasibility(gap_pick, report_text)
                st.session_state["gap_feas_result"] = fr
        else:
            manual_gap = st.text_area(
                "Or enter gap title / description",
                height=100,
                key="feas_manual_gap",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
            if st.button(
                "Assess manual gap",
                key="btn_manual_gap",
                on_click=remember_main_tab_for(_DATA_TAB_LABEL),
            ) and manual_gap.strip():
                fr = assess_gap_feasibility(manual_gap.strip(), manual_gap.strip())
                st.session_state["gap_feas_result"] = fr

        fr = st.session_state.get("gap_feas_result")
        if fr:
            st.markdown(f"**{fr.gap_title}**")
            m1, m2, m3 = st.columns(3)
            m1.metric("Mapped disease_id", fr.disease_id or "—")
            m2.metric("Map confidence", f"{fr.map_confidence:.2f}")
            m3.metric("Status", fr.status)
            render_feasibility_result(fr.assessment)
            if fr.evolution_log:
                with st.expander("Evolution log"):
                    st.json(fr.evolution_log)


def render_tool_result(name: str, result: dict) -> None:
    if "error" in result:
        st.error(f"Error: {result['error']}")
        return
    desc = result.get("description", "")
    if desc:
        st.caption(desc)

    if name == "corpus_focus_coverage":
        metrics = extract_corpus_focus_metrics(result)
        if metrics is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Focus papers", metrics["focus_papers"])
            c2.metric("Focus extracted", metrics["focus_extracted"])
            c3.metric("Global papers", metrics["global_papers"])
            ratio = metrics["coverage_ratio"]
            ratio_text = f"{ratio * 100:.2f}%" if isinstance(ratio, (int, float)) else "—"
            c4.metric("Coverage ratio", ratio_text)

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Method entities", metrics["method_entities"])
            c6.metric("Disease entities", metrics["disease_entities"])
            c7.metric("Limitation relations", metrics["limitation_relations"])
            c8.metric(
                "Analysis ready",
                "Yes" if metrics["analysis_ready"] else "No",
            )

            top_diseases = metrics.get("top_diseases") or []
            if top_diseases:
                st.markdown("**Top matched diseases**")
                safe_table(pd.DataFrame(top_diseases), height=min(260, 40 + len(top_diseases) * 35))

            warnings = metrics.get("warnings") or []
            for warning in warnings:
                st.warning(warning)
            return

    if "data" in result and isinstance(result["data"], list) and result["data"]:
        safe_table(pd.DataFrame(result["data"]), height=min(400, 40 + len(result["data"]) * 35))
        return

    if "gaps" in result:
        gaps = result.get("gaps", [])
        if gaps:
            safe_table(pd.DataFrame(gaps))
        else:
            st.info("No combination gaps found.")
        return

    if "results_backed" in result or "all_metrics" in result:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Results-section backed**")
            rb = result.get("results_backed", [])
            safe_table(pd.DataFrame(rb) if rb else pd.DataFrame())
        with c2:
            st.markdown("**All metrics**")
            am = result.get("all_metrics", [])
            safe_table(pd.DataFrame(am) if am else pd.DataFrame())
        return

    st.json(result)


def extract_evidence(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for ev in events:
        if ev.get("type") != "tool_result":
            continue
        result = ev.get("result", {})
        for key in ("data", "results_backed", "all_metrics"):
            for item in result.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                pmid = item.get("source_pmid") or item.get("pmid") or ""
                quote = item.get("evidence_quote") or item.get("quotes") or ""
                title = item.get("title") or item.get("limitation") or item.get("metric") or ""
                uid = f"{pmid}:{quote[:40]}:{title[:40]}"
                if uid in seen:
                    continue
                seen.add(uid)
                if pmid or quote or title:
                    rows.append({
                        "PMID": pmid,
                        "Title/Entity": str(title)[:80],
                        "Evidence Section": item.get("evidence_section") or item.get("sections", ""),
                        "Quote": str(quote)[:120] if quote else "",
                        "Tool": TOOL_META.get(ev.get("name", ""), {}).get("label", ev.get("name", "")),
                    })
    return rows


def extract_papers(events: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for ev in events:
        if ev.get("type") != "tool_result":
            continue
        result = ev.get("result", {})
        for item in result.get("data", []):
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            if not title or title in seen:
                continue
            seen[title] = {
                "Title": title,
                "Year": item.get("year", ""),
                "Journal": item.get("journal_name") or item.get("journal", ""),
                "PMID": item.get("pmid", ""),
                "Study Type": item.get("study_type", ""),
                "Full Text": item.get("full_text_status", ""),
                "Found via": TOOL_META.get(ev.get("name", ""), {}).get("label", ev.get("name", "")),
            }
    return sorted(seen.values(), key=lambda x: str(x.get("Year", "")), reverse=True)


def _format_corpus_paper_rows(rows: list[dict], *, found_via: str) -> list[dict]:
    out: list[dict] = []
    for item in rows:
        title = item.get("title") or ""
        if not title:
            continue
        out.append({
            "Title": title,
            "Year": item.get("year", ""),
            "Journal": item.get("journal_name") or item.get("journal", ""),
            "PMID": item.get("pmid", ""),
            "Study Type": item.get("study_type", ""),
            "Full Text": item.get("full_text_status", ""),
            "Found via": found_via,
        })
    return sorted(out, key=lambda x: str(x.get("Year", "")), reverse=True)


def resolve_evidence_literature_papers(
    events: list[dict],
    focus: str | None,
    *,
    limit: int = 50,
) -> tuple[list[dict], str]:
    """Debate tool titles first; otherwise corpus search for focus (avoids Papers=0)."""
    debate_rows = extract_papers(events)
    if debate_rows:
        return debate_rows[:limit], "debate_tools"
    raw, strategy = debate_or_corpus_papers([], focus, limit=limit)
    if strategy == "debate_tools":
        return debate_rows[:limit], strategy
    label = (
        "Corpus focus match"
        if strategy.startswith("corpus_") and raw
        else strategy
    )
    return _format_corpus_paper_rows(raw, found_via=label), strategy


def compute_stats(events: list[dict]) -> dict:
    calls = sum(1 for e in events if e.get("type") == "tool_call")
    records = 0
    summaries = 0
    for e in events:
        if e.get("type") != "tool_result":
            continue
        tool_name = e.get("name", "")
        r = e.get("result", {})
        records += record_count(r)
        if is_summary_result(tool_name, r):
            summaries += 1
    return {
        "tools_called": calls,
        "records_retrieved": records,
        "summary_results": summaries,
        "papers_found": len(extract_papers(events)),
        "evidence_rows": len(extract_evidence(events)),
    }


def group_call_result_pairs(events: list[dict]) -> list[dict[str, Any]]:
    pairs: dict[str, dict] = {}
    order: list[str] = []
    for ev in events:
        if ev.get("type") not in ("tool_call", "tool_result", "tool_error"):
            continue
        cid = ev.get("call_id") or ev.get("name", "") + str(id(ev))
        if cid not in pairs:
            pairs[cid] = {}
            order.append(cid)
        pairs[cid][ev["type"]] = ev
    return [pairs[cid] for cid in order]


def render_debate_role_guide(*, compact: bool = False) -> None:
    """Show role explanations for end users."""
    if compact:
        st.caption(
            "Flow: **Opportunity Scout** → **Evidence Reviewer** → **Final Synthesizer**"
        )
        return
    st.markdown("#### What do the three roles do?")
    cols = st.columns(3)
    for col, (title, subtitle, task, color) in zip(cols, DEBATE_ROLE_CARDS):
        with col:
            st.markdown(
                f"<div style='border-left:4px solid {color};padding-left:12px;margin-bottom:8px'>"
                f"<strong>{title}</strong><br>"
                f"<span style='color:#666;font-size:0.85rem'>{subtitle}</span><br>"
                f"<span style='font-size:0.9rem'>{task}</span></div>",
                unsafe_allow_html=True,
            )
    with st.expander("Debate flow & confidence score", expanded=False):
        st.markdown(DEBATE_FLOW_HELP)
        for key in ("optimist", "skeptic", "moderator"):
            st.markdown(f"- **{role_display(key)}**：{ROLE_DESCRIPTIONS[key]}")


def role_badge(role: str) -> str:
    color = ROLE_COLOR.get(role, "#6c757d")
    label = role_display(role)
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:0.75rem;">{label}</span>'
    )


def render_gap_visualization_tab(
    events: list[dict],
    *,
    report_text: str = "",
    focus_hint: str = "",
) -> None:
    """MVP charts: debate funnel, method×disease heatmap, lit×data scatter, tool treemap."""
    st.subheader("Gap Discovery Visualizations")
    st.caption(
        "Charts summarize the debate session and tool evidence. "
        "Lower-left on the scatter plot ≈ large literature gap + ample cohort data."
    )

    if not plotly_available():
        st.error(
            "Missing **plotly**. Install with:\n\n"
            "```powershell\n"
            "..\\.venv\\Scripts\\pip.exe install plotly\n"
            "```"
        )
        return

    focus = (focus_hint or "").strip() or None
    use_corpus_preview = st.checkbox(
        "Fill missing charts from live corpus tools",
        value=not events,
        help="When debate did not call combo/cross tools, query the KG directly.",
    )

    def _combo_fetch() -> list[dict]:
        return tool_method_disease_combo_gap(focus=focus).get("gaps", [])

    def _cross_fetch() -> list[dict]:
        return tool_literature_data_cross_matrix(focus=focus).get("data", [])

    bundle = build_gap_viz_bundle(
        events,
        report_text=report_text,
        focus=focus,
        tool_meta=TOOL_META,
        category_colors=CATEGORY_COLOR,
        combo_fetcher=_combo_fetch if use_corpus_preview else None,
        cross_fetcher=_cross_fetch if use_corpus_preview else None,
    )

    stats = bundle["funnel_stats"]
    if events or report_text:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Scout candidates", stats.get("scout_candidates", 0))
        c2.metric("Verified", stats.get("verified", 0))
        c3.metric("Weak evidence", stats.get("weak_evidence", 0))
        c4.metric("False gaps", stats.get("false_gaps", 0))
        c5.metric("Final gaps", stats.get("final_gaps", 0))

    col_l, col_r = st.columns(2)
    with col_l:
        if bundle["funnel_fig"] is not None:
            st.plotly_chart(bundle["funnel_fig"], use_container_width=True)
        elif not events:
            st.info("Run Gap Debate to populate the debate funnel.")
        else:
            st.info("Not enough debate data for funnel chart.")

    with col_r:
        if bundle["treemap_fig"] is not None:
            st.plotly_chart(bundle["treemap_fig"], use_container_width=True)
        else:
            st.info("Tool treemap appears after agents call KG tools.")

    if bundle["combo_fig"] is not None:
        st.plotly_chart(bundle["combo_fig"], use_container_width=True)
    elif use_corpus_preview:
        st.warning("No method × disease combo data (KG may be empty — run extract first).")
    else:
        st.info(
            "Method × disease heatmap needs `method_disease_combo_gap` in the debate, "
            "or enable corpus preview above."
        )

    if bundle["cross_fig"] is not None:
        st.plotly_chart(bundle["cross_fig"], use_container_width=True)
    elif use_corpus_preview:
        st.warning("No literature × data cross rows (bootstrap landscape + extract KG first).")
    else:
        st.info(
            "Lit × data scatter needs `literature_data_cross_matrix` during debate, "
            "or enable corpus preview."
        )


@st.cache_data(ttl=300, show_spinner=False)
def _load_weekly_hotspot_payload(_version: int, window_days: int) -> dict:
    from analysis.weekly_hotspot import (
        compare_with_previous_week,
        compute_emerging_gap_opportunities,
        compute_weekly_hotspots,
    )

    payload = compute_weekly_hotspots(window_days=window_days)
    payload["week_over_week"] = compare_with_previous_week(payload)
    payload["emerging_gap_opportunities"] = compute_emerging_gap_opportunities(
        window_days=window_days,
        payload=payload,
    )
    return payload


def render_weekly_hotspot_tab(focus_hint: str = "") -> None:
    """Weekly ingest hotspots, WoW deltas, gap opportunities, optional LLM brief."""
    from analysis.hotspot_brief import save_hotspot_brief
    from analysis.weekly_hotspot import (
        generate_hotspot_report,
        list_weekly_hotspot_weeks,
        save_hotspot_report,
        week_id,
    )
    from db.schema import weekly_hotspot_stats

    st.subheader("Weekly Research Hotspots")
    st.caption(
        f"Ingest window: **{config.HOTSPOT_WINDOW_DAYS}d** (`papers.created_at`) · "
        "Week-over-week uses persisted snapshots."
    )

    hs = weekly_hotspot_stats()
    weeks = list_weekly_hotspot_weeks()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Snapshot weeks", hs.get("hotspot_runs", 0))
    c2.metric("Snapshot rows", hs.get("hotspot_snapshot_rows", 0))
    c3.metric("Current week", week_id())
    c4.metric("Prior snapshot", weeks[1] if len(weeks) > 1 else "—")

    window_days = st.slider(
        "Window (days)",
        7,
        30,
        config.HOTSPOT_WINDOW_DAYS,
        key="hotspot_window_days",
    )
    payload = _load_weekly_hotspot_payload(len(weeks), window_days)

    m1, m2, m3 = st.columns(3)
    m1.metric("Papers ingested", payload.get("papers_ingested", 0))
    m2.metric("Top method", (payload.get("emerging_methods") or [{}])[0].get("name", "—"))
    m3.metric("Gap opportunities", len(payload.get("emerging_gap_opportunities") or []))

    wow = payload.get("week_over_week") or {}
    if wow.get("has_baseline"):
        st.markdown(f"**Week-over-week** vs `{wow.get('previous_week_id')}`")
        for board, title in [("method", "Methods"), ("disease", "Diseases"), ("combo", "Combos")]:
            b = wow.get("boards", {}).get(board, {})
            new_e = ", ".join(r["label"][:40] for r in b.get("new_entrants", [])[:3]) or "—"
            cooled = ", ".join(r["label"][:40] for r in b.get("cooled", [])[:3]) or "—"
            st.caption(f"{title}: new [{new_e}] · cooled [{cooled}]")
    else:
        st.info(
            f"No prior snapshot ({wow.get('previous_week_id', '?')}). "
            "Run **Save snapshot report** weekly to enable comparison."
        )

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("Refresh hotspots", use_container_width=True):
            _load_weekly_hotspot_payload.clear()
            st.rerun()
    with col_b:
        save_btn = st.button("Save snapshot report", use_container_width=True)
    with col_c:
        brief_btn = st.button("Generate LLM brief", use_container_width=True)

    if save_btn:
        path, saved = save_hotspot_report(persist=True)
        st.success(f"Saved {path} ({saved.get('snapshot_rows', 0)} rows)")
        _load_weekly_hotspot_payload.clear()
        st.rerun()

    if brief_btn:
        with st.spinner(f"Generating brief ({config.LLM_MODEL_AGENT})…"):
            brief_path, brief_text, _ = save_hotspot_brief(persist=True)
        st.session_state["hotspot_brief"] = brief_text
        st.success(f"Brief saved: {brief_path}")

    tab_m, tab_d, tab_c, tab_o, tab_l = st.tabs([
        "Methods",
        "Diseases",
        "Hot Combos",
        "Gap Opportunities",
        "Limitations",
    ])
    with tab_m:
        safe_table(pd.DataFrame(payload.get("emerging_methods", [])))
    with tab_d:
        safe_table(pd.DataFrame(payload.get("heating_diseases", [])))
    with tab_c:
        safe_table(pd.DataFrame(payload.get("hot_combos", [])))
    with tab_o:
        opps = payload.get("emerging_gap_opportunities", [])
        if opps:
            safe_table(pd.DataFrame(opps))
        else:
            st.info("No hot×gap crosses in this window.")
    with tab_l:
        safe_table(pd.DataFrame(payload.get("new_limitations", [])))

    if st.session_state.get("hotspot_brief"):
        st.divider()
        st.markdown("### LLM Brief")
        st.markdown(st.session_state["hotspot_brief"])

    with st.expander("Full markdown report preview", expanded=False):
        st.markdown(generate_hotspot_report(payload, wow=wow))


# Session state
for _k, _v in [
    ("events", []), ("report", ""), ("run_focus", ""), ("run_top_n", 6),
    ("debate_rounds", 0), ("debate_confidence", 0.0),
    ("idea_events", []), ("proposal", ""), ("proposal_gap_text", ""),
    ("proposal_rounds", []), ("final_rounds", 1), ("final_score", 0.0),
    ("landscape_msg", ""),
    ("hotspot_brief", ""),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Sidebar
with st.sidebar:
    st.title("Research Gap Analysis")
    st.caption("Pathomics Full-Text KG")
    st.divider()

    stats = db_stats()
    st.markdown("**Corpus**")
    st.caption(
        f"Papers: {stats['papers']} | Extracted: {stats['extracted']} | "
        f"S2 enriched: {stats.get('s2_enriched', 0)} | IF journals: {stats.get('journals_with_if', 0)} | "
        f"Full-text rels: {stats['relations_fulltext']} | "
        f"Landscape: {landscape_count()} diseases"
    )
    st.divider()

    focus_input = st.text_input(
        "Research focus",
        placeholder="e.g. breast cancer, radiomics, 肠息肉",
        help="Disease/topic focus. Chinese aliases supported (e.g. 肠息肉 → colorectal polyp).",
    )
    _foc_norm = normalize_focus(focus_input)
    if _foc_norm:
        from analysis.disease_synonyms import resolve_disease_concept  # noqa: E402

        _resolved = resolve_disease_concept(_foc_norm)
        if _resolved:
            _fx = (
                f" · Fangxin {_resolved.fangxin_disease_code}"
                if _resolved.fangxin_disease_code
                else ""
            )
            _cui = f" · CUI {_resolved.umls_cui}" if _resolved.umls_cui else ""
            st.caption(f"Resolved: {_resolved.canonical}{_fx}{_cui}")
        elif any("\u4e00" <= ch <= "\u9fff" for ch in _foc_norm):
            st.caption("No synonym mapping — try an English disease name")
    top_n_input = st.slider("Gap recommendations", 3, 10, 6)
    debate_rounds_input = st.slider("Max debate rounds", 1, 3, 2)
    proposal_rounds_input = st.slider(
        "Max Generator x Critic rounds (Proposal tab)",
        1, 5, 2,
    )
    verbose_input = st.checkbox("Show LLM reasoning traces")
    use_ops_memory_input = st.checkbox(
        "Use ops memory",
        value=True,
        help="Inject the last 4 reported gaps for this focus to soft-avoid similar directions",
    )
    persist_ops_memory_input = st.checkbox(
        "Persist this run",
        value=True,
        help="Write ops_runs and gap items after a successful debate or proposal",
    )
    with st.expander("Ops memory for this focus", expanded=False):
        from analysis.ops_memory import load_recent_gaps  # noqa: E402

        mem = load_recent_gaps(focus_input or None)
        if not mem.items:
            st.caption("No memory yet")
        else:
            for it in mem.items[:40]:
                st.markdown(f"- `{it.week_id}` {it.title}")
    st.divider()
    run_button = st.button("Run Gap Debate", type="primary", use_container_width=True)

    if st.session_state["events"]:
        s = compute_stats(st.session_state["events"])
        st.divider()
        st.markdown("**Session stats**")
        for label, val in [
            ("Tools called", s["tools_called"]),
            ("Records", s["records_retrieved"]),
            ("Summary results", s["summary_results"]),
            ("Evidence rows", s["evidence_rows"]),
        ]:
            st.metric(label, val)

st.title("Pathology AI - Research Gap Analysis")
focus_label = f"Focus: *{focus_input}*" if focus_input else "Full corpus"
st.caption(
    f"Opportunity Scout × Evidence Reviewer × Final Synthesizer  |  "
    f"Full-text KG  |  {focus_label}"
)
render_debate_role_guide(compact=True)
st.divider()

if run_button:
    st.session_state.update({
        "events": [], "report": "", "run_focus": focus_input or "All",
        "run_top_n": top_n_input, "debate_confidence": 0.0,
    })
    live_events: list[dict] = []
    tool_step = 0
    current_role = ""

    with st.status(
        "Running debate: Opportunity Scout → Evidence Reviewer → Final Synthesizer …",
        expanded=True,
    ) as sw:
        for event in stream_gap_debate_agent(
            focus=focus_input or None,
            top_n=top_n_input,
            max_debate_rounds=debate_rounds_input,
            use_ops_memory=use_ops_memory_input,
        ):
            live_events.append(event)
            st.session_state["events"] = list(live_events)
            etype = event.get("type", "")

            if etype == "debate_round_start":
                st.markdown(f"**Debate Round {event['round']} / {event['max_rounds']}**")
            elif etype == "phase_start":
                current_role = event.get("role", "")
                st.markdown(
                    f"{role_badge(current_role)} phase started",
                    unsafe_allow_html=True,
                )
            elif etype == "llm_request_start":
                st.caption(
                    f"Waiting for {role_display(event.get('role', ''))} LLM "
                    f"({event.get('iteration', '?')}/{event.get('max_iters', '?')}) …"
                )
            elif etype == "tool_call":
                tool_step += 1
                role = event.get("role", "")
                role_lbl = role_display(role)
                meta = TOOL_META.get(event["name"], {"label": event["name"]})
                args = event.get("args") or {}
                st.write(
                    f"  Step {tool_step} [{role_lbl}] {meta.get('label', event['name'])} "
                    f"· `{args}`"
                )
            elif etype == "tool_running":
                meta = TOOL_META.get(event["name"], {"label": event["name"]})
                st.caption(f"    … running {meta.get('label', event['name'])}")
            elif etype == "tool_result":
                r = event.get("result", {})
                summary = format_tool_result_summary(event.get("name", ""), r)
                st.write(f"    → {summary}")
            elif etype == "tool_error":
                st.warning(f"[{event.get('role')}] {event['name']}: {event.get('error')}")
            elif etype == "optimist_proposal":
                st.success(
                    f"Opportunity Scout candidates (round {event['round']}): "
                    f"{len(event['content'])} chars"
                )
            elif etype == "skeptic_review":
                st.info(
                    f"Evidence Reviewer confidence: {event['confidence']:.1f}/10  "
                    f"(verified={event['verified_count']}, false={event['false_count']})"
                )
            elif etype == "debate_feedback":
                st.warning(
                    f"Final Synthesizer revision request: "
                    f"{event.get('revision_priority', '')[:120]}"
                )
            elif etype == "thinking" and verbose_input:
                with st.expander(
                    f"Reasoning [{role_display(event.get('role', '?'))}]",
                    expanded=False,
                ):
                    st.markdown(event.get("content", ""))
            elif etype == "final":
                st.session_state["report"] = event.get("content", "")
                st.session_state["debate_rounds"] = event.get("rounds", 1)
                st.session_state["debate_confidence"] = event.get("confidence", 0.0)
                if persist_ops_memory_input and event.get("content"):
                    from analysis.ops_memory import persist_debate_report  # noqa: E402

                    rid = persist_debate_report(
                        event["content"],
                        focus=focus_input or None,
                        source="gap_ui",
                        enabled=True,
                    )
                    if rid:
                        st.session_state["ops_run_id"] = rid
                sw.update(
                    label=(
                        f"Debate complete — {tool_step} tool calls, "
                        f"reviewer confidence {event.get('confidence', 0):.1f}/10"
                    ),
                    state="complete",
                    expanded=False,
                )
            elif etype == "error":
                st.error(event.get("content"))
                sw.update(label="Debate failed", state="error")

st.divider()

bootstrap_main_tab_state()

tab_debate, tab_hotspot, tab_viz, tab_evidence, tab_report, tab_data, tab_proposal = st.tabs(
    MAIN_TAB_LABELS
)
render_main_tab_sync()

if not st.session_state["events"]:
    with tab_debate:
        st.info(
            "Set a focus in the sidebar and click **Run Gap Debate**. "
            "The system runs **Opportunity Scout** → **Evidence Reviewer** → **Final Synthesizer**."
        )
        render_debate_role_guide()
    with tab_hotspot:
        render_weekly_hotspot_tab(focus_hint=focus_input)
    with tab_viz:
        render_gap_visualization_tab([], focus_hint=focus_input)
    with tab_evidence:
        foc = normalize_focus(focus_input)
        if foc:
            papers, strategy = resolve_evidence_literature_papers([], foc, limit=50)
            st.subheader(f"Papers ({len(papers)})")
            if papers:
                st.caption(
                    f"Matched via {strategy} for focus «{foc}» "
                    "(run Gap Debate to also collect evidence quotes)."
                )
                safe_table(pd.DataFrame(papers))
            else:
                st.info(f"No corpus papers matched focus «{foc}».")
        else:
            st.info("Run Gap Debate to populate evidence and literature, or set a Research focus.")
    with tab_report:
        st.info("Run Gap Debate to generate the gap report.")
        s = db_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Papers", s["papers"])
        c2.metric("Extracted", s["extracted"])
        c3.metric("Full-text available", s["fulltext_available"])
        c4.metric("KG + Feasibility tools", len(IDEA_TOOLS))
    with tab_data:
        render_data_feasibility_tab(focus_hint=focus_input)
    with tab_proposal:
        st.info("Complete Gap Debate first, or use **Data Feasibility** tab to test APIs.")

elif st.session_state["events"]:
    with tab_debate:
        st.subheader("Debate Trace")
        render_debate_role_guide(compact=True)
        st.divider()
        pairs = group_call_result_pairs(st.session_state["events"])
        debate_cards = [
            e for e in st.session_state["events"]
            if e.get("type") in ("optimist_proposal", "skeptic_review", "debate_feedback")
        ]
        for card in debate_cards:
            ct = card["type"]
            if ct == "optimist_proposal":
                with st.expander(
                    f"Opportunity Scout — Round {card['round']} candidates",
                    expanded=False,
                ):
                    st.markdown(card.get("content", "")[:4000])
            elif ct == "skeptic_review":
                with st.expander(
                    f"Evidence Reviewer — Round {card['round']} "
                    f"(confidence {card.get('confidence', 0):.1f}/10)",
                    expanded=False,
                ):
                    st.markdown(card.get("content", "")[:4000])
            elif ct == "debate_feedback":
                st.warning(
                    f"Round {card['round']} · Final Synthesizer revision: "
                    f"{card.get('revision_priority', '')}"
                )

        st.divider()
        for i, pair in enumerate(pairs, 1):
            call = pair.get("tool_call", {})
            res = pair.get("tool_result")
            err = pair.get("tool_error")
            name = call.get("name", "?")
            role = call.get("role", "")
            meta = TOOL_META.get(name, {"label": name, "category": "Other"})
            feas_lbl = IDEA_TOOL_META.get(name)
            label = feas_lbl or meta.get("label", name)
            role_lbl = role_display(role)
            with st.expander(f"Step {i}: [{role_lbl}] {label}", expanded=False):
                st.markdown(role_badge(role), unsafe_allow_html=True)
                if err:
                    st.error(err.get("error"))
                elif res:
                    rdict = res.get("result", {})
                    if name in FEASIBILITY_TOOLS:
                        render_feasibility_result(rdict)
                    else:
                        render_tool_result(name, rdict)

    with tab_hotspot:
        render_weekly_hotspot_tab(
            focus_hint=st.session_state.get("run_focus") or focus_input,
        )

    with tab_viz:
        render_gap_visualization_tab(
            st.session_state["events"],
            report_text=st.session_state.get("report", ""),
            focus_hint=st.session_state.get("run_focus") or focus_input,
        )

    with tab_evidence:
        evidence = extract_evidence(st.session_state["events"])
        focus_lit = (
            normalize_focus(st.session_state.get("run_focus"))
            or normalize_focus(focus_input)
        )
        papers, lit_strategy = resolve_evidence_literature_papers(
            st.session_state["events"],
            focus_lit,
            limit=50,
        )
        st.subheader(f"Full-Text Evidence ({len(evidence)} rows)")
        if evidence:
            safe_table(pd.DataFrame(evidence))
        else:
            st.info("No evidence quotes extracted yet.")
        st.divider()
        st.subheader(f"Papers ({len(papers)})")
        if papers:
            if lit_strategy.startswith("corpus_"):
                st.caption(
                    f"Debate tools returned no paper titles; showing corpus matches "
                    f"for focus «{focus_lit}» ({lit_strategy})."
                )
            safe_table(pd.DataFrame(papers))
        else:
            st.info("No paper metadata in tool results or corpus focus match.")

    with tab_report:
        report_text = st.session_state.get("report", "")
        if not report_text:
            st.info("Run Gap Debate to generate the report.")
        else:
            display_report = humanize_debate_report(report_text)
            s = compute_stats(st.session_state["events"])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Focus", st.session_state.get("run_focus", "All"))
            c2.metric("Debate rounds", st.session_state.get("debate_rounds", 1))
            c3.metric("Reviewer confidence", f"{st.session_state.get('debate_confidence', 0):.1f}/10")
            c4.metric("Tool calls", s["tools_called"])
            st.caption(
                "Report produced by **Final Synthesizer**. Plain labels "
                "(Opportunity Scout / Evidence Reviewer / Final Synthesizer) replace "
                "Optimist / Skeptic / Moderator in the text below."
            )
            st.divider()
            st.markdown(display_report)
            header = (
                f"# Pathomics/Radiomics Gap Report\n\n"
                f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"> Focus: {st.session_state.get('run_focus')}\n"
                f"> Flow: Opportunity Scout → Evidence Reviewer → Final Synthesizer\n\n---\n\n"
            )
            st.download_button(
                "Download report (Markdown)",
                data=(header + display_report).encode("utf-8"),
                file_name=f"gap_debate_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
            )

    with tab_data:
        render_data_feasibility_tab(
            focus_hint=st.session_state.get("run_focus") or focus_input,
        )

    with tab_proposal:
        st.subheader("Research Proposal Generator")
        report_for_parse = st.session_state.get("report", "")
        parsed = parse_gap_titles(report_for_parse) if report_for_parse else []

        gap_source = st.radio(
            "Gap source",
            ["Select from report", "Enter manually"],
            horizontal=True,
            label_visibility="collapsed",
            key="gap_source",
            on_change=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
        )
        if gap_source == "Select from report":
            gap_input = (
                st.selectbox(
                    "Select gap",
                    parsed,
                    key="gap_sel",
                    on_change=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
                )
                if parsed
                else ""
            )
            if not parsed:
                st.info("Run Gap Debate first to populate gap titles.")
        else:
            gap_input = st.text_area(
                "Custom gap",
                height=120,
                key="gap_manual",
                on_change=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
            )

        gen_btn = st.button(
            "Generate Research Proposal",
            type="primary",
            disabled=not (gap_input and str(gap_input).strip()),
            on_click=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
        )

        if gen_btn and gap_input:
            st.session_state.update({
                "idea_events": [], "proposal": "",
                "proposal_gap_text": str(gap_input).strip(),
                "proposal_rounds": [],
            })
            idea_events: list[dict] = []
            with st.status("Generator x Critic loop …", expanded=True) as psw:
                for event in stream_idea_agent(
                    gap_text=str(gap_input).strip(),
                    max_rounds=proposal_rounds_input,
                ):
                    idea_events.append(event)
                    st.session_state["idea_events"] = list(idea_events)
                    et = event.get("type")
                    if et == "round_start":
                        st.markdown(f"#### Round {event['round']} / {event['max_rounds']}")
                    elif et == "tool_call":
                        role = event.get("role", "")
                        lbl = IDEA_TOOL_META.get(event["name"], event["name"])
                        st.write(f"  [{role}] {lbl} · `{event.get('args', {})}`")
                    elif et == "finalizing_draft":
                        st.caption(event.get("message", "Generating full proposal…"))
                    elif et == "draft":
                        st.success(f"Draft v{event['round']} — {len(event['content'])} chars")
                        rl = st.session_state.get("proposal_rounds", [])
                        rl.append({"round": event["round"], "draft": event["content"], "feedback": None})
                        st.session_state["proposal_rounds"] = rl
                    elif et == "feedback":
                        st.markdown(f"Critic: **{event['score']:.1f}/10** accept={event['accept']}")
                        rl = st.session_state.get("proposal_rounds", [])
                        if rl and rl[-1]["round"] == event["round"]:
                            rl[-1]["feedback"] = event
                            st.session_state["proposal_rounds"] = rl
                    elif et == "final":
                        st.session_state["proposal"] = event.get("content", "")
                        st.session_state["final_rounds"] = event.get("rounds", 1)
                        st.session_state["final_score"] = event.get("final_score", 0.0)
                        feas_score = event.get("feasibility_score")
                        st.session_state["proposal_feasibility_score"] = feas_score
                        if persist_ops_memory_input and event.get("content"):
                            from analysis.ops_memory import (  # noqa: E402
                                create_ops_run,
                                finalize_ops_run,
                                persist_proposal,
                            )

                            rid = st.session_state.get("ops_run_id")
                            if not rid:
                                rid = create_ops_run(focus_input or None, "gap_ui")
                                finalize_ops_run(rid)
                                st.session_state["ops_run_id"] = rid
                            gap_title = (
                                st.session_state.get("proposal_gap_text")
                                or str(gap_input).strip()
                            )
                            persist_proposal(
                                rid,
                                gap_title=gap_title,
                                proposal_md=event.get("content", ""),
                                feasibility_score=(
                                    float(feas_score)
                                    if feas_score is not None
                                    else None
                                ),
                                critic_score=(
                                    float(event.get("final_score"))
                                    if event.get("final_score") is not None
                                    else None
                                ),
                                status="generated",
                            )
                        psw.update(
                            label=f"Done — {event.get('rounds', 1)} rounds, score {event.get('final_score', 0):.1f}/10",
                            state="complete",
                            expanded=False,
                        )

        proposal = st.session_state.get("proposal", "")
        if proposal:
            st.divider()
            p1, p2, p3 = st.columns(3)
            p1.metric("Final score", f"{st.session_state.get('final_score', 0):.1f}/10")
            p2.metric("Rounds", st.session_state.get("final_rounds", 1))
            _pfs = st.session_state.get("proposal_feasibility_score")
            p3.metric(
                "Feasibility",
                f"{float(_pfs):.2f}" if _pfs is not None else "n/a",
            )
            if len(proposal.strip()) < 400 or not any(
                m in proposal
                for m in (
                    "## 1.",
                    "## 1 ",
                    "## Background",
                    "REVISION_NOTE",
                    "Fangxin Data Integration",
                    "## 一",
                    "研究背景",
                )
            ):
                st.warning(
                    "Proposal looks incomplete. Re-run generation or check API / tool errors in the status log."
                )
            st.markdown("### Final Proposal")
            st.markdown(proposal)
            st.download_button(
                "Download proposal (Markdown)",
                data=proposal.encode("utf-8"),
                file_name=f"proposal_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
            )
