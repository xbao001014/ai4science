"""Plotly charts for the gap-debate workflow (Streamlit gap_ui)."""
from __future__ import annotations

import re
from typing import Any, Callable

import pandas as pd

try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    px = None  # type: ignore[assignment]
    go = None  # type: ignore[assignment]

from analysis.agent_utils import parse_json_block
from pipeline_utils import parse_gap_titles

_GAP_HEADING_RE = re.compile(
    r"(?:###\s*)?(?:候选空白|研究空白|Research\s+Gap|Gap)\s*\d+",
    re.IGNORECASE,
)
_NUMBERED_GAP_RE = re.compile(
    r"^\s*(?:\d+[\.\)、]|\*\*\d+[\.\)、])\s*(.+)",
    re.MULTILINE,
)

_LIT_GAP_SCORE = {"unexplored": 0, "minimal": 1}
_DATA_SUPPORT_SCORE = {"low": 0, "medium": 1, "high": 2}


def plotly_available() -> bool:
    return HAS_PLOTLY


def _record_count(result: dict) -> int:
    if not isinstance(result, dict):
        return 0
    for key in ("data", "gaps", "results_backed", "all_metrics"):
        items = result.get(key)
        if isinstance(items, list):
            return len(items)
    return 0


def count_scout_candidates(content: str) -> int:
    """Heuristic count of Opportunity Scout gap proposals in markdown."""
    if not content or not content.strip():
        return 0
    headings = _GAP_HEADING_RE.findall(content)
    if headings:
        return len(headings)
    numbered = [
        m.group(1).strip()
        for m in _NUMBERED_GAP_RE.finditer(content)
        if 5 < len(m.group(1).strip()) < 200
    ]
    if numbered:
        return len(numbered)
    bullets = re.findall(r"^[-*]\s+.{10,}", content, re.MULTILINE)
    return max(len(bullets), 1) if bullets else 0


def extract_skeptic_breakdown(events: list[dict]) -> dict[str, int]:
    """Latest Evidence Reviewer verdict counts from debate events."""
    breakdown = {"verified": 0, "false": 0, "weak": 0}
    for ev in events:
        if ev.get("type") != "skeptic_review":
            continue
        review = parse_json_block(ev.get("content", ""), fallback={})
        breakdown["verified"] = len(review.get("verified_gaps") or [])
        breakdown["false"] = len(review.get("false_gaps") or [])
        breakdown["weak"] = len(review.get("weak_evidence_gaps") or [])
    return breakdown


def debate_funnel_stats(events: list[dict], report_text: str = "") -> dict[str, int]:
    """Aggregate debate-stage counts for funnel visualization."""
    scout = 0
    for ev in events:
        if ev.get("type") == "optimist_proposal":
            scout = max(scout, count_scout_candidates(ev.get("content", "")))

    skeptic = extract_skeptic_breakdown(events)
    final = len(parse_gap_titles(report_text)) if report_text else 0

    if scout == 0:
        scout = skeptic["verified"] + skeptic["false"] + skeptic["weak"]
    if scout == 0 and final:
        scout = final

    return {
        "scout_candidates": scout,
        "verified": skeptic["verified"],
        "weak_evidence": skeptic["weak"],
        "false_gaps": skeptic["false"],
        "final_gaps": final,
    }


def build_debate_funnel_figure(stats: dict[str, int]) -> Any:
    """Horizontal bar chart showing gap filtering through debate stages."""
    if not HAS_PLOTLY:
        return None

    stages = [
        ("Opportunity Scout", stats.get("scout_candidates", 0), "#2ca02c"),
        ("Verified", stats.get("verified", 0), "#1f77b4"),
        ("Weak evidence", stats.get("weak_evidence", 0), "#ff7f0e"),
        ("False gaps", stats.get("false_gaps", 0), "#d62728"),
        ("Final report", stats.get("final_gaps", 0), "#9467bd"),
    ]
    labels = [s[0] for s in stages]
    values = [s[1] for s in stages]
    colors = [s[2] for s in stages]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=colors,
            text=values,
            textposition="outside",
        )
    )
    fig.update_layout(
        title="Gap Debate Funnel",
        xaxis_title="Count",
        yaxis=dict(autorange="reversed"),
        height=320,
        margin=dict(l=120, r=40, t=50, b=40),
        showlegend=False,
    )
    return fig


