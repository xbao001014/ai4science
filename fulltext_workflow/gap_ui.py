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
    page_title="病理 AI · 研究空白分析",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    st.error(
        "缺少依赖：**openai**。请安装项目依赖并使用项目虚拟环境：\n\n"
        "```powershell\n"
        "cd fulltext_workflow\n"
        "..\\.venv\\Scripts\\pip.exe install -r ..\\requirements.txt\n"
        "..\\.venv\\Scripts\\streamlit.exe run gap_ui.py\n"
        "```\n\n"
        "或运行：`.\\run_gap_ui.ps1`"
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
    tool_public_dataset_assess,
    tool_subtype_distribution,
    tool_text_disease_matches,
)
from feasibility.disease_mapper import map_gap_to_disease  # noqa: E402
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
from utils.proposal_difficulty_ui import (  # noqa: E402
    difficulty_display_target,
    support_pmids_from_evidence,
)
from analysis.focus_filter import debate_or_corpus_papers, normalize_focus  # noqa: E402
from utils.tab_state import build_tab_sync_script, normalize_tab_label  # noqa: E402
from viz.gap_opportunity import assemble_opportunity_view  # noqa: E402
from viz.gap_viz import (  # noqa: E402
    build_gap_viz_bundle,
    build_molecular_bar,
    build_subtype_bar,
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
    "corpus_focus_coverage": {"label": "焦点语料覆盖", "category": "语料诊断"},
    "author_stated_gaps": {"label": "作者自述空白", "category": "全文证据"},
    "limitation_impact_rank": {"label": "局限 × 影响", "category": "影响加权"},
    "limitation_temporal_profile": {
        "label": "局限时序画像",
        "category": "时序空白",
    },
    "combo_gap_temporal": {"label": "组合空白时序", "category": "时序空白"},
    "limitation_gap_status": {"label": "局限空白状态", "category": "时序空白"},
    "hotspot_entities": {"label": "热点实体", "category": "影响加权"},
    "recent_highcite_papers": {"label": "高引近期论文", "category": "影响加权"},
    "literature_impact_priority_matrix": {"label": "文献影响矩阵", "category": "影响加权"},
    "disease_task_coverage": {"label": "疾病-任务覆盖", "category": "覆盖空白"},
    "method_disease_combo_gap": {"label": "方法×疾病组合空白", "category": "组合空白"},
    "metric_evidence_quality": {"label": "指标证据质量", "category": "全文证据"},
    "graph_entity_pagerank": {"label": "实体 PageRank vs 论文", "category": "图分析"},
    "graph_community_gaps": {"label": "社区检测空白", "category": "图分析"},
    "graph_disease_method_reach": {"label": "疾病-方法可达性", "category": "图分析"},
    "pathology_disease_catalog": {"label": "D-01 疾病目录", "category": "数据可行性"},
    "pathology_tasks_for_disease": {"label": "D-02 任务类型", "category": "数据可行性"},
    "feasibility_assess": {"label": "V-01 可行性评估", "category": "数据可行性"},
    "public_dataset_assess": {"label": "V-03 公开数据集", "category": "数据可行性"},
    "data_gap_analysis": {"label": "V-02 数据空白分析", "category": "数据可行性"},
    "literature_data_cross_matrix": {"label": "文献×数据矩阵", "category": "数据可行性"},
    "disease_cohort_stats": {"label": "V1.1 队列统计", "category": "数据可行性"},
    "subtype_distribution": {"label": "V1.1 亚型分布", "category": "数据可行性"},
    "attribute_distribution": {"label": "V1.1 属性分布", "category": "数据可行性"},
    "molecular_positivity": {"label": "V1.1 分子阳性率", "category": "数据可行性"},
    "text_disease_matches": {"label": "V1.1 文本匹配", "category": "数据可行性"},
    "emerging_gap_opportunities": {"label": "每周热点×空白", "category": "每周热点"},
}

CATEGORY_COLOR = {
    "语料诊断": "#009688",
    "全文证据": "#795548",
    "时序空白": "#607d8b",
    "覆盖空白": "#d62728",
    "组合空白": "#9467bd",
    "图分析": "#e377c2",
    "影响加权": "#ff9800",
    "数据可行性": "#17a2b8",
    "每周热点": "#8bc34a",
}

IDEA_TOOL_META: dict[str, str] = {
    "related_papers": "相关论文",
    "methods_for_topic": "AI 方法概览",
    "datasets_for_topic": "数据集清单",
    "metrics_for_topic": "带证据的指标",
    "author_limitations_for_topic": "作者局限",
    "modality_coverage_for_topic": "模态覆盖",
    "recent_papers_for_topic": "近期论文",
    "graph_entity_pagerank": "实体 PageRank",
    "graph_community_gaps": "社区空白",
    "graph_disease_method_reach": "疾病-方法可达",
    "pathology_disease_catalog": "D-01 疾病目录",
    "pathology_tasks_for_disease": "D-02 任务类型",
    "feasibility_assess": "V-01 可行性评估",
    "public_dataset_assess": "V-03 公开数据集",
    "data_gap_analysis": "V-02 数据空白分析",
    "literature_data_cross_matrix": "文献×数据交叉矩阵",
}

FEAS_API_META: dict[str, dict] = {
    "D-01": {
        "name": "疾病目录",
        "endpoint": f"GET {config.PATHOLOGY_API_BASE_URL}/diseases",
    },
    "D-02": {
        "name": "任务类型（由 LIS 数据推断）",
        "endpoint": "(client-side · 疾病分布图谱缓存)",
    },
    "cohort": {
        "name": "患者 / 标本 / 切片计数",
        "endpoint": "GET …/sample-count-by-hospital + /diseases/patients|slides (V1.1 §7.1–7.2)",
    },
    "subtype": {
        "name": "亚型分布",
        "endpoint": "GET …/patients/disease-subtypes (V1.1 §7.4)",
    },
    "attribute": {
        "name": "属性分布",
        "endpoint": "GET …/patients/disease-attributes (V1.1 §7.3)",
    },
    "molecular": {
        "name": "分子 / IHC 阳性率",
        "endpoint": "GET …/molecular-results (V1.1 §7.8)",
    },
    "text": {
        "name": "文本疾病匹配",
        "endpoint": "GET …/text-disease-matches (V1.1 §7.5–7.7)",
    },
    "V-01": {
        "name": "可行性评估",
        "endpoint": "(client-side · aggregates LIS GET endpoints)",
    },
    "V-02": {
        "name": "数据空白分析",
        "endpoint": "(client-side · V-01 + bottleneck rules)",
    },
    "V-03": {
        "name": "公开数据集可行性",
        "endpoint": "(client-side · KG USES_DATASET + access_class)",
    },
    "cross": {"name": "文献×数据矩阵", "endpoint": "(pipeline tool)"},
}

TASK_TYPE_OPTIONS = [
    "survival_prediction",
    "grade_classification",
    "molecular_subtype_classification",
    "region_segmentation",
]

