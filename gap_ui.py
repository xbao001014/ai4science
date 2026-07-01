"""
gap_ui.py
Streamlit visualization interface for the Research Gap Analysis Agent.

Shows the agent's full reasoning process in real time:
  - Tool call trace with parameters and retrieved data
  - Literature evidence table from KG queries
  - Final academic research report

Usage:
    streamlit run gap_ui.py
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

# ── Page config (must be the very first Streamlit call) ────────────────────
st.set_page_config(
    page_title="Pathology AI — Research Gap Analysis",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "Knowledge Graph-Driven Research Gap Analysis Agent"},
)

# ── Delayed imports (after page config) ────────────────────────────────────
from gap_agent import stream_agent, TOOL_SCHEMAS          # noqa: E402
from idea_agent import stream_idea_agent, IDEA_TOOLS      # noqa: E402
from utils.db import get_conn, init_db                    # noqa: E402

init_db()

# ─────────────────────────────────────────────────────────────────────────────
# Tool metadata registry
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# pyarrow-safe table renderer
# st.dataframe() internally imports pyarrow; on this machine the DLL is broken.
# safe_table() tries st.dataframe() first and falls back to st.table().
# ─────────────────────────────────────────────────────────────────────────────

def safe_table(df: "pd.DataFrame", height: int | None = None, **_kwargs) -> None:
    """Render a DataFrame without crashing when pyarrow is unavailable."""
    if df is None or (hasattr(df, "empty") and df.empty):
        st.caption("(no data)")
        return
    try:
        kw: dict = {"use_container_width": True, "hide_index": True}
        if height:
            kw["height"] = height
        st.dataframe(df, **kw)
    except Exception:
        # pyarrow DLL broken — fall back to plain HTML table
        st.markdown(df.to_html(index=False), unsafe_allow_html=True)


TOOL_META: dict[str, dict] = {
    "trend_overview":           {"label": "Annual Publication Trend",           "category": "Overview"},
    "hotspot_entities":         {"label": "Research Hotspot Entities",          "category": "Overview"},
    "disease_task_coverage":    {"label": "Disease–Task Coverage Matrix",       "category": "Coverage Gap"},
    "method_clinical_gap":      {"label": "Method–Clinical Translation Gap",    "category": "Translation Gap"},
    "dataset_scarcity":         {"label": "Dataset Scarcity Assessment",        "category": "Coverage Gap"},
    "underexplored_disease":    {"label": "High-Impact Underexplored Diseases", "category": "Coverage Gap"},
    "emerging_methods":         {"label": "Emerging Methodology Survey",        "category": "Frontier"},
    "method_disease_combo_gap": {"label": "Method x Disease Combination Gap",   "category": "Combination Gap"},
    "foundation_model_gaps":    {"label": "Foundation Model Application Gap",   "category": "Translation Gap"},
    "multimodal_gaps":          {"label": "Multimodal Research Gap",            "category": "Coverage Gap"},
    "recent_highcite_papers":   {"label": "Recent High-Impact Papers",          "category": "Literature"},
    "method_cooccurrence":      {"label": "Method Co-occurrence Network",       "category": "Overview"},
    "low_impact_direction":     {"label": "High-Volume Low-IF Directions",      "category": "Opportunity"},
    # Graph traversal tools
    "graph_entity_pagerank":       {"label": "Entity PageRank vs Paper Count",     "category": "Graph Analysis"},
    "graph_structural_holes":      {"label": "Structural Holes (Bridge Entities)",  "category": "Graph Analysis"},
    "graph_community_gaps":        {"label": "Community Detection & Gaps",         "category": "Graph Analysis"},
    "graph_disease_method_reach":  {"label": "Disease–Method Multi-hop Reachability", "category": "Graph Analysis"},
    "graph_citation_pagerank":     {"label": "Citation Network PageRank",          "category": "Graph Analysis"},
}

CATEGORY_COLOR: dict[str, str] = {
    "Overview":        "#1f77b4",
    "Coverage Gap":    "#d62728",
    "Translation Gap": "#ff7f0e",
    "Combination Gap": "#9467bd",
    "Frontier":        "#2ca02c",
    "Literature":      "#8c564b",
    "Opportunity":     "#17becf",
    "Graph Analysis":  "#e377c2",
}

# Idea-agent tool metadata
IDEA_TOOL_META: dict[str, str] = {
    "related_papers":             "Related Papers Retrieval",
    "methods_for_topic":          "AI Methods Survey",
    "datasets_for_topic":         "Dataset Inventory",
    "metrics_for_topic":          "Performance Baseline",
    "tasks_for_topic":            "Task Coverage",
    "clinical_studies_for_topic": "Clinical Study Survey",
    "highcite_landmark_papers":   "Landmark Papers",
    "foundation_model_methods":   "Foundation Model Methods",
    "emerging_tech_for_proposal": "Emerging Technologies",
}


def parse_gap_titles(report_text: str) -> list[str]:
    """Extract '研究空白 N：...' or '### N.' section titles from a gap report."""
    import re
    titles: list[str] = []
    # Pattern 1: ### 研究空白 1：Title
    for m in re.finditer(r"###\s*研究空白\s*\d+[：:]\s*(.+)", report_text):
        t = m.group(1).strip().rstrip("*").strip()
        if t:
            titles.append(t)
    # Pattern 2: **1. Title** or **研究空白 1**
    if not titles:
        for m in re.finditer(r"\*+\d+[\.\、]\s*(.+?)\*+", report_text):
            t = m.group(1).strip()
            if 5 < len(t) < 80:
                titles.append(t)
    return titles

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Step badge ─────────────────────────────────────────────────── */
.step-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px; height: 22px;
    border-radius: 50%;
    background: #495057;
    color: #fff;
    font-size: 0.72rem;
    font-weight: 700;
    margin-right: 8px;
    flex-shrink: 0;
}
/* ── Tool header ────────────────────────────────────────────────── */
.tool-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 2px;
}
.tool-name {
    font-weight: 600;
    font-size: 0.94rem;
    color: #212529;
}
.tool-tag {
    font-size: 0.72rem;
    padding: 2px 8px;
    border-radius: 10px;
    color: #fff;
    font-weight: 500;
}
.tool-meta-row {
    font-size: 0.80rem;
    color: #6c757d;
    margin-top: 2px;
}
/* ── Stat box ───────────────────────────────────────────────────── */
.stat-box {
    background: #f1f3f5;
    padding: 10px 8px;
    border-radius: 6px;
    text-align: center;
    margin-bottom: 8px;
}
.stat-value {
    font-size: 1.7rem;
    font-weight: 700;
    color: #212529;
    line-height: 1.2;
}
.stat-label {
    font-size: 0.72rem;
    color: #868e96;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
/* ── Section divider ────────────────────────────────────────────── */
.section-rule {
    border: none;
    border-top: 1px solid #dee2e6;
    margin: 18px 0 12px;
}
/* ── Paper card ─────────────────────────────────────────────────── */
.paper-card {
    border: 1px solid #dee2e6;
    border-radius: 4px;
    padding: 10px 14px;
    margin-bottom: 6px;
    background: #fff;
}
.paper-title { font-weight: 500; font-size: 0.92rem; color: #212529; }
.paper-meta  { font-size: 0.79rem; color: #6c757d; margin-top: 3px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def _tag_html(category: str) -> str:
    color = CATEGORY_COLOR.get(category, "#6c757d")
    return f'<span class="tool-tag" style="background:{color}">{category}</span>'


def render_tool_result(name: str, result: dict) -> None:
    """Render one tool result in the most readable format for its structure."""
    if "error" in result:
        st.error(f"Error: {result['error']}")
        return

    desc = result.get("description", "")
    if desc:
        st.caption(desc)

    # ── Standard flat list ────────────────────────────────────────────────
    if "data" in result and isinstance(result["data"], list) and result["data"]:
        df = pd.DataFrame(result["data"])
        safe_table(df, height=min(400, 40 + len(df) * 35))
        return

    # ── method_disease_combo_gap: gap matrix ──────────────────────────────
    if "gaps" in result:
        gaps = result.get("gaps", [])
        if not gaps:
            st.info("No unexplored combinations found within the specified focus.")
            return
        try:
            df_gaps = pd.DataFrame(gaps)
            if {"method", "disease", "paper_cnt"}.issubset(df_gaps.columns):
                pivot = df_gaps.pivot_table(
                    index="method", columns="disease",
                    values="paper_cnt", aggfunc="first", fill_value=0,
                )
                pivot = pivot.iloc[:12, :14]  # cap display size

                try:
                    import plotly.graph_objects as go  # type: ignore
                    fig = go.Figure(go.Heatmap(
                        z=pivot.values.tolist(),
                        x=list(pivot.columns),
                        y=list(pivot.index),
                        colorscale=[
                            [0.00, "#c0392b"],
                            [0.01, "#e67e22"],
                            [0.20, "#f1c40f"],
                            [1.00, "#27ae60"],
                        ],
                        text=[[str(v) for v in row] for row in pivot.values.tolist()],
                        texttemplate="%{text}",
                        showscale=True,
                        colorbar=dict(title="Papers", thickness=12),
                    ))
                    fig.update_layout(
                        title="Method x Disease Combination Matrix  (0 = unexplored gap)",
                        height=max(320, len(pivot) * 38 + 120),
                        margin=dict(l=160, r=40, t=50, b=130),
                        xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
                        yaxis=dict(tickfont=dict(size=10)),
                        font=dict(size=11),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                except ImportError:
                    safe_table(pivot)
            else:
                safe_table(df_gaps)
        except Exception:
            safe_table(pd.DataFrame(gaps))
        return

    # ── foundation_model_gaps: two side-by-side tables ────────────────────
    if "diseases_with_fm" in result or "diseases_without_fm" in result:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Diseases with Foundation Model studies**")
            data = result.get("diseases_with_fm", [])
            safe_table(pd.DataFrame(data) if data else pd.DataFrame())
        with c2:
            st.markdown("**Diseases WITHOUT Foundation Model studies** (gap)")
            data = result.get("diseases_without_fm", [])
            safe_table(pd.DataFrame(data) if data else pd.DataFrame())
        return

    # ── Fallback ──────────────────────────────────────────────────────────
    st.json(result)


def extract_papers(events: list[dict]) -> list[dict]:
    """Collect all paper-like records across tool results, deduplicated by title."""
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
                "Title":       title,
                "Year":        item.get("year", ""),
                "Journal":     item.get("journal_name") or item.get("journal", ""),
                "Citations":   item.get("citation_count") or item.get("cited_by_in_corpus") or 0,
                "Study Type":  item.get("study_type", ""),
                "Found via":   TOOL_META.get(ev["name"], {}).get("label", ev["name"]),
            }
    return sorted(seen.values(), key=lambda x: -(int(x.get("Citations") or 0)))


def compute_stats(events: list[dict]) -> dict:
    calls   = sum(1 for e in events if e.get("type") == "tool_call")
    records = sum(
        len(e.get("result", {}).get("data", e.get("result", {}).get("gaps", [])))
        for e in events if e.get("type") == "tool_result"
    )
    papers  = len(extract_papers(events))
    return {"tools_called": calls, "records_retrieved": records, "papers_found": papers}


def group_call_result_pairs(events: list[dict]) -> list[dict[str, Any]]:
    """Pair each tool_call with its corresponding tool_result or tool_error."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────────────────────────────────────