def _latest_tool_result(events: list[dict], tool_name: str) -> dict | None:
    result = None
    for ev in events:
        if ev.get("type") == "tool_result" and ev.get("name") == tool_name:
            result = ev.get("result")
    return result


def combo_gap_rows(events: list[dict]) -> list[dict]:
    """Method × disease gap rows from debate tool results."""
    raw = _latest_tool_result(events, "method_disease_combo_gap")
    if raw and isinstance(raw.get("gaps"), list):
        return raw["gaps"]
    return []


def build_method_disease_heatmap(
    gaps: list[dict],
    *,
    focus: str | None = None,
) -> Any:
    """Heatmap of literature coverage (paper_cnt) per method–disease pair."""
    if not HAS_PLOTLY:
        return None
    if not gaps:
        return None

    df = pd.DataFrame(gaps)
    if df.empty or "method" not in df.columns or "disease" not in df.columns:
        return None

    pivot = df.pivot_table(
        index="method",
        columns="disease",
        values="paper_cnt",
        aggfunc="max",
        fill_value=0,
    )
    pivot = pivot.sort_index(axis=0).sort_index(axis=1)

    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale=[
                [0.0, "#d62728"],
                [0.15, "#ff9896"],
                [0.35, "#ffbb78"],
                [1.0, "#98df8a"],
            ],
            colorbar=dict(title="Papers"),
            hovertemplate=(
                "Method: %{y}<br>Disease: %{x}<br>Papers: %{z}<extra></extra>"
            ),
        )
    )
    title = "Method × Disease Literature Coverage"
    if focus:
        title += f" (focus: {focus})"
    fig.update_layout(
        title=title,
        xaxis_title="Disease",
        yaxis_title="Method",
        height=max(360, 28 * len(pivot.index) + 120),
        margin=dict(l=140, r=40, t=60, b=120),
        xaxis=dict(tickangle=-35),
    )
    return fig


def cross_matrix_rows(events: list[dict]) -> list[dict]:
    """Literature × data cross-matrix rows from debate events."""
    raw = _latest_tool_result(events, "literature_data_cross_matrix")
    if raw and isinstance(raw.get("data"), list):
        return raw["data"]
    return []


