"""User-facing labels for Gap Debate roles (Optimist / Skeptic / Moderator)."""
from __future__ import annotations

# Internal agent keys → plain English labels (default UI language)
ROLE_LABELS: dict[str, str] = {
    "optimist": "Opportunity Scout",
    "skeptic": "Evidence Reviewer",
    "moderator": "Final Synthesizer",
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    "optimist": (
        "Mines the literature knowledge graph for promising research directions "
        "and outputs a candidate gap list."
    ),
    "skeptic": (
        "Independently verifies candidates, separates true gaps from false positives "
        "and weak evidence, and assigns an overall confidence score."
    ),
    "moderator": (
        "Merges both perspectives, adds Fangxin data support, and produces the "
        "final Gap Report—or sends the debate to another revision round."
    ),
}

DEBATE_FLOW_HELP = """
**How one debate round works**

1. **Opportunity Scout** — query the KG and propose Top-N candidate gaps  
2. **Evidence Reviewer** — re-query independently, score and label true / false / weak gaps  
3. **Final Synthesizer** — merge opinions into the final report (or request revision)

**Confidence (0–10)** comes from the Evidence Reviewer’s overall score for the batch.
At **≥7.5**, the Final Synthesizer is more likely to publish the final report directly.
"""

DEBATE_ROLE_CARDS = [
    ("Opportunity Scout", "Idea scout", "Find directions & candidates", "#2ca02c"),
    ("Evidence Reviewer", "Peer reviewer", "Verify claims & flag false gaps", "#d62728"),
    ("Final Synthesizer", "Lead PI", "Prioritize & write conclusions", "#1f77b4"),
]

# Report body: technical role names → plain English (longest matches first)
_REPORT_REPLACEMENTS: list[tuple[str, str]] = [
    ("Optimist Agent", "Opportunity Scout"),
    ("Skeptic Agent", "Evidence Reviewer"),
    ("Moderator Agent", "Final Synthesizer"),
    ("Optimist vs Skeptic", "Opportunity Scout vs Evidence Reviewer"),
    ("Optimist proposal / Skeptic verification", "Opportunity Scout proposal / Evidence Reviewer conclusion"),
    ("Optimist 提出 / Skeptic 验证状态", "Opportunity Scout proposal / Evidence Reviewer conclusion"),
    ("Opportunity Scout 提出 / Evidence Reviewer 结论", "Opportunity Scout proposal / Evidence Reviewer conclusion"),
    ("三方评审共识", "Review consensus"),
    ("评审过程摘要", "Review process summary"),
    ("评审共识度", "Review consensus score"),
    ("Debate 记录摘要", "Review process summary"),
    ("Debate 共识度", "Review consensus score"),
    ("Debate 共识", "Review consensus"),
    ("Optimist 总结", "Opportunity Scout summary"),
    ("Optimist 提出", "Opportunity Scout proposal"),
    ("Skeptic 验证状态", "Evidence Reviewer conclusion"),
    ("Optimist", "Opportunity Scout"),
    ("Skeptic", "Evidence Reviewer"),
    ("Moderator", "Final Synthesizer"),
]


def role_display(role: str) -> str:
    """Map internal role key to user-facing English label."""
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