# Fallback when landscape/API catalog is empty (offline mock tests only)
_MOCK_DISEASE_FALLBACK = ["GC-ADC", "NSCLC-ADC", "CRC-ADC", "HCC", "BRCA-IDC"]
MAIN_TAB_ENTRIES: list[tuple[str, str]] = [
    ("debate-process", "辩论过程"),
    ("weekly-hotspot", "每周热点"),
    ("visualization", "可视化"),
    ("evidence-literature", "证据与文献"),
    ("gap-report", "研究空白报告"),
    ("data-feasibility-fangxin-lis", "数据可行性（方信 LIS）"),
    ("research-proposal", "研究提案"),
]
MAIN_TAB_LABELS = [label for _, label in MAIN_TAB_ENTRIES]
MAIN_TAB_BY_SLUG = {slug: label for slug, label in MAIN_TAB_ENTRIES}
MAIN_TAB_SLUG_BY_LABEL = {label: slug for slug, label in MAIN_TAB_ENTRIES}
_DATA_TAB_LABEL = MAIN_TAB_BY_SLUG["data-feasibility-fangxin-lis"]
_PROPOSAL_TAB_LABEL = MAIN_TAB_BY_SLUG["research-proposal"]
_DIFFICULTY_LABELS = {"easy": "简单", "moderate": "中等", "hard": "困难"}


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
        return f"{disease_id} — {zh}（{cases} 例）"
    return f"{disease_id}（{cases} 例）"


def default_disease_id(catalog: list[dict[str, Any]]) -> str:
    ids = feasibility_disease_ids(catalog)
    return ids[0] if ids else "GC-ADC"


def safe_table(df: pd.DataFrame, height: int | None = None, **_kwargs) -> None:
    if df is None or (hasattr(df, "empty") and df.empty):
        st.caption("（无数据）")
        return
    try:
        kw: dict = {"use_container_width": True, "hide_index": True}
        if height:
            kw["height"] = height
        st.dataframe(df, **kw)
    except Exception:
        st.markdown(df.to_html(index=False), unsafe_allow_html=True)


def remember_main_tab(label_or_slug: str) -> None:
    if label_or_slug in MAIN_TAB_BY_SLUG:
        slug = label_or_slug
    elif label_or_slug in MAIN_TAB_SLUG_BY_LABEL:
        slug = MAIN_TAB_SLUG_BY_LABEL[label_or_slug]
    else:
        slug = normalize_tab_label(label_or_slug)
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
    default = MAIN_TAB_ENTRIES[0][0]
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
        build_tab_sync_script(
            MAIN_TAB_LABELS,
            slug,
            slug_by_label=MAIN_TAB_SLUG_BY_LABEL,
        ),
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
        c1.metric("可行性得分", f"{result.get('feasibility_score', 0):.2f}")
        c2.metric("队列规模", result.get("available_cohort_size", "—"))
        c3.metric("建议", result.get("recommendation", "—"))
        c4.metric("状态", result.get("status", "—"))
        if result.get("note"):
            st.info(result["note"])
        breakdown = result.get("breakdown")
        if breakdown:
            with st.expander("样本分解", expanded=True):
                safe_table(pd.DataFrame([breakdown]).T.reset_index().rename(
                    columns={"index": "field", 0: "count"}
                ))

    if result.get("alternative_hypothesis_suggestions"):
        st.markdown("**替代建议（V-02）**")
        for s in result["alternative_hypothesis_suggestions"]:
            st.markdown(f"- {s}")

    gaps = result.get("gaps")
    if gaps:
        st.markdown("**数据空白**")
        safe_table(pd.DataFrame(gaps))

    if "data" in result and isinstance(result["data"], list):
        safe_table(pd.DataFrame(result["data"]))
    elif "feasibility_score" not in result and "gaps" not in result:
        st.json(result)


def render_public_dataset_result(result: dict) -> None:
    """Render V-03 public-dataset feasibility report."""
    if "error" in result:
        st.error(result["error"])
        return
    desc = result.get("description", "")
    if desc:
        st.caption(desc)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("公开覆盖分", f"{float(result.get('public_coverage_score') or 0):.2f}")
    c2.metric("状态", result.get("status", "—"))
    c3.metric("主题论文数", result.get("topic_paper_cnt", "—"))
    c4.metric("匹配策略", result.get("match_strategy", "—"))
    rec = result.get("recommended_public") or []
    if rec:
        st.markdown("**推荐公开数据集**")
        safe_table(pd.DataFrame(rec))
    other = result.get("other_datasets") or []
    if other:
        with st.expander("其他数据集（private / unknown）", expanded=False):
            safe_table(pd.DataFrame(other))
    gaps = result.get("gaps") or []
    if gaps:
        st.markdown("**缺口**")
        for g in gaps:
            st.markdown(f"- {g}")
    roles = result.get("roles_for_proposal") or []
    if roles:
        st.caption("提案用途建议: " + ", ".join(str(r) for r in roles))


