"""Recommended user journey helpers for Gap UI (pure, Streamlit-free)."""
from __future__ import annotations

from typing import Any

# After a successful blank debate, land on the deliverable tab.
POST_DEBATE_TAB_SLUG = "gap-report"

# Ordered path shown to end users (slug may be a synthetic step like "focus").
JOURNEY_STEPS: list[tuple[str, str]] = [
    ("weekly-hotspot", "浏览热点"),
    ("focus", "设焦点"),
    ("debate-process", "运行辩论"),
    ("gap-report", "看报告"),
    ("visualization", "查看方信数据"),
    ("research-proposal", "生成提案"),
]


def journey_status(
    *,
    has_focus: bool,
    has_report: bool,
    has_proposal: bool,
) -> dict[str, Any]:
    """Derive where the user is on the recommended path."""
    if has_proposal and has_report:
        return {
            "current_slug": "research-proposal",
            "current_label": "生成提案",
            "current_index": 5,
            "complete": True,
            "has_focus": has_focus,
            "has_report": has_report,
            "has_proposal": has_proposal,
        }
    if has_report:
        return {
            "current_slug": "gap-report",
            "current_label": "看报告",
            "current_index": 3,
            "complete": False,
            "has_focus": has_focus,
            "has_report": has_report,
            "has_proposal": has_proposal,
        }
    if has_focus:
        return {
            "current_slug": "debate-process",
            "current_label": "运行辩论",
            "current_index": 2,
            "complete": False,
            "has_focus": has_focus,
            "has_report": has_report,
            "has_proposal": has_proposal,
        }
    return {
        "current_slug": "focus",
        "current_label": "设焦点",
        "current_index": 1,
        "complete": False,
        "has_focus": has_focus,
        "has_report": has_report,
        "has_proposal": has_proposal,
    }


def next_step_hint(status: dict[str, Any]) -> str:
    """One-line next action for captions / callouts."""
    if status.get("complete"):
        return "流程已完成 — 可下载报告与提案，或换焦点再跑一轮。"
    slug = status.get("current_slug")
    if slug == "focus":
        return "下一步：在侧栏填写研究焦点（也可先打开「每周热点」浏览）。"
    if slug == "debate-process":
        return "下一步：点击侧栏「运行空白辩论」。"
    if slug == "gap-report":
        return "下一步：到「可视化」查看方信队列概况，或打开「研究提案」生成方案。"
    if slug == "weekly-hotspot":
        return "下一步：在侧栏填写研究焦点。"
    if slug == "visualization":
        return "下一步：打开「研究提案」生成方案。"
    if slug == "research-proposal":
        return "下一步：生成并下载研究提案。"
    return "按推荐路径继续。"


def format_journey_line(status: dict[str, Any]) -> str:
    """Render path with the current step marked."""
    cur = int(status.get("current_index", 0))
    parts: list[str] = []
    for i, (_slug, label) in enumerate(JOURNEY_STEPS):
        if status.get("complete") and i == len(JOURNEY_STEPS) - 1:
            parts.append(f"**{label}**")
        elif i == cur and not status.get("complete"):
            parts.append(f"**{label}**")
        else:
            parts.append(label)
    return "推荐路径：" + " → ".join(parts)


def journey_action_buttons(status: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Optional quick-nav buttons: (tab_slug_or_empty, button_label).
    Empty slug means sidebar focus (no tab switch).
    """
    if status.get("complete"):
        return [
            ("gap-report", "查看报告"),
            ("research-proposal", "查看提案"),
        ]
    slug = status.get("current_slug")
    if slug == "focus":
        return [
            ("weekly-hotspot", "去每周热点"),
            ("", "请先设焦点"),
        ]
    if slug == "debate-process":
        return [
            ("weekly-hotspot", "去每周热点"),
            ("debate-process", "看辩论说明"),
        ]
    if slug == "gap-report":
        return [
            ("visualization", "查看方信数据"),
            ("research-proposal", "生成提案"),
            ("debate-process", "看辩论过程"),
        ]
    return []
