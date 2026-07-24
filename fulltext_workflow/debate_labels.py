"""User-facing labels for Gap Debate roles (Optimist / Skeptic / Moderator)."""
from __future__ import annotations

# Internal agent keys → Chinese UI labels
ROLE_LABELS: dict[str, str] = {
    "optimist": "机会侦察",
    "skeptic": "证据审阅",
    "moderator": "综合终审",
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    "optimist": (
        "从文献知识图谱中挖掘有潜力的研究方向，输出候选研究空白列表。"
    ),
    "skeptic": (
        "独立核验候选，区分真实空白、伪阳性与弱证据，并给出整体置信度评分。"
    ),
    "moderator": (
        "综合双方观点，补充方信数据支撑，产出最终研究空白报告，"
        "或要求进入下一轮修订。"
    ),
}

DEBATE_FLOW_HELP = """
**一轮辩论如何进行**

1. **机会侦察** — 查询知识图谱，提出 Top-N 候选研究空白  
2. **证据审阅** — 独立再查证，评分并标注真/伪/弱空白  
3. **综合终审** — 合并意见写入最终报告（或要求修订）

**置信度（0–10）** 来自证据审阅对本批候选的整体评分。  
达到 **≥7.5** 时，综合终审更可能直接发布最终报告。
"""

DEBATE_ROLE_CARDS = [
    ("机会侦察", "方向挖掘", "发现方向与候选空白", "#2ca02c"),
    ("证据审阅", "同行复核", "核验主张并标出伪空白", "#d62728"),
    ("综合终审", "课题主持", "排序优先级并撰写结论", "#1f77b4"),
]

# Report body: technical / English role names → Chinese UI labels (longest matches first)
_REPORT_REPLACEMENTS: list[tuple[str, str]] = [
    ("Optimist Agent", "机会侦察"),
    ("Skeptic Agent", "证据审阅"),
    ("Moderator Agent", "综合终审"),
    ("Optimist vs Skeptic", "机会侦察 vs 证据审阅"),
    ("Optimist proposal / Skeptic verification", "机会侦察提案 / 证据审阅结论"),
    ("Optimist 提出 / Skeptic 验证状态", "机会侦察提案 / 证据审阅结论"),
    ("Opportunity Scout 提出 / Evidence Reviewer 结论", "机会侦察提案 / 证据审阅结论"),
    ("Opportunity Scout proposal / Evidence Reviewer conclusion", "机会侦察提案 / 证据审阅结论"),
    ("Opportunity Scout vs Evidence Reviewer", "机会侦察 vs 证据审阅"),
    ("Final Synthesizer", "综合终审"),
    ("Evidence Reviewer", "证据审阅"),
    ("Opportunity Scout", "机会侦察"),
    ("三方评审共识", "评审共识"),
    ("评审过程摘要", "评审过程摘要"),
    ("评审共识度", "评审共识度"),
    ("Debate 记录摘要", "评审过程摘要"),
    ("Debate 共识度", "评审共识度"),
    ("Debate 共识", "评审共识"),
    ("Review consensus score", "评审共识度"),
    ("Review process summary", "评审过程摘要"),
    ("Review consensus", "评审共识"),
    ("Optimist 总结", "机会侦察总结"),
    ("Optimist 提出", "机会侦察提案"),
    ("Skeptic 验证状态", "证据审阅结论"),
    ("Optimist", "机会侦察"),
    ("Skeptic", "证据审阅"),
    ("Moderator", "综合终审"),
]


def role_display(role: str) -> str:
    """Map internal role key to user-facing Chinese label."""
    key = (role or "").lower().strip()
    return ROLE_LABELS.get(key, role)


def humanize_debate_report(text: str) -> str:
    """Replace agent role names in Gap Report markdown for UI display."""
    if not text:
        return text
    out = text
    for old, new in _REPORT_REPLACEMENTS:
        out = out.replace(old, new)
    return out