def render_data_feasibility_tab(focus_hint: str = "") -> None:
    """Streamlit tab: Fangxin LIS API / pathology_data_api_spec interfaces."""
    st.subheader("方信病理数据 API（schema V1.1）")
    st.caption(
        f"通过 `{config.PATHOLOGY_API_BASE_URL}` 访问方信 LIS。 "
        "对齐 `数据库接口更新V1.1.pdf` 查询语义（§7），基于现有 GET 接口。 "
        "参见 [api_document.md](../api_document.md)。"
    )

    lc = landscape_count()
    disease_catalog = load_feasibility_disease_catalog(lc)
    disease_ids = feasibility_disease_ids(disease_catalog)
    organ_options = feasibility_organ_systems(disease_catalog)

    c0, c1, c2 = st.columns([2, 1, 1])
    with c0:
        st.markdown(
            f"**阶段 0 疾病分布图谱** — SQLite `pathology_landscape`：**{lc}** 种疾病"
        )
        if not disease_catalog:
            st.warning(
                "尚无缓存疾病。请点击 **初始化疾病分布图谱** 从 LIS API 加载。"
            )
        else:
            st.caption(
                f"D-01 / V-01 下拉使用 **{len(disease_ids)}** 种缓存疾病 "
                f"（示例：{format_disease_option(disease_ids[0], disease_catalog)}）。"
            )
    with c1:
        if st.button(
            "初始化疾病分布图谱",
            use_container_width=True,
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            with st.spinner("正在从 LIS API 拉取疾病与样本统计 …"):
                res = bootstrap_landscape(force=False)
                load_feasibility_disease_catalog.clear()
                if res.get("skipped"):
                    st.session_state["landscape_msg"] = res.get("reason", "已加载")
                else:
                    st.session_state["landscape_msg"] = (
                        f"已从 API 加载 {res['disease_count']} 种疾病"
                    )
                st.rerun()
    with c2:
        if st.button(
            "强制重载",
            use_container_width=True,
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            with st.spinner("正在强制从 LIS API 重载 …"):
                bootstrap_landscape(force=True)
                load_feasibility_disease_catalog.clear()
                st.session_state["landscape_msg"] = "已强制从 API 重载"
                st.rerun()
    if st.session_state.get("landscape_msg"):
        st.success(st.session_state["landscape_msg"])

    if lc > 0:
        with st.expander("缓存疾病分布图谱快照", expanded=False):
            for row in get_all_landscape():
                cat = row["payload"].get("catalog", {})
                v11 = row["payload"].get("v11") or {}
                mol_n = len(v11.get("molecular_positivity") or [])
                st.markdown(
                    f"**{row['disease_id']}** — {cat.get('name_zh', '')} "
                    f"（{cat.get('total_cases', 0)} 例） · "
                    f"subtypes={len(v11.get('subtype_distribution') or [])} · "
                    f"attrs={len(v11.get('attribute_distribution') or [])} · "
                    f"markers={mol_n} · 更新于 {row.get('updated_at', '')}"
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
        sub_v03,
        sub_cross,
        sub_gap,
    ) = st.tabs([
        "D-01 / D-02 目录",
        "亚型（§7.4）",
        "属性（§7.3）",
        "分子（§7.8）",
        "文本匹配（§7.5–7.7）",
        "V-01 可行性",
        "V-02 空白分析",
        "V-03 公开数据集",
        "文献×数据矩阵",
        "从空白快速核查",
    ])

    with sub_catalog:
        st.markdown(f"**{FEAS_API_META['D-01']['name']}** · `{FEAS_API_META['D-01']['endpoint']}`")
        col_a, col_b = st.columns(2)
        with col_a:
            organ = st.selectbox(
                "organ_system（API OrganSystem）",
                organ_options,
                format_func=lambda x: x or "（全部）",
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
            "查询 D-01",
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
            st.metric("疾病类型总数", r.get("total", 0))
            render_tool_result("pathology_disease_catalog", r)

        st.divider()
        st.markdown(f"**{FEAS_API_META['D-02']['name']}** · `{FEAS_API_META['D-02']['endpoint']}`")
        d02_id = st.selectbox(
            "disease_id（DiseaseCode）",
            disease_ids,
            format_func=lambda did: format_disease_option(did, disease_catalog),
            key="feas_d02_disease",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        c_d02a, c_d02b = st.columns(2)
        with c_d02a:
            if st.button(
                "查询 D-02 任务",
                key="btn_d02",
                on_click=remember_main_tab_for(_DATA_TAB_LABEL),
            ):
                st.session_state["d02_result"] = tool_pathology_tasks_for_disease(d02_id)
        with c_d02b:
            if st.button(
                "查询队列统计（§7.1/7.2）",
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
                m1.metric("患者", cr.get("patient_count", 0))
                m2.metric("标本", cr.get("specimen_count", 0))
                m3.metric("切片", cr.get("slide_count", 0))
                m4.metric("医院", cr.get("hospital_count", 0))

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
            "查询亚型分布",
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
                    st.info("当前 API 样本中该疾病无亚型行。")

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
            "属性关键词（可选）",
            value="",
            key="attr_keyword",
            placeholder="分期 / 分级 / severity / Gleason …",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "查询属性分布",
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
                    st.info("该疾病 / 关键词下无匹配属性行。")

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
            "查询阳性率",
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
                c1.metric("队列患者", r.get("patient_scope", 0))
                c2.metric("已检测", r.get("tested_patients", 0))
                c3.metric("阳性", r.get("positive_patients", 0))
                c4.metric("阳性率", f"{r.get('positivity_rate', 0):.1%}")

    with sub_text:
        st.markdown(f"**{FEAS_API_META['text']['name']}** · `{FEAS_API_META['text']['endpoint']}`")
        st.caption(
            "使用 text_disease_match 做 NLP/报告命中追溯。"
            "独立 disease_alias_dict REST 尚未开放 — 请通过匹配结果与疾病字典解析。"
        )
        tx_options = ["(all)"] + disease_ids
        tx_id = st.selectbox(
            "disease_id 过滤",
            tx_options,
            format_func=lambda did: (
                "（全部疾病）"
                if did == "(all)"
                else format_disease_option(did, disease_catalog)
            ),
            key="text_disease",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        pending_only = st.checkbox(
            "仅待审（§7.7）",
            value=False,
            key="text_pending",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "查询文本匹配",
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
                st.metric("匹配总数", r.get("total_matches", 0))
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("**核验状态**")
                    vs = r.get("verification_status") or {}
                    if vs:
                        safe_table(
                            pd.DataFrame(
                                [{"status": k, "count": v} for k, v in vs.items()]
                            )
                        )
                with col_b:
                    st.markdown("**高频提及**")
                    mentions = r.get("top_mentions") or []
                    if mentions:
                        safe_table(pd.DataFrame(mentions), height=260)
                sample = r.get("sample") or []
                if sample:
                    with st.expander("样例行", expanded=False):
                        safe_table(pd.DataFrame(sample), height=320)

    with sub_v01:
        st.markdown(f"**{FEAS_API_META['V-01']['name']}** · `{FEAS_API_META['V-01']['endpoint']}`")
        st.caption(
            "汇总 LIS 查询 API 的样本数、患者、属性与分子结果，"
            "在本地计算 feasibility_score。"
        )
        fc1, fc2 = st.columns(2)
        with fc1:
            v01_disease = st.selectbox(
                "disease_id（DiseaseCode）",
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
                "required_labels（逗号分隔）",
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
            "运行 V-01 评估",
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
            "假设与 V-01 相同；突出数据瓶颈与替代方向。"
        )
        if st.button(
            "复制 V-01 表单并运行 V-02",
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

    with sub_v03:
        st.markdown(f"**{FEAS_API_META['V-03']['name']}** · `{FEAS_API_META['V-03']['endpoint']}`")
        st.caption(
            "经 focus 相关论文选出 USES_DATASET 中 access_class=public 的集合；"
            "数据集名不必包含 focus 关键词。"
        )
        v03_kw = st.text_input(
            "关键词 / 空白描述",
            value=focus_hint,
            key="v03_keyword",
            placeholder="例如 nasopharyngeal carcinoma WSI",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "运行 V-03 评估",
            type="primary",
            key="btn_v03",
            on_click=remember_main_tab_for(_DATA_TAB_LABEL),
        ):
            st.session_state["v03_result"] = tool_public_dataset_assess(v03_kw or "")
        if "v03_result" in st.session_state:
            render_public_dataset_result(st.session_state["v03_result"])

    with sub_cross:
        st.markdown(f"**{FEAS_API_META['cross']['name']}**")
        cross_focus = st.text_input(
            "文献焦点关键词",
            value=focus_hint,
            key="cross_focus",
            placeholder="例如 radiomics",
            on_change=remember_main_tab_for(_DATA_TAB_LABEL),
        )
        if st.button(
            "构建交叉矩阵",
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
                    "cross_priority_score = 文献空白 + LIS 队列 + 引用/IF 影响 "
                    "（完整加权需运行 enrich-s2 与 import-if）"
                )
            else:
                st.info("无交叉矩阵行（知识图谱可能为空 — 请先运行抽取）。")

    with sub_gap:
        st.markdown("**从辩论报告评估空白**")
        report_text = st.session_state.get("report", "")
        parsed_gaps = parse_gap_titles(report_text) if report_text else []
        if parsed_gaps:
            gap_pick = st.selectbox(
                "从辩论报告选择空白",
                parsed_gaps,
                key="feas_gap_pick",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
            if st.button(
                "评估所选空白",
                type="primary",
                key="btn_gap_assess",
                on_click=remember_main_tab_for(_DATA_TAB_LABEL),
            ):
                fr = assess_gap_feasibility(gap_pick, report_text)
                st.session_state["gap_feas_result"] = fr
        else:
            manual_gap = st.text_area(
                "或输入空白标题 / 描述",
                height=100,
                key="feas_manual_gap",
                on_change=remember_main_tab_for(_DATA_TAB_LABEL),
            )
            if st.button(
                "评估手动输入的空白",
                key="btn_manual_gap",
                on_click=remember_main_tab_for(_DATA_TAB_LABEL),
            ) and manual_gap.strip():
                fr = assess_gap_feasibility(manual_gap.strip(), manual_gap.strip())
                st.session_state["gap_feas_result"] = fr

        fr = st.session_state.get("gap_feas_result")
        if fr:
            st.markdown(f"**{fr.gap_title}**")
            m1, m2, m3 = st.columns(3)
            m1.metric("映射 disease_id", fr.disease_id or "—")
            m2.metric("映射置信度", f"{fr.map_confidence:.2f}")
            m3.metric("状态", fr.status)
            st.markdown("##### 方信 V-01")
            render_feasibility_result(fr.assessment)
            pda = getattr(fr, "public_dataset_assessment", None) or {}
            if pda:
                st.markdown("##### 公开数据集 V-03")
                render_public_dataset_result(pda)
            if fr.evolution_log:
                with st.expander("演化日志"):
                    st.json(fr.evolution_log)


def render_tool_result(name: str, result: dict) -> None:
    if "error" in result:
        st.error(f"错误：{result['error']}")
        return
    desc = result.get("description", "")
    if desc:
        st.caption(desc)

    if name == "corpus_focus_coverage":
        metrics = extract_corpus_focus_metrics(result)
        if metrics is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("焦点论文", metrics["focus_papers"])
            c2.metric("焦点已抽取", metrics["focus_extracted"])
            c3.metric("全局论文", metrics["global_papers"])
            ratio = metrics["coverage_ratio"]
            ratio_text = f"{ratio * 100:.2f}%" if isinstance(ratio, (int, float)) else "—"
            c4.metric("覆盖率", ratio_text)

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("方法实体", metrics["method_entities"])
            c6.metric("疾病实体", metrics["disease_entities"])
            c7.metric("局限关系", metrics["limitation_relations"])
            c8.metric(
                "可分析",
                "是" if metrics["analysis_ready"] else "否",
            )

            top_diseases = metrics.get("top_diseases") or []
            if top_diseases:
                st.markdown("**匹配疾病 Top**")
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
            st.info("未发现组合空白。")
        return

    if "results_backed" in result or "all_metrics" in result:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**结果章节支撑**")
            rb = result.get("results_backed", [])
            safe_table(pd.DataFrame(rb) if rb else pd.DataFrame())
        with c2:
            st.markdown("**全部指标**")
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
                        "标题/实体": str(title)[:80],
                        "证据章节": item.get("evidence_section") or item.get("sections", ""),
                        "摘录": str(quote)[:120] if quote else "",
                        "工具": TOOL_META.get(ev.get("name", ""), {}).get("label", ev.get("name", "")),
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
                "标题": title,
                "年份": item.get("year", ""),
                "期刊": item.get("journal_name") or item.get("journal", ""),
                "PMID": item.get("pmid", ""),
                "研究类型": item.get("study_type", ""),
                "全文": item.get("full_text_status", ""),
                "来源": TOOL_META.get(ev.get("name", ""), {}).get("label", ev.get("name", "")),
            }
    return sorted(seen.values(), key=lambda x: str(x.get("年份", "")), reverse=True)


def _format_corpus_paper_rows(rows: list[dict], *, found_via: str) -> list[dict]:
    out: list[dict] = []
    for item in rows:
        title = item.get("title") or ""
        if not title:
            continue
        out.append({
            "标题": title,
            "年份": item.get("year", ""),
            "期刊": item.get("journal_name") or item.get("journal", ""),
            "PMID": item.get("pmid", ""),
            "研究类型": item.get("study_type", ""),
            "全文": item.get("full_text_status", ""),
            "来源": found_via,
        })
    return sorted(out, key=lambda x: str(x.get("年份", "")), reverse=True)


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
        "语料焦点匹配"
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
            "流程：**机会侦察** → **证据审阅** → **综合终审**"
        )
        return
    st.markdown("#### 三个角色分别做什么？")
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
    with st.expander("辩论流程与置信度", expanded=False):
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


def _landscape_indexes() -> tuple[dict[str, int], dict[str, dict], list[str]]:
    """Read-only landscape cache indexes for Visualization (no bootstrap)."""
    cases: dict[str, int] = {}
    by_id: dict[str, dict] = {}
    names: list[str] = []
    for row in get_all_landscape():
        did = row["disease_id"]
        payload = row.get("payload") or {}
        cat = payload.get("catalog") or {}
        cases[did] = int(cat.get("total_cases") or 0)
        by_id[did] = {**payload, "updated_at": row.get("updated_at")}
        for n in (cat.get("name_en"), cat.get("name_zh"), did):
            if n:
                names.append(str(n))
    return cases, by_id, names


def _fangxin_scale_metrics(payload: dict) -> dict[str, int]:
    """Four scale metrics from landscape payload (sample_size / pools)."""
    cat = payload.get("catalog") or {}
    ss = payload.get("sample_size") or {}
    pools = payload.get("feasibility_pools") or {}
    total = int(ss.get("total_cases") or cat.get("total_cases") or 0)
    wsi = int(
        ss.get("total_wsi_slides")
        or ss.get("cases_with_wsi")
        or pools.get("has_wsi")
        or 0
    )
    followup = int(
        ss.get("cases_with_followup")
        or pools.get("has_survival_label")
        or pools.get("meets_followup_12m")
        or 0
    )
    mol_keys = ("has_msi_status", "has_her2", "has_egfr", "has_alk", "has_pd_l1")
    molecular = max((int(pools.get(k) or 0) for k in mol_keys), default=0)
    return {
        "total_cases": total,
        "wsi": wsi,
        "followup": followup,
        "molecular": molecular,
    }


def render_gap_visualization_tab(
    events: list[dict],
    *,
    report_text: str = "",
    focus_hint: str = "",
) -> None:
    """Focus gaps × Fangxin dual-pane; session funnel/treemap under diagnostics."""
    st.subheader("焦点空白 × 方信支撑")
    st.caption(
        "左：侧栏焦点下的方法×疾病机会（有报告时叠加辩论标题）。"
        "右：所选疾病的方信疾病分布图谱缓存 — 只读；初始化在「数据可行性」页。"
    )

    focus = normalize_focus(focus_hint)
    show_all = st.checkbox(
        "显示全部覆盖等级",
        value=False,
        key="viz_show_all_coverage",
        help="默认仅显示文献未覆盖 / 极少覆盖的空白。",
    )
    top_n = st.slider("Top N", 10, 50, 30, key="viz_top_n")

    disease_cases, landscape_by_id, catalog_names = _landscape_indexes()

    gaps: list[dict] = []
    if focus is None:
        st.info("请在侧栏设置研究焦点。")
    else:
        try:
            gaps = list(tool_method_disease_combo_gap(focus=focus).get("gaps") or [])
        except Exception as exc:
            st.warning(f"无法加载方法×疾病组合：{exc}")
            gaps = []

    disease_id_by_name: dict[str, str | None] = {}
    for disease_name in sorted({str(g.get("disease") or "") for g in gaps if g.get("disease")}):
        did, _conf, _reason = map_gap_to_disease(
            disease_name,
            known_diseases=list(catalog_names),
            client=None,
        )
        disease_id_by_name[disease_name] = did

    debate_titles = parse_gap_titles(report_text) if (report_text or "").strip() else []
    view = assemble_opportunity_view(
        gaps=gaps,
        disease_cases=disease_cases,
        disease_id_by_name=disease_id_by_name,
        debate_titles=debate_titles or None,
        scarce_only=not show_all,
        limit=int(top_n),
    )
    rows = list(view.get("rows") or [])
    summary = view.get("summary") or {}
    unmatched = list(view.get("unmatched_debate") or [])
    matched_count = int(view.get("debate_matched_count") or 0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("组合数", int(summary.get("combo_count") or 0))
    m2.metric("文献稀缺", int(summary.get("scarce_count") or 0))
    m3.metric("已映射方信", int(summary.get("mapped_count") or 0))
    m4.metric("高数据占比", f"{float(summary.get('high_share') or 0):.0f}%")

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**机会表**")
        if focus is None:
            st.caption("设置焦点以加载知识图谱组合。")
        elif not gaps:
            st.info("该焦点下无方法×疾病组合 — 请先运行抽取 / 入库。")
        elif not rows:
            st.info(
                "过滤后无行 — 请启用 **显示全部覆盖等级** "
                "或增大 Top N。"
            )
        else:
            display_rows = [
                {
                    "来源": r.get("source") or "",
                    "方法": r.get("method") or "",
                    "疾病": r.get("disease") or "",
                    "文献空白": r.get("gap") or "",
                    "论文数": int(r.get("paper_cnt") or 0),
                    "方信": r.get("disease_id") or "—",
                    "数据": r.get("data") or "none",
                }
                for r in rows
            ]
            st.dataframe(
                pd.DataFrame(display_rows),
                use_container_width=True,
                hide_index=True,
            )

            options = [str(r["row_key"]) for r in rows]
            label_by_key = {
                str(r["row_key"]): (
                    f"{r.get('source') or '语料'} · "
                    f"{r.get('method') or '?'} · "
                    f"{r.get('disease') or '?'}"
                )
                for r in rows
            }
            current = st.session_state.get("viz_selected_combo")
            if current not in options:
                st.session_state["viz_selected_combo"] = options[0]
            st.selectbox(
                "所选组合",
                options,
                format_func=lambda k: label_by_key.get(k, k),
                key="viz_selected_combo",
            )
            st.caption(f"已有 {matched_count} 条辩论空白匹配到表格。")
            if unmatched:
                listed = "\n".join(f"- {t}" for t in unmatched[:12])
                extra = f"\n- …另有 {len(unmatched) - 12} 条" if len(unmatched) > 12 else ""
                st.info(f"未匹配的辩论空白（不伪造行展示）：\n{listed}{extra}")

    with col_r:
        st.markdown("**方信详情**")
        selected_key = st.session_state.get("viz_selected_combo")
        selected = next((r for r in rows if str(r.get("row_key")) == selected_key), None)
        if not rows or selected is None:
            st.info("请在左侧选择一行")
        else:
            disease_name = str(selected.get("disease") or "")
            did = selected.get("disease_id")
            if not did:
                st.warning(
                    f"**{disease_name or '疾病'}** — 无法映射到方信 DiseaseCode"
                )
            elif did not in landscape_by_id:
                st.info(
                    f"`{did}` 无疾病分布图谱缓存 — 请在「数据可行性」中初始化"
                )
            else:
                payload = landscape_by_id[did]
                cat = payload.get("catalog") or {}
                zh = cat.get("name_zh") or ""
                en = cat.get("name_en") or ""
                names = " / ".join(x for x in (zh, en) if x) or disease_name
                st.markdown(
                    f"**`{did}`** — {names} · 数据 **{selected.get('data') or 'none'}**"
                )
                st.caption(f"updated_at: {payload.get('updated_at') or '—'}")

                scale = _fangxin_scale_metrics(payload)
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("总病例", scale["total_cases"])
                s2.metric("WSI 切片/病例", scale["wsi"])
                s3.metric("随访病例", scale["followup"])
                s4.metric("分子标注", scale["molecular"])

                v11 = payload.get("v11") or {}
                subtypes = list(v11.get("subtype_distribution") or [])
                molecular = list(v11.get("molecular_positivity") or [])

                fig_sub = build_subtype_bar(subtypes) if plotly_available() else None
                if fig_sub is not None:
                    st.plotly_chart(fig_sub, use_container_width=True)
                elif subtypes:
                    safe_table(pd.DataFrame(subtypes[:8]), height=280)
                else:
                    st.caption("疾病分布图谱缓存中无亚型分布。")

                fig_mol = build_molecular_bar(molecular) if plotly_available() else None
                if fig_mol is not None:
                    st.plotly_chart(fig_mol, use_container_width=True)
                elif molecular:
                    safe_table(pd.DataFrame(molecular[:8]), height=280)
                else:
                    st.caption("疾病分布图谱缓存中无分子阳性率。")

                st.caption(
                    "更深入的队列评估见：**数据可行性 → V-01**。"
                )

    with st.expander("会话诊断", expanded=False):
        st.caption("当前会话的辩论漏斗与工具树图（可选）。")
        if not plotly_available():
            st.warning(
                "诊断图表缺少 **plotly**。请安装："
                "`..\\.venv\\Scripts\\pip.exe install plotly`。"
            )
        bundle = build_gap_viz_bundle(
            events,
            report_text=report_text,
            focus=focus,
            tool_meta=TOOL_META,
            category_colors=CATEGORY_COLOR,
        )
        stats = bundle["funnel_stats"]
        if events or report_text:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("侦察候选", stats.get("scout_candidates", 0))
            c2.metric("已核实", stats.get("verified", 0))
            c3.metric("弱证据", stats.get("weak_evidence", 0))
            c4.metric("伪空白", stats.get("false_gaps", 0))
            c5.metric("最终空白", stats.get("final_gaps", 0))

        d1, d2 = st.columns(2)
        with d1:
            if bundle["funnel_fig"] is not None:
                st.plotly_chart(bundle["funnel_fig"], use_container_width=True)
            elif not events:
                st.info("运行空白辩论以填充辩论漏斗。")
            else:
                st.info("辩论数据不足，无法绘制漏斗图。")
        with d2:
            if bundle["treemap_fig"] is not None:
                st.plotly_chart(bundle["treemap_fig"], use_container_width=True)
            else:
                st.info("智能体调用知识图谱工具后将显示工具树图。")


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
    """Weekly publication hotspots, WoW deltas, gap opportunities, optional LLM brief."""
    from analysis.hotspot_brief import save_hotspot_brief
    from analysis.weekly_hotspot import (
        generate_hotspot_report,
        list_weekly_hotspot_weeks,
        save_hotspot_report,
        week_id,
    )
    from db.schema import weekly_hotspot_stats

    st.subheader("每周研究热点")
    st.caption(
        f"发表窗口：**{config.HOTSPOT_WINDOW_DAYS} 天**（`papers.pub_date`，"
        "仅 `date_precision` ∈ day/month） · "
        "年精度日期不进主榜 · 周环比依赖已持久化的快照。"
    )

    hs = weekly_hotspot_stats()
    weeks = list_weekly_hotspot_weeks()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("快照周数", hs.get("hotspot_runs", 0))
    c2.metric("快照行数", hs.get("hotspot_snapshot_rows", 0))
    c3.metric("当前周", week_id())
    c4.metric("上一快照", weeks[1] if len(weeks) > 1 else "—")

    window_days = st.slider(
        "发表窗口（天）",
        7,
        30,
        config.HOTSPOT_WINDOW_DAYS,
        key="hotspot_window_days",
    )
    payload = _load_weekly_hotspot_payload(len(weeks), window_days)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "窗口内发表",
        payload.get("papers_in_window", payload.get("papers_ingested", 0)),
    )
    m2.metric("排除(年精度)", payload.get("papers_excluded_low_precision", 0))
    m3.metric("热门方法", (payload.get("emerging_methods") or [{}])[0].get("name", "—"))
    m4.metric("空白机会", len(payload.get("emerging_gap_opportunities") or []))

    wow = payload.get("week_over_week") or {}
    if wow.get("has_baseline"):
        st.markdown(f"**周环比** 对比 `{wow.get('previous_week_id')}`")
        for board, title in [("method", "方法"), ("disease", "疾病"), ("combo", "组合")]:
            b = wow.get("boards", {}).get(board, {})
            new_e = ", ".join(r["label"][:40] for r in b.get("new_entrants", [])[:3]) or "—"
            cooled = ", ".join(r["label"][:40] for r in b.get("cooled", [])[:3]) or "—"
            st.caption(f"{title}：新增 [{new_e}] · 降温 [{cooled}]")
    else:
        st.info(
            f"尚无上一快照（{wow.get('previous_week_id', '?')}）。"
            "请每周运行 **保存快照报告** 以启用对比。"
        )

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("刷新热点", use_container_width=True):
            _load_weekly_hotspot_payload.clear()
            st.rerun()
    with col_b:
        save_btn = st.button("保存快照报告", use_container_width=True)
    with col_c:
        brief_btn = st.button("生成 LLM 简报", use_container_width=True)

    if save_btn:
        path, saved = save_hotspot_report(persist=True)
        st.success(f"已保存 {path}（{saved.get('snapshot_rows', 0)} 行）")
        _load_weekly_hotspot_payload.clear()
        st.rerun()

    if brief_btn:
        with st.spinner(f"正在生成简报（{config.LLM_MODEL_AGENT}）…"):
            brief_path, brief_text, _ = save_hotspot_brief(persist=True)
        st.session_state["hotspot_brief"] = brief_text
        st.success(f"简报已保存：{brief_path}")

    tab_m, tab_d, tab_c, tab_o, tab_l = st.tabs([
        "方法",
        "疾病",
        "热门组合",
        "空白机会",
        "局限",
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
            st.info("本窗口内无热点×空白交叉。")
    with tab_l:
        safe_table(pd.DataFrame(payload.get("new_limitations", [])))

    if st.session_state.get("hotspot_brief"):
        st.divider()
        st.markdown("### LLM 简报")
        st.markdown(st.session_state["hotspot_brief"])

    with st.expander("完整 Markdown 报告预览", expanded=False):
        st.markdown(generate_hotspot_report(payload, wow=wow))


# Session state
for _k, _v in [
    ("events", []), ("report", ""), ("run_focus", ""), ("run_top_n", 3),
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
    st.title("研究空白分析")
    stats = db_stats()
    _sub_l, _sub_r = st.columns([4, 3], vertical_alignment="center")
    with _sub_l:
        st.caption("病理组学全文分析")
    with _sub_r:
        with st.popover("语料库"):
            st.caption(
                "  \n".join(
                    [
                        f"论文总数：{stats['papers']}　|　已抽取：{stats['extracted']}",
                        f"抽取实体：{stats.get('entities', 0)}　|　全文关系：{stats['relations_fulltext']}",
                        f"引用已补全：{stats.get('s2_enriched', 0)}",
                        f"期刊影响因子库：{stats.get('journals_with_if', 0)} 种",
                        f"疾病分布图谱：{landscape_count()} 种疾病",
                    ]
                )
            )
    st.divider()

    focus_input = st.text_input(
        "研究焦点",
        placeholder="例如 breast cancer, radiomics, 肠息肉",
        help="疾病/主题焦点。支持中文别名（如 肠息肉 → colorectal polyp）。",
    )
    _foc_norm = normalize_focus(focus_input)
    if _foc_norm:
        from analysis.disease_synonyms import resolve_disease_concept  # noqa: E402

        _resolved = resolve_disease_concept(_foc_norm)
        if _resolved:
            _fx = (
                f" · 方信 {_resolved.fangxin_disease_code}"
                if _resolved.fangxin_disease_code
                else ""
            )
            _cui = f" · CUI {_resolved.umls_cui}" if _resolved.umls_cui else ""
            st.caption(f"已解析：{_resolved.canonical}{_fx}{_cui}")
        elif any("\u4e00" <= ch <= "\u9fff" for ch in _foc_norm):
            st.caption("无同义词映射 — 可试英文疾病名")
    top_n_input = st.slider(
        "推荐研究空白条数",
        3,
        10,
        3,
        help="一次辩论中希望输出的研究空白候选数量",
    )
    debate_rounds_input = st.slider(
        "空白辩论轮次上限",
        1,
        3,
        2,
        help="机会侦察 → 证据审阅 → 综合终审 可重复的最大轮数",
    )
    proposal_rounds_input = st.slider(
        "研究提案迭代轮次上限",
        1,
        5,
        2,
        help="在「研究提案」页中，生成与评审交替迭代的最大轮数",
    )
    verbose_input = st.checkbox("显示 LLM 推理过程")
    use_ops_memory_input = st.checkbox(
        "使用运维记忆",
        value=True,
        help="注入该焦点最近 4 条已报告空白，软性回避相近方向",
    )
    persist_ops_memory_input = st.checkbox(
        "记忆本次运行",
        value=True,
        help="辩论或提案成功后写入 ops_runs 与空白条目",
    )
    with st.expander("当前焦点的运维记忆", expanded=False):
        from analysis.ops_memory import load_recent_gaps  # noqa: E402

        mem = load_recent_gaps(focus_input or None)
        if not mem.items:
            st.caption("暂无记忆")
        else:
            for it in mem.items[:40]:
                st.markdown(f"- `{it.week_id}` {it.title}")
    st.divider()
    run_button = st.button("运行空白辩论", type="primary", use_container_width=True)

    if st.session_state["events"]:
        s = compute_stats(st.session_state["events"])
        st.divider()
        st.markdown("**会话统计**")
        for label, val in [
            ("工具调用", s["tools_called"]),
            ("记录数", s["records_retrieved"]),
            ("摘要结果", s["summary_results"]),
            ("证据行数", s["evidence_rows"]),
        ]:
            st.metric(label, val)

st.title("病理 AI · 研究空白分析")
focus_label = f"焦点：*{focus_input}*" if focus_input else "全库"
st.caption(
    f"机会侦察 × 证据审阅 × 综合终审  |  "
    f"全文知识图谱  |  {focus_label}"
)
render_debate_role_guide(compact=True)
st.divider()

if run_button:
    st.session_state.update({
        "events": [], "report": "", "run_focus": focus_input or "全部",
        "run_top_n": top_n_input, "debate_confidence": 0.0,
    })
    live_events: list[dict] = []
    tool_step = 0
    current_role = ""

    with st.status(
        "正在辩论：机会侦察 → 证据审阅 → 综合终审 …",
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
                st.markdown(f"**辩论轮次 {event['round']} / {event['max_rounds']}**")
            elif etype == "phase_start":
                current_role = event.get("role", "")
                st.markdown(
                    f"{role_badge(current_role)} 阶段开始",
                    unsafe_allow_html=True,
                )
            elif etype == "llm_request_start":
                st.caption(
                    f"等待 {role_display(event.get('role', ''))} LLM "
                    f"（{event.get('iteration', '?')}/{event.get('max_iters', '?')}）…"
                )
            elif etype == "tool_call":
                tool_step += 1
                role = event.get("role", "")
                role_lbl = role_display(role)
                meta = TOOL_META.get(event["name"], {"label": event["name"]})
                args = event.get("args") or {}
                st.write(
                    f"  步骤 {tool_step} [{role_lbl}] {meta.get('label', event['name'])} "
                    f"· `{args}`"
                )
            elif etype == "tool_running":
                meta = TOOL_META.get(event["name"], {"label": event["name"]})
                st.caption(f"    … 正在运行 {meta.get('label', event['name'])}")
            elif etype == "tool_result":
                r = event.get("result", {})
                summary = format_tool_result_summary(event.get("name", ""), r)
                st.write(f"    → {summary}")
            elif etype == "tool_error":
                st.warning(f"[{event.get('role')}] {event['name']}: {event.get('error')}")
            elif etype == "optimist_proposal":
                st.success(
                    f"机会侦察候选（第 {event['round']} 轮）："
                    f"{len(event['content'])} 字符"
                )
            elif etype == "skeptic_review":
                st.info(
                    f"证据审阅置信度：{event['confidence']:.1f}/10  "
                    f"（核实={event['verified_count']}，伪空白={event['false_count']}）"
                )
            elif etype == "debate_feedback":
                st.warning(
                    f"综合终审修订请求："
                    f"{event.get('revision_priority', '')[:120]}"
                )
            elif etype == "thinking" and verbose_input:
                with st.expander(
                    f"推理 [{role_display(event.get('role', '?'))}]",
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
                        f"辩论完成 — {tool_step} 次工具调用，"
                        f"审阅置信度 {event.get('confidence', 0):.1f}/10"
                    ),
                    state="complete",
                    expanded=False,
                )
            elif etype == "error":
                st.error(event.get("content"))
                sw.update(label="辩论失败", state="error")

st.divider()

bootstrap_main_tab_state()

tab_debate, tab_hotspot, tab_viz, tab_evidence, tab_report, tab_data, tab_proposal = st.tabs(
    MAIN_TAB_LABELS
)
render_main_tab_sync()

if not st.session_state["events"]:
    with tab_debate:
        st.info(
            "在侧栏设置焦点并点击 **运行空白辩论**。"
            "系统将依次运行 **机会侦察** → **证据审阅** → **综合终审**。"
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
            st.subheader(f"论文（{len(papers)}）")
            if papers:
                st.caption(
                    f"按焦点「{foc}」经 {strategy} 匹配 "
                    "（运行空白辩论还可收集证据摘录）。"
                )
                safe_table(pd.DataFrame(papers))
            else:
                st.info(f"语料中无论文匹配焦点「{foc}」。")
        else:
            st.info("请运行空白辩论以填充证据与文献，或设置研究焦点。")
    with tab_report:
        st.info("请运行空白辩论以生成研究空白报告。")
        s = db_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("论文", s["papers"])
        c2.metric("已抽取", s["extracted"])
        c3.metric("全文可用", s["fulltext_available"])
        c4.metric("知识图谱 + 可行性工具", len(IDEA_TOOLS))
    with tab_data:
        render_data_feasibility_tab(focus_hint=focus_input)
    with tab_proposal:
        st.info("请先完成空白辩论，或使用 **数据可行性** 页测试 API。")

elif st.session_state["events"]:
    with tab_debate:
        st.subheader("辩论轨迹")
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
                    f"机会侦察 — 第 {card['round']} 轮候选",
                    expanded=False,
                ):
                    st.markdown(card.get("content", "")[:4000])
            elif ct == "skeptic_review":
                with st.expander(
                    f"证据审阅 — 第 {card['round']} 轮 "
                    f"（置信度 {card.get('confidence', 0):.1f}/10）",
                    expanded=False,
                ):
                    st.markdown(card.get("content", "")[:4000])
            elif ct == "debate_feedback":
                st.warning(
                    f"第 {card['round']} 轮 · 综合终审修订："
                    f"{card.get('revision_priority', '')}"
                )

        st.divider()
        for i, pair in enumerate(pairs, 1):
            call = pair.get("tool_call", {})
            res = pair.get("tool_result")
            err = pair.get("tool_error")
            name = call.get("name", "?")
            role = call.get("role", "")
            meta = TOOL_META.get(name, {"label": name, "category": "其他"})
            feas_lbl = IDEA_TOOL_META.get(name)
            label = feas_lbl or meta.get("label", name)
            role_lbl = role_display(role)
            with st.expander(f"步骤 {i}：[{role_lbl}] {label}", expanded=False):
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
        st.subheader(f"全文证据（{len(evidence)} 行）")
        if evidence:
            safe_table(pd.DataFrame(evidence))
        else:
            st.info("尚未抽取证据摘录。")
        st.divider()
        st.subheader(f"论文（{len(papers)}）")
        if papers:
            if lit_strategy.startswith("corpus_"):
                st.caption(
                    f"辩论工具未返回论文标题；显示焦点「{focus_lit}」的语料匹配 "
                    f"（{lit_strategy}）。"
                )
            safe_table(pd.DataFrame(papers))
        else:
            st.info("工具结果或语料焦点匹配中无论文元数据。")

    with tab_report:
        report_text = st.session_state.get("report", "")
        if not report_text:
            st.info("请运行空白辩论以生成报告。")
        else:
            display_report = humanize_debate_report(report_text)
            s = compute_stats(st.session_state["events"])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("焦点", st.session_state.get("run_focus", "全部"))
            c2.metric("辩论轮数", st.session_state.get("debate_rounds", 1))
            c3.metric("审阅置信度", f"{st.session_state.get('debate_confidence', 0):.1f}/10")
            c4.metric("工具调用", s["tools_called"])
            st.caption(
                "报告由 **综合终审** 产出。下文中的角色名已替换为 "
                "机会侦察 / 证据审阅 / 综合终审。"
            )
            st.divider()
            st.markdown(display_report)
            header = (
                f"# 病理组学/影像组学研究空白报告\n\n"
                f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"> 焦点：{st.session_state.get('run_focus')}\n"
                f"> 流程：机会侦察 → 证据审阅 → 综合终审\n\n---\n\n"
            )
            st.download_button(
                "下载报告（Markdown）",
                data=(header + display_report).encode("utf-8"),
                file_name=f"gap_debate_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
            )

    with tab_data:
        render_data_feasibility_tab(
            focus_hint=st.session_state.get("run_focus") or focus_input,
        )

    with tab_proposal:
        st.subheader("研究提案生成器")
        report_for_parse = st.session_state.get("report", "")
        parsed = parse_gap_titles(report_for_parse) if report_for_parse else []

        gap_source = st.radio(
            "空白来源",
            ["从报告选择", "手动输入"],
            horizontal=True,
            label_visibility="collapsed",
            key="gap_source",
            on_change=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
        )
        if gap_source == "从报告选择":
            gap_input = (
                st.selectbox(
                    "选择空白",
                    parsed,
                    key="gap_sel",
                    on_change=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
                )
                if parsed
                else ""
            )
            if not parsed:
                st.info("请先运行空白辩论以填充空白标题。")
        else:
            gap_input = st.text_area(
                "自定义空白",
                height=120,
                key="gap_manual",
                on_change=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
            )

        target_difficulty_input = st.selectbox(
            "目标难度",
            options=["easy", "moderate", "hard"],
            index=1,
            format_func=lambda x: _DIFFICULTY_LABELS.get(x, x),
            key="proposal_target_difficulty",
            help=(
                "引导提案雄心；评估难度另行计算并以颜色标注。"
            ),
            on_change=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
        )

        gen_btn = st.button(
            "生成研究提案",
            type="primary",
            disabled=not (gap_input and str(gap_input).strip()),
            on_click=remember_main_tab_for(_PROPOSAL_TAB_LABEL),
        )

        if gen_btn and gap_input:
            support_pmids = support_pmids_from_evidence(
                extract_evidence(st.session_state.get("events") or [])
            )
            proposal_gap_data = (
                {"support_pmids": support_pmids} if support_pmids else None
            )
            st.session_state.update({
                "idea_events": [], "proposal": "",
                "proposal_gap_text": str(gap_input).strip(),
                "proposal_rounds": [],
                "proposal_result_target_difficulty": None,
                "proposal_assessed_difficulty": None,
                "proposal_difficulty_delta": None,
                "proposal_difficulty_color": None,
                "proposal_difficulty_summary": None,
                "proposal_q_coverage_low": False,
                "proposal_difficulty_breakdown": {},
            })
            idea_events: list[dict] = []
            with st.status("生成器 × 评审循环 …", expanded=True) as psw:
                for event in stream_idea_agent(
                    gap_text=str(gap_input).strip(),
                    gap_data=proposal_gap_data,
                    max_rounds=proposal_rounds_input,
                    target_difficulty=target_difficulty_input,
                ):
                    idea_events.append(event)
                    st.session_state["idea_events"] = list(idea_events)
                    et = event.get("type")
                    if et in {"difficulty_assessed", "final"}:
                        st.session_state.update({
                            "proposal_result_target_difficulty": event.get(
                                "target_difficulty"
                            ),
                            "proposal_assessed_difficulty": event.get(
                                "assessed_difficulty"
                            ),
                            "proposal_difficulty_delta": event.get(
                                "difficulty_delta"
                            ),
                            "proposal_difficulty_color": event.get(
                                "difficulty_color", event.get("color")
                            ),
                            "proposal_difficulty_summary": event.get(
                                "difficulty_summary", event.get("summary_line")
                            ),
                            "proposal_q_coverage_low": bool(
                                event.get("q_coverage_low")
                            ),
                            "proposal_difficulty_breakdown": event.get(
                                "difficulty_breakdown", event.get("breakdown")
                            ) or {},
                        })
                    if et == "round_start":
                        st.markdown(f"#### 第 {event['round']} / {event['max_rounds']} 轮")
                    elif et == "tool_call":
                        role = event.get("role", "")
                        lbl = IDEA_TOOL_META.get(event["name"], event["name"])
                        st.write(f"  [{role}] {lbl} · `{event.get('args', {})}`")
                    elif et == "finalizing_draft":
                        st.caption(event.get("message", "正在生成完整提案…"))
                    elif et == "draft":
                        st.success(f"草稿 v{event['round']} — {len(event['content'])} 字符")
                        rl = st.session_state.get("proposal_rounds", [])
                        rl.append({"round": event["round"], "draft": event["content"], "feedback": None})
                        st.session_state["proposal_rounds"] = rl
                    elif et == "feedback":
                        st.markdown(f"评审：**{event['score']:.1f}/10** 接受={event['accept']}")
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
                                target_difficulty=event.get("target_difficulty"),
                                assessed_difficulty=event.get(
                                    "assessed_difficulty"
                                ),
                                difficulty_delta=event.get("difficulty_delta"),
                                difficulty_breakdown_json=json.dumps(
                                    event.get("difficulty_breakdown") or {},
                                    ensure_ascii=False,
                                ),
                            )
                        psw.update(
                            label=f"完成 — {event.get('rounds', 1)} 轮，得分 {event.get('final_score', 0):.1f}/10",
                            state="complete",
                            expanded=False,
                        )

        proposal = st.session_state.get("proposal", "")
        if proposal:
            st.divider()
            _difficulty_colors = {
                "green": "#2e7d32",
                "amber": "#ed6c02",
                "red": "#c62828",
            }
            _difficulty_color = _difficulty_colors.get(
                st.session_state.get("proposal_difficulty_color") or "green",
                "#2e7d32",
            )
            _target_difficulty = difficulty_display_target(st.session_state)
            _assessed_difficulty = st.session_state.get(
                "proposal_assessed_difficulty"
            )
            if _target_difficulty and _assessed_difficulty:
                st.markdown(
                    '<div style="display:flex;gap:8px;align-items:center;'
                    'margin:8px 0;">'
                    '<span style="padding:4px 10px;border-radius:999px;'
                    'background:#eee;">'
                    f"目标：<b>{_DIFFICULTY_LABELS.get(_target_difficulty, _target_difficulty)}</b></span>"
                    '<span style="padding:4px 10px;border-radius:999px;'
                    f'background:{_difficulty_color};color:#fff;">'
                    f"评估：<b>{_DIFFICULTY_LABELS.get(_assessed_difficulty, _assessed_difficulty)}</b></span>"
                    + (
                        '<span style="padding:4px 10px;border-radius:999px;'
                        'background:#9e9e9e;color:#fff;">Q 覆盖偏低</span>'
                        if st.session_state.get("proposal_q_coverage_low")
                        else ""
                    )
                    + "</div>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    st.session_state.get("proposal_difficulty_summary") or ""
                )
            p1, p2, p3 = st.columns(3)
            p1.metric("最终得分", f"{st.session_state.get('final_score', 0):.1f}/10")
            p2.metric("轮数", st.session_state.get("final_rounds", 1))
            _pfs = st.session_state.get("proposal_feasibility_score")
            p3.metric(
                "可行性",
                f"{float(_pfs):.2f}" if _pfs is not None else "无",
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
                    "提案看起来不完整。请重新生成，或检查状态日志中的 API / 工具错误。"
                )
            st.markdown("### 最终提案")
            st.markdown(proposal)
            st.download_button(
                "下载提案（Markdown）",
                data=proposal.encode("utf-8"),
                file_name=f"proposal_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
            )