for _k, _v in [("events", []), ("report", ""), ("run_focus", ""), ("run_top_n", 6),
                ("idea_events", []), ("proposal", ""), ("selected_gap", ""),
                ("proposal_gap_text", ""), ("proposal_rounds", []),
                ("final_rounds", 1), ("final_score", 0.0)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — configuration
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Research Gap Analysis")
    st.caption("Pathology AI Knowledge Graph")
    st.divider()

    focus_input = st.text_input(
        "Research domain focus",
        placeholder="e.g. lung cancer, segmentation, foundation model",
        help="Leave blank for a comprehensive full-domain analysis.",
    )
    top_n_input = st.slider("Number of recommendations", min_value=3, max_value=10, value=6)
    verbose_input = st.checkbox("Show LLM reasoning traces")
    st.divider()
    run_button = st.button("Run Analysis", type="primary", use_container_width=True)

    # Post-run summary statistics
    if st.session_state["events"]:
        stats = compute_stats(st.session_state["events"])
        st.divider()
        st.markdown("**Session statistics**")
        for label, value in [
            ("Tools called",      stats["tools_called"]),
            ("Records retrieved", stats["records_retrieved"]),
            ("Papers identified", stats["papers_found"]),
        ]:
            st.markdown(
                f'<div class="stat-box">'
                f'<div class="stat-value">{value}</div>'
                f'<div class="stat-label">{label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Page header
# ─────────────────────────────────────────────────────────────────────────────
st.title("Pathology AI — Research Gap Analysis")
focus_label = f"Focus domain: *{focus_input}*" if focus_input else "Full-domain analysis"
st.caption(f"Knowledge graph-driven research direction recommendation  |  {focus_label}")
st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# Run the agent (streams events into session state in real time)
# ─────────────────────────────────────────────────────────────────────────────
if run_button:
    st.session_state["events"]    = []
    st.session_state["report"]    = ""
    st.session_state["run_focus"] = focus_input or "All domains"
    st.session_state["run_top_n"] = top_n_input

    live_events: list[dict] = []
    tool_step = 0

    with st.status("Running knowledge graph analysis …", expanded=True) as status_widget:
        for event in stream_agent(
            focus=focus_input or None,
            top_n=top_n_input,
            max_iterations=25,
        ):
            live_events.append(event)
            st.session_state["events"] = list(live_events)   # persist incrementally
            etype = event.get("type", "")

            if etype == "tool_call":
                tool_step += 1
                meta      = TOOL_META.get(event["name"], {})
                label     = meta.get("label", event["name"])
                category  = meta.get("category", "")
                focus_arg = (event.get("args") or {}).get("focus") or "all"
                st.write(f"**Step {tool_step}** — {label}  ·  category: *{category}*  ·  focus: `{focus_arg}`")

            elif etype == "tool_result":
                result    = event.get("result", {})
                n_records = len(result.get("data", result.get("gaps", [])))
                st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;Retrieved {n_records} records")

            elif etype == "tool_error":
                st.warning(f"Tool error [{event.get('name')}]: {event.get('error')}")

            elif etype == "thinking" and verbose_input:
                with st.expander("LLM reasoning trace", expanded=False):
                    st.markdown(event.get("content", ""))

            elif etype == "final":
                st.session_state["report"] = event.get("content", "")
                status_widget.update(
                    label=f"Analysis complete — {tool_step} KG queries executed",
                    state="complete",
                    expanded=False,
                )

            elif etype == "error":
                st.error(event.get("content", "Unknown error"))
                status_widget.update(label="Analysis failed", state="error")


# ─────────────────────────────────────────────────────────────────────────────
# Results display (three tabs)
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state["events"]:
    tab_process, tab_papers, tab_report, tab_proposal = st.tabs([
        "Analysis Process",
        "Referenced Literature",
        "Research Report",
        "Research Proposal",
    ])

    # ── Tab 1: Analysis Process ─────────────────────────────────────────
    with tab_process:
        st.subheader("Knowledge Graph Query Trace")
        st.caption(
            "Each step corresponds to one knowledge graph query issued by the agent. "
            "Expand a step to inspect the retrieved data."
        )

        pairs = group_call_result_pairs(st.session_state["events"])

        if not pairs:
            st.info("No tool calls recorded yet.")
        else:
            for step_num, pair in enumerate(pairs, start=1):
                call_ev   = pair.get("tool_call", {})
                result_ev = pair.get("tool_result")
                error_ev  = pair.get("tool_error")

                name      = call_ev.get("name", "unknown")
                meta      = TOOL_META.get(name, {"label": name, "category": "Other"})
                label     = meta.get("label", name)
                category  = meta.get("category", "Other")
                color     = CATEGORY_COLOR.get(category, "#6c757d")
                focus_arg = (call_ev.get("args") or {}).get("focus") or "all"

                n_records = 0
                if result_ev:
                    r = result_ev.get("result", {})
                    n_records = len(r.get("data", r.get("gaps", [])))

                header_html = (
                    f'<div class="tool-header">'
                    f'<span class="step-badge">{step_num}</span>'
                    f'<span class="tool-name">{label}</span>'
                    f'<span class="tool-tag" style="background:{color}">{category}</span>'
                    f'</div>'
                    f'<div class="tool-meta-row">'
                    f'Function: <code>{name}</code> &nbsp;|&nbsp; '
                    f'Focus: <code>{focus_arg}</code> &nbsp;|&nbsp; '
                    f'Records retrieved: <strong>{n_records}</strong>'
                    f'</div>'
                )

                with st.expander(f"Step {step_num}: {label}", expanded=False):
                    st.markdown(header_html, unsafe_allow_html=True)
                    st.markdown('<hr class="section-rule">', unsafe_allow_html=True)

                    if error_ev:
                        st.error(f"Error: {error_ev.get('error', 'Unknown error')}")
                    elif result_ev:
                        render_tool_result(name, result_ev.get("result", {}))
                    else:
                        st.info("Result not yet received.")

        # Reasoning traces (if any)
        thinking_events = [e for e in st.session_state["events"] if e.get("type") == "thinking"]
        if thinking_events:
            st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
            st.subheader("LLM Reasoning Traces")
            for i, ev in enumerate(thinking_events, 1):
                with st.expander(f"Reasoning trace {i}", expanded=False):
                    st.markdown(ev.get("content", ""))

    # ── Tab 2: Referenced Literature ────────────────────────────────────
    with tab_papers:
        papers = extract_papers(st.session_state["events"])
        st.subheader(f"Literature Identified During Analysis ({len(papers)} papers)")
        st.caption(
            "Papers retrieved from the knowledge graph queries, ranked by citation count. "
            "These constitute the empirical evidence base for the research gap analysis."
        )

        if not papers:
            st.info("No papers with structured metadata were retrieved. Run the analysis to populate this section.")
        else:
            # Filters
            fc1, fc2 = st.columns([3, 1])
            with fc1:
                search_term = st.text_input("Filter", placeholder="Search title, journal, study type …")
            with fc2:
                min_cites = st.number_input("Min. citations", min_value=0, value=0, step=10)

            df_papers = pd.DataFrame(papers)
            df_papers["Citations"] = pd.to_numeric(df_papers["Citations"], errors="coerce").fillna(0).astype(int)

            if search_term:
                mask = df_papers.apply(lambda row: search_term.lower() in str(row).lower(), axis=1)
                df_papers = df_papers[mask]
            if min_cites > 0:
                df_papers = df_papers[df_papers["Citations"] >= min_cites]

            st.caption(f"Showing {len(df_papers)} of {len(papers)} papers")
            safe_table(df_papers)

            # Citation distribution chart
            if len(df_papers) > 3:
                st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
                st.markdown("**Citation distribution of identified papers**")
                try:
                    import numpy as np
                    import plotly.graph_objects as go  # type: ignore
                    vals = df_papers["Citations"].dropna().astype(int).tolist()
                    counts, edges = np.histogram(vals, bins=20)
                    fig = go.Figure(go.Bar(
                        x=[f"{int(edges[i])}-{int(edges[i+1])}" for i in range(len(counts))],
                        y=counts.tolist(),
                        marker_color="#1f77b4",
                    ))
                    fig.update_layout(
                        height=260,
                        margin=dict(l=40, r=20, t=20, b=60),
                        xaxis_title="Citation count range",
                        yaxis_title="Number of papers",
                        bargap=0.05,
                        xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                except Exception:
                    pass  # skip chart if anything fails

    # ── Tab 3: Research Report ───────────────────────────────────────────
    with tab_report:
        report_text = st.session_state.get("report", "")
        if not report_text:
            st.info("Run the analysis to generate the research report.")
        else:
            # Metadata bar
            stats = compute_stats(st.session_state["events"])
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Focus domain",      st.session_state.get("run_focus", "All domains"))
            mc2.metric("Tools queried",     stats["tools_called"])
            mc3.metric("Records retrieved", stats["records_retrieved"])
            mc4.metric("Generated",         datetime.now().strftime("%Y-%m-%d %H:%M"))
            st.divider()

            # Report body
            st.markdown(report_text)
            st.divider()

            # Download
            report_with_header = (
                "# 病理AI研究空白分析报告\n\n"
                f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"> 研究方向：{st.session_state.get('run_focus', 'All domains')}\n"
                f"> 知识图谱查询次数：{stats['tools_called']}\n\n"
                "---\n\n"
                + report_text
            )
            st.download_button(
                label="Download report (Markdown)",
                data=report_with_header.encode("utf-8"),
                file_name=f"gap_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
            )

    # ── Tab 4: Research Proposal ─────────────────────────────────────────
    with tab_proposal:
        st.subheader("Research Proposal Generator")
        st.caption(
            "Select a research gap identified in the report above, or type a custom description, "
            "then click Generate to produce a full research proposal (background, objectives, "
            "technical roadmap, clinical protocol, and innovation analysis)."
        )

        report_text_for_parse = st.session_state.get("report", "")
        parsed_titles = parse_gap_titles(report_text_for_parse) if report_text_for_parse else []

        gap_source = st.radio(
            "Gap source",
            options=["Select from report", "Enter manually"],
            horizontal=True,
            label_visibility="collapsed",
        )

        if gap_source == "Select from report":
            if not parsed_titles:
                st.info("Run a gap analysis first — identified gap titles will appear here for selection.")
                gap_input = ""
            else:
                gap_choice = st.selectbox(
                    "Select a research gap from the report",
                    options=parsed_titles,
                    key="gap_selectbox",
                )
                gap_input = gap_choice or ""
        else:
            gap_input = st.text_area(
                "Custom research gap description",
                height=120,
                placeholder="e.g. Foundation model-based prognosis prediction for non-small cell lung cancer — "
                            "185 papers exist on NSCLC but zero foundation model studies have been published.",
                key="gap_manual_input",
            )

        max_rounds = st.slider(
            "Max Generator × Critic refinement rounds",
            min_value=1, max_value=5, value=2,
            help="Each round: Generator drafts/revises → Critic evaluates with KG evidence → repeat.",
        )

        gen_btn = st.button(
            "Generate Research Proposal",
            type="primary",
            disabled=not gap_input.strip(),
            key="gen_proposal_btn",
        )

        # ── Run adversarial proposal generation ──────────────────────────
        if gen_btn and gap_input.strip():
            st.session_state["idea_events"]       = []
            st.session_state["proposal"]          = ""
            st.session_state["proposal_gap_text"] = gap_input.strip()
            st.session_state["proposal_rounds"]   = []

            idea_events: list[dict] = []
            round_containers: dict = {}   # round_num → st.status handle
            current_round = 0
            current_role  = "generator"
            gen_tool_step = 0
            critic_tool_step = 0

            outer_status = st.status(
                "Running Generator × Critic refinement loop …",
                expanded=True,
            )

            with outer_status:
                for event in stream_idea_agent(
                    gap_text=gap_input.strip(),
                    max_rounds=max_rounds,
                ):
                    idea_events.append(event)
                    st.session_state["idea_events"] = list(idea_events)
                    etype = event.get("type", "")

                    if etype == "round_start":
                        current_round = event["round"]
                        gen_tool_step = 0
                        critic_tool_step = 0
                        st.markdown(
                            f"#### Round {current_round} / {event['max_rounds']}"
                        )
                        st.caption("Generator is querying the knowledge graph …")

                    elif etype == "tool_call":
                        role = event.get("role", "generator")
                        current_role = role
                        tool_label = IDEA_TOOL_META.get(event["name"], event["name"])
                        role_tag = "[Generator]" if role == "generator" else "[Critic]"
                        args_d = event.get("args") or {}
                        args_str = ", ".join(f"{k}={v!r}" for k, v in args_d.items())
                        if role == "generator":
                            gen_tool_step += 1
                            st.write(f"  G-{gen_tool_step}. {tool_label}  ·  `{args_str}`")
                        else:
                            critic_tool_step += 1
                            st.write(f"  C-{critic_tool_step}. {role_tag} {tool_label}  ·  `{args_str}`")

                    elif etype == "tool_result":
                        data = (event.get("result") or {}).get("data", [])
                        st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;Retrieved {len(data)} records")

                    elif etype == "tool_error":
                        st.warning(
                            f"[{event.get('role','?')}] Tool error "
                            f"[{event.get('name')}]: {event.get('error')}"
                        )

                    elif etype == "draft":
                        rnd = event["round"]
                        st.success(
                            f"Draft v{rnd} generated — {len(event['content'])} characters"
                        )
                        rounds_list = st.session_state.get("proposal_rounds", [])
                        rounds_list.append({"round": rnd, "draft": event["content"], "feedback": None})
                        st.session_state["proposal_rounds"] = rounds_list
                        st.caption("Critic is evaluating …")

                    elif etype == "feedback":
                        rnd = event["round"]
                        score = event["score"]
                        accept = event["accept"]
                        dims = event.get("dimension_scores", {})
                        score_bar = " | ".join(
                            f"{k.replace('_',' ')}: {v:.1f}"
                            for k, v in dims.items()
                        ) if dims else ""
                        color = "green" if accept else ("orange" if score >= 6 else "red")
                        st.markdown(
                            f"Critic score: **:{color}[{score:.1f}/10]**  "
                            f"{'— Accepted' if accept else '— Revision required'}"
                        )
                        if score_bar:
                            st.caption(score_bar)
                        if event.get("revision_priority") and not accept:
                            st.info(f"Revision priority: {event['revision_priority']}")
                        # Save feedback into rounds list
                        rounds_list = st.session_state.get("proposal_rounds", [])
                        if rounds_list and rounds_list[-1]["round"] == rnd:
                            rounds_list[-1]["feedback"] = event
                            st.session_state["proposal_rounds"] = rounds_list

                    elif etype == "final":
                        st.session_state["proposal"] = event.get("content", "")
                        st.session_state["final_rounds"] = event.get("rounds", 1)
                        st.session_state["final_score"]  = event.get("final_score", 0.0)
                        outer_status.update(
                            label=(
                                f"Proposal finalised — "
                                f"{event.get('rounds', 1)} round(s), "
                                f"score {event.get('final_score', 0):.1f}/10"
                            ),
                            state="complete",
                            expanded=False,
                        )

                    elif etype == "error":
                        st.error(event.get("content"))
                        outer_status.update(label="Generation failed", state="error")

        # ── Display proposal ──────────────────────────────────────────────
        proposal_text = st.session_state.get("proposal", "")
        if proposal_text:
            st.divider()

            # Stats bar
            idea_evs      = st.session_state.get("idea_events", [])
            rounds_done   = st.session_state.get("final_rounds", 1)
            final_sc      = st.session_state.get("final_score", 0.0)
            n_tool_calls  = sum(1 for e in idea_evs if e.get("type") == "tool_call")
            n_gen_calls   = sum(1 for e in idea_evs if e.get("type") == "tool_call" and e.get("role") == "generator")
            n_critic_calls = sum(1 for e in idea_evs if e.get("type") == "tool_call" and e.get("role") == "critic")

            pm1, pm2, pm3, pm4 = st.columns(4)
            pm1.metric("Refinement rounds", rounds_done)
            pm2.metric("Final critic score", f"{final_sc:.1f}/10")
            pm3.metric("Generator KG queries", n_gen_calls)
            pm4.metric("Critic KG queries", n_critic_calls)
            st.divider()

            # Per-round iteration history
            rounds_list = st.session_state.get("proposal_rounds", [])
            if len(rounds_list) > 1:
                st.markdown("**Refinement history**")
                for r in rounds_list:
                    rnd = r["round"]
                    fb  = r.get("feedback") or {}
                    sc  = fb.get("score", None)
                    sc_str = f"{sc:.1f}/10" if sc is not None else "—"
                    with st.expander(
                        f"Round {rnd}  —  Critic score: {sc_str}  "
                        f"{'(accepted)' if fb.get('accept') else ''}",
                        expanded=False,
                    ):
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            st.markdown("**Draft**")
                            st.markdown(r.get("draft", "")[:3000] + ("…" if len(r.get("draft","")) > 3000 else ""))
                        with c2:
                            if fb:
                                st.markdown("**Critic feedback**")
                                dims = fb.get("dimension_scores", {})
                                if dims:
                                    dim_df = pd.DataFrame(
                                        [{"dimension": k.replace("_", " "), "score": v}
                                         for k, v in dims.items()]
                                    )
                                    safe_table(dim_df, height=None)
                                for strength in fb.get("strengths", []):
                                    st.success(strength)
                                for issue in fb.get("critical_issues", []):
                                    st.warning(
                                        f"**[{issue.get('section','')}]** {issue.get('issue','')}\n\n"
                                        f"Suggestion: {issue.get('suggestion','')}"
                                    )
                                if fb.get("revision_priority"):
                                    st.info(f"Revision priority: {fb['revision_priority']}")
                st.divider()

            # Final proposal body
            st.markdown("### Final Research Proposal")
            st.markdown(proposal_text)
            st.divider()

            # Full KG trace expander
            with st.expander(
                f"Full knowledge graph query trace  ({n_tool_calls} queries across all rounds)",
                expanded=False,
            ):
                current_rnd_label = None
                for i, ev in enumerate(idea_evs, 1):
                    if ev.get("type") == "round_start":
                        st.markdown(f"**--- Round {ev['round']} ---**")
                        current_rnd_label = ev["round"]
                    elif ev.get("type") == "tool_call":
                        role = ev.get("role", "generator")
                        tool_label = IDEA_TOOL_META.get(ev["name"], ev["name"])
                        args_d = ev.get("args") or {}
                        args_str = ", ".join(f"{k}={v!r}" for k, v in args_d.items())
                        st.markdown(
                            f"{'[Generator]' if role == 'generator' else '[Critic]'} "
                            f"**{tool_label}** — `{ev['name']}({args_str})`"
                        )
                    elif ev.get("type") == "tool_result":
                        data = (ev.get("result") or {}).get("data", [])
                        if data:
                            safe_table(pd.DataFrame(data[:8]), height=None)

            # Download — final proposal with iteration summary header
            rounds_summary = "\n".join(
                f"| {r['round']} | {(r.get('feedback') or {}).get('score', 0):.1f} | "
                f"{(r.get('feedback') or {}).get('revision_priority', '')[:60]} |"
                for r in rounds_list
            )
            proposal_with_header = (
                "# 病理AI研究方案（Generator x Critic 对抗式迭代生成）\n\n"
                f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"> 研究空白：{st.session_state.get('proposal_gap_text', '')}\n"
                f"> 迭代轮次：{rounds_done}\n"
                f"> 最终评分：{final_sc:.1f}/10\n"
                f"> KG查询总次数（Generator + Critic）：{n_tool_calls}\n\n"
                "## 迭代历史摘要\n\n"
                "| 轮次 | Critic评分 | 主要修订方向 |\n"
                "|------|-----------|------------|\n"
                + rounds_summary + "\n\n"
                "---\n\n"
                + proposal_text
            )
            st.download_button(
                label="Download final proposal (Markdown)",
                data=proposal_with_header.encode("utf-8"),
                file_name=f"proposal_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
                key="download_proposal",
            )

# ─────────────────────────────────────────────────────────────────────────────
# Landing state (no run yet)
# ─────────────────────────────────────────────────────────────────────────────
else:
    st.markdown("""
### Getting Started

Configure the analysis parameters in the sidebar and click **Run Analysis** to begin.
The agent will query the knowledge graph in real time, and each step will be shown as
it executes. When complete, results are organised across four tabs:

| Tab | Content |
|-----|---------|
| **Analysis Process** | Full trace of every KG query: function name, parameters, and retrieved data |
| **Referenced Literature** | All papers surfaced during analysis, with citation metadata |
| **Research Report** | Structured academic report with ranked, evidence-backed research directions |
| **Research Proposal** | Select a gap from the report to generate a full AI+pathology research proposal |

**Workflow:**

1. Set a focus domain (optional) and click **Run Analysis**
2. Review identified gaps in the **Research Report** tab
3. Switch to **Research Proposal**, select a gap, and click **Generate Research Proposal**
4. The proposal includes research background, objectives, technical roadmap, clinical protocol, and innovation analysis
""")

    # Show KG overview stats
    st.divider()
    st.markdown("**Current knowledge graph summary**")
    try:
        with get_conn() as conn:
            n_papers   = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            n_entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            n_triples  = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
            n_journals = conn.execute("SELECT COUNT(*) FROM journals").fetchone()[0]
        cols = st.columns(4)
        for col, (label, val) in zip(cols, [
            ("Papers", f"{n_papers:,}"),
            ("Entities", f"{n_entities:,}"),
            ("Triples", f"{n_triples:,}"),
            ("Journals", f"{n_journals:,}"),
        ]):
            col.metric(label, val)
    except Exception:
        st.caption("Knowledge graph not yet built. Run main.py first.")
