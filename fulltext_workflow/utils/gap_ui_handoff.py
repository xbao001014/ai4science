"""Gap UI P2 handoffs: debate summary + opportunity → proposal / V-01."""
from __future__ import annotations

from typing import Any, MutableMapping

from viz.gap_viz import debate_funnel_stats

DATA_FEAS_VIEW_KEY = "data_feas_view"
DATA_VIEW_GAP_CHECK = "从空白快速核查"
DATA_VIEW_V01 = "V-01 可行性"
DATA_VIEW_ADVANCED = "高级 API"
DATA_FEAS_VIEWS = (DATA_VIEW_GAP_CHECK, DATA_VIEW_V01, DATA_VIEW_ADVANCED)

# Streamlit widget key for V-01 disease selectbox in gap_ui.
V01_DISEASE_KEY = "v01_disease"


def debate_summary_metrics(
    events: list[dict],
    report_text: str = "",
    *,
    debate_confidence: float = 0.0,
) -> dict[str, Any]:
    """Top-of-debate-tab summary: funnel counts + confidence + tool steps."""
    funnel = debate_funnel_stats(events, report_text or "")
    tool_steps = sum(1 for e in events if e.get("type") == "tool_call")
    return {
        **funnel,
        "confidence": float(debate_confidence or 0.0),
        "tool_steps": tool_steps,
    }


def opportunity_proposal_text(row: dict[str, Any]) -> str:
    """Compose a manual gap blurb for the proposal generator."""
    method = str(row.get("method") or "?").strip() or "?"
    disease = str(row.get("disease") or "?").strip() or "?"
    lines = [f"{method} × {disease}"]
    bridge = str(row.get("bridge_task") or "").strip()
    if bridge:
        lines.append(f"已验证任务桥梁：{bridge}")
    gap = str(row.get("gap") or "").strip()
    if gap:
        lines.append(f"文献空白：{gap}")
    support = str(row.get("support_diseases") or "").strip()
    if support:
        lines.append(f"支持病种：{support}")
    return "\n".join(lines)


def apply_opportunity_proposal_handoff(
    state: MutableMapping[str, Any],
    row: dict[str, Any],
) -> None:
    """Seed proposal tab to manual input with opportunity text."""
    state["gap_source"] = "手动输入"
    state["gap_manual"] = opportunity_proposal_text(row)


def apply_opportunity_v01_handoff(
    state: MutableMapping[str, Any],
    row: dict[str, Any],
) -> None:
    """Open data-feasibility on V-01 with disease preselected when mapped."""
    state[DATA_FEAS_VIEW_KEY] = DATA_VIEW_V01
    did = str(row.get("disease_id") or "").strip()
    if did:
        state[V01_DISEASE_KEY] = did