def build_lit_data_scatter(rows: list[dict]) -> Any:
    """Quadrant scatter: cohort size vs literature gap strength."""
    if not HAS_PLOTLY or not rows:
        return None

    df = pd.DataFrame(rows)
    needed = {"cohort_size", "literature_paper_cnt", "cross_priority_score"}
    if not needed.issubset(df.columns):
        return None

    df = df.copy()
    for col, default in (("literature_gap", ""), ("data_support", "unknown")):
        if col in df.columns:
            df[col] = df[col].fillna(default)
        else:
            df[col] = default
    df["label"] = df.apply(
        lambda r: f"{r.get('method', '?')} · {r.get('disease', '?')}", axis=1
    )

    fig = px.scatter(
        df,
        x="cohort_size",
        y="literature_paper_cnt",
        size="cross_priority_score",
        color="data_support",
        hover_name="label",
        color_discrete_map={
            "high": "#2ca02c",
            "medium": "#ff7f0e",
            "low": "#d62728",
            "unknown": "#9e9e9e",
        },
        labels={
            "cohort_size": "Fangxin cohort size",
            "literature_paper_cnt": "Literature papers (lower = larger gap)",
            "data_support": "Data support",
            "cross_priority_score": "Priority score",
        },
        title="Literature Gap × Data Support (priority = bubble size)",
    )

    if len(df) >= 2:
        x_med = float(df["cohort_size"].median())
        y_med = float(df["literature_paper_cnt"].median())
        fig.add_vline(x=x_med, line_dash="dot", line_color="#aaa")
        fig.add_hline(y=y_med, line_dash="dot", line_color="#aaa")

    fig.update_layout(
        height=420,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def tool_category_stats(
    events: list[dict],
    tool_meta: dict[str, dict],
) -> list[dict[str, Any]]:
    """Aggregate tool-result record counts by category and tool name."""
    counts: dict[tuple[str, str], int] = {}
    for ev in events:
        if ev.get("type") != "tool_result":
            continue
        name = ev.get("name", "")
        meta = tool_meta.get(name, {})
        category = meta.get("category", "Other")
        label = meta.get("label", name)
        n = _record_count(ev.get("result", {}))
        if n <= 0:
            n = 1
        key = (category, label)
        counts[key] = counts.get(key, 0) + n

    rows = [
        {"category": cat, "tool": tool, "records": n}
        for (cat, tool), n in sorted(counts.items(), key=lambda x: -x[1])
    ]
    return rows


def build_tool_treemap(
    stats_rows: list[dict],
    category_colors: dict[str, str] | None = None,
) -> Any:
    """Treemap of evidence retrieved per tool during debate."""
    if not HAS_PLOTLY or not stats_rows:
        return None

    df = pd.DataFrame(stats_rows)
    color_map = category_colors or {}

    fig = px.treemap(
        df,
        path=["category", "tool"],
        values="records",
        color="category",
        color_discrete_map=color_map,
        title="Evidence Retrieved by Tool (debate session)",
    )
    fig.update_layout(height=400, margin=dict(l=10, r=10, t=50, b=10))
    fig.update_traces(textinfo="label+value")
    return fig


def build_subtype_bar(distribution: list[dict], *, top_n: int = 8) -> Any:
    if not HAS_PLOTLY or not distribution:
        return None
    rows = []
    for item in distribution:
        name = item.get("subtype_name_zh") or item.get("name") or "?"
        count = item.get("patient_count", item.get("count", 0)) or 0
        rows.append({"label": str(name), "count": int(count)})
    rows = sorted(rows, key=lambda r: -r["count"])[:top_n]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    fig = px.bar(df, x="count", y="label", orientation="h", title="Subtype distribution (top)")
    fig.update_layout(height=max(280, 28 * len(rows) + 80), yaxis=dict(autorange="reversed"), margin=dict(l=120, r=20, t=50, b=40))
    return fig


def build_molecular_bar(positivity: list[dict], *, top_n: int = 8) -> Any:
    if not HAS_PLOTLY or not positivity:
        return None
    rows = []
    for item in positivity:
        name = item.get("marker") or item.get("name") or "?"
        val = item.get("positivity_rate", item.get("rate", item.get("patient_count", 0))) or 0
        rows.append({"label": str(name), "value": float(val)})
    rows = sorted(rows, key=lambda r: -r["value"])[:top_n]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    fig = px.bar(df, x="value", y="label", orientation="h", title="Molecular positivity (top)")
    fig.update_layout(height=max(280, 28 * len(rows) + 80), yaxis=dict(autorange="reversed"), margin=dict(l=120, r=20, t=50, b=40))
    return fig


def build_gap_viz_bundle(
    events: list[dict],
    *,
    report_text: str = "",
    focus: str | None = None,
    tool_meta: dict[str, dict],
    category_colors: dict[str, str] | None = None,
    combo_fetcher: Callable[[], list[dict]] | None = None,
    cross_fetcher: Callable[[], list[dict]] | None = None,
) -> dict[str, Any]:
    """Build all MVP gap visualizations from session state."""
    funnel = debate_funnel_stats(events, report_text)
    combo = combo_gap_rows(events)
    if not combo and combo_fetcher:
        combo = combo_fetcher()

    cross = cross_matrix_rows(events)
    if not cross and cross_fetcher:
        cross = cross_fetcher()

    tools = tool_category_stats(events, tool_meta)

    return {
        "funnel_stats": funnel,
        "funnel_fig": build_debate_funnel_figure(funnel),
        "combo_fig": build_method_disease_heatmap(combo, focus=focus),
        "combo_rows": combo,
        "cross_fig": build_lit_data_scatter(cross),
        "cross_rows": cross,
        "treemap_fig": build_tool_treemap(tools, category_colors),
        "tool_stats": tools,
    }
