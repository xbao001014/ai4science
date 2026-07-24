"""
idea_agent.py — Adversarial Multi-Agent Research Proposal Generation

Adapted for fulltext_workflow (pathology AI / digital pathology, evidence-aware KG).
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime
from typing import Any, Generator

import config
from analysis.agent_utils import (
    best_assistant_content,
    bind_tools_with_focus,
    finalize_assistant_content,
    last_assistant_content,
    looks_like_proposal,
    parse_json_block,
    run_tool_agent,
)
from analysis.graph_tools import GRAPH_TOOLS, GRAPH_TOOL_SCHEMAS, init_gap_registry
from analysis.feasibility_tools import FEASIBILITY_TOOLS, FEASIBILITY_TOOL_SCHEMAS
from analysis.focus_filter import search_papers_for_topic, topic_keyword_pmid_in_clause
from analysis.difficulty_scoring import (
    DIFFICULTY_LEVELS,
    assess_implementation_difficulty,
    format_difficulty_markdown_header,
    load_public_datasets_for_keyword,
    load_supporting_papers_by_pmids,
    load_supporting_papers_for_keyword,
)
from feasibility.disease_mapper import map_gap_to_disease
from db.schema import get_conn, init_db

init_gap_registry()

# ── Fulltext SQL tools ───────────────────────────────────────────────────────

def _q(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def tool_related_papers(keyword: str) -> dict:
    rows, strategy = search_papers_for_topic(keyword, limit=config.TOOL_TOP_N)
    desc = f"Papers related to '{keyword}'"
    if strategy not in ("full_phrase", "empty", "no_match"):
        desc += f" (matched via {strategy})"
    return {"description": desc, "count": len(rows), "data": rows}


def tool_methods_for_topic(keyword: str) -> dict:
    pmid_fc = topic_keyword_pmid_in_clause("r_d.source_pmid", keyword)
    rows = _q(f"""
        SELECT e_m.name AS method,
               COUNT(DISTINCT r_m.source_pmid) AS paper_cnt,
               MIN(p.year) AS first_used,
               MAX(p.year) AS last_used
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_m ON r_m.source_pmid = p.pmid
        JOIN entities e_m ON r_m.object_id = e_m.id
        WHERE r_m.relation = 'APPLIES_METHOD' AND e_m.type = 'Method'
          {pmid_fc}
        GROUP BY e_m.id
        ORDER BY paper_cnt DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"AI methods in '{keyword}' research", "count": len(rows), "data": rows}


def tool_datasets_for_topic(keyword: str) -> dict:
    pmid_fc = topic_keyword_pmid_in_clause("r_d.source_pmid", keyword)
    rows = _q(f"""
        SELECT e_ds.name AS dataset,
               COALESCE(e_ds.access_class, 'unknown') AS access_class,
               COUNT(DISTINCT r_ds.source_pmid) AS used_by_papers
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_ds ON r_ds.source_pmid = p.pmid
        JOIN entities e_ds ON r_ds.object_id = e_ds.id
        WHERE r_ds.relation = 'USES_DATASET' AND e_ds.type = 'Dataset'
          {pmid_fc}
        GROUP BY e_ds.id
        ORDER BY
          CASE COALESCE(e_ds.access_class, 'unknown')
            WHEN 'public' THEN 0
            WHEN 'private' THEN 1
            ELSE 2
          END,
          used_by_papers DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {
        "description": (
            f"Datasets in '{keyword}' research "
            "(access_class: public|private|unknown; Fangxin is separate via feasibility tools)"
        ),
        "count": len(rows),
        "data": rows,
    }


def tool_metrics_for_topic(keyword: str) -> dict:
    pmid_fc = topic_keyword_pmid_in_clause("r_d.source_pmid", keyword)
    rows = _q(f"""
        SELECT e_mt.name AS metric, r_mt.metric_value,
               p.title, p.year, p.pmid,
               r_mt.evidence_section, r_mt.evidence_quote,
               r_mt.extraction_granularity
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_mt ON r_mt.source_pmid = p.pmid
        JOIN entities e_mt ON r_mt.object_id = e_mt.id
        WHERE r_mt.relation = 'ACHIEVES_METRIC' AND e_mt.type = 'Metric'
          {pmid_fc}
        ORDER BY p.year DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Metrics with evidence for '{keyword}'", "count": len(rows), "data": rows}


def tool_author_limitations_for_topic(keyword: str) -> dict:
    pmid_fc = topic_keyword_pmid_in_clause("r.source_pmid", keyword)
    rows = _q(f"""
        SELECT e.name AS limitation,
               r.source_pmid, r.evidence_section, r.evidence_quote,
               r.extraction_granularity
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        JOIN papers p ON r.source_pmid = p.pmid
        WHERE (r.relation = 'REPORTS_LIMITATION' OR e.type = 'Limitation')
          {pmid_fc}
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Author-stated limitations for '{keyword}'", "count": len(rows), "data": rows}


def tool_modality_coverage_for_topic(keyword: str) -> dict:
    pmid_fc = topic_keyword_pmid_in_clause("r_d.source_pmid", keyword)
    rows = _q(f"""
        SELECT e_m.name AS modality,
               COUNT(DISTINCT r_m.source_pmid) AS paper_cnt
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_m ON r_m.source_pmid = p.pmid
        JOIN entities e_m ON r_m.object_id = e_m.id
        WHERE r_m.relation = 'USES_MODALITY' AND e_m.type = 'Modality'
          {pmid_fc}
        GROUP BY e_m.id ORDER BY paper_cnt DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Imaging/clinical modality coverage for '{keyword}'", "count": len(rows), "data": rows}


def tool_recent_papers_for_topic(keyword: str) -> dict:
    rows, strategy = search_papers_for_topic(
        keyword,
        extra_where=f" AND p.year >= {config.SEARCH_YEAR_START}",
        limit=config.TOOL_TOP_N,
        select_columns=(
            "p.title, p.year, p.journal_name, p.study_type, "
            "p.abstract, p.pmid, p.full_text_status"
        ),
    )
    desc = f"Recent papers ({config.SEARCH_YEAR_START}+) for '{keyword}'"
    if strategy not in ("full_phrase", "empty", "no_match"):
        desc += f" (matched via {strategy})"
    return {"description": desc, "count": len(rows), "data": rows}


_SQL_IDEA_TOOLS: dict[str, Any] = {
    "related_papers": tool_related_papers,
    "methods_for_topic": tool_methods_for_topic,
    "datasets_for_topic": tool_datasets_for_topic,
    "metrics_for_topic": tool_metrics_for_topic,
    "author_limitations_for_topic": tool_author_limitations_for_topic,
    "modality_coverage_for_topic": tool_modality_coverage_for_topic,
    "recent_papers_for_topic": tool_recent_papers_for_topic,
}

IDEA_TOOLS: dict[str, Any] = {**_SQL_IDEA_TOOLS, **GRAPH_TOOLS, **FEASIBILITY_TOOLS}

_KEYWORD_SCHEMA = {
    "type": "string",
    "description": (
        "2-4 core terms preferred (e.g. 'WSI breast cancer grading'); "
        "long gap titles are auto-decomposed when no exact match."
    ),
}

_IDEA_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "related_papers",
        "description": "Retrieve papers related to a research gap keyword (multi-level match).",
        "parameters": {"type": "object", "properties": {"keyword": _KEYWORD_SCHEMA}, "required": ["keyword"]},
    }},
    {"type": "function", "function": {
        "name": "methods_for_topic",
        "description": "List AI methods used in research matching the keyword.",
        "parameters": {"type": "object", "properties": {"keyword": _KEYWORD_SCHEMA}, "required": ["keyword"]},
    }},
    {"type": "function", "function": {
        "name": "datasets_for_topic",
        "description": (
            "List datasets used in research matching the keyword, with access_class "
            "(public|private|unknown). Fangxin hospital data is assessed via feasibility tools, "
            "not this list."
        ),
        "parameters": {"type": "object", "properties": {"keyword": _KEYWORD_SCHEMA}, "required": ["keyword"]},
    }},
    {"type": "function", "function": {
        "name": "metrics_for_topic",
        "description": "Performance metrics with full-text evidence quotes.",
        "parameters": {"type": "object", "properties": {"keyword": _KEYWORD_SCHEMA}, "required": ["keyword"]},
    }},
    {"type": "function", "function": {
        "name": "author_limitations_for_topic",
        "description": "Author-stated limitations with evidence_section and evidence_quote.",
        "parameters": {"type": "object", "properties": {"keyword": _KEYWORD_SCHEMA}, "required": ["keyword"]},
    }},
    {"type": "function", "function": {
        "name": "modality_coverage_for_topic",
        "description": "Pathology modality coverage (WSI / H&E / IHC / cytology etc.) for the topic.",
        "parameters": {"type": "object", "properties": {"keyword": _KEYWORD_SCHEMA}, "required": ["keyword"]},
    }},
    {"type": "function", "function": {
        "name": "recent_papers_for_topic",
        "description": f"Recent papers since {config.SEARCH_YEAR_START} for the topic.",
        "parameters": {"type": "object", "properties": {"keyword": _KEYWORD_SCHEMA}, "required": ["keyword"]},
    }},
]

IDEA_TOOL_SCHEMAS: list[dict] = _IDEA_TOOL_SCHEMAS + GRAPH_TOOL_SCHEMAS + FEASIBILITY_TOOL_SCHEMAS

_GAP_ANCHOR_RULES = """\
[Anchored research gap — do not change the topic]
The user-selected research gap below must remain the sole focus of the proposal:
{gap_text}

Hard rules:
- Every tool keyword/focus must stay related to this gap's disease/task (do not switch diseases).
- Fangxin disease_id: {disease_id_rule}
- If Fangxin data are insufficient: state a "Data Integration Limitations" section; \
**do not** use an unrelated disease_id (e.g. BRCA-IDC for a non-breast topic) to inflate feasibility.
- Revision rounds may only deepen the same gap; never replace it with a new topic.
- Write the full proposal in **English** (section titles and body).
"""

_CRITIC_ANCHOR_EXTRA = """\
- Do not recommend switching to another disease or a new topic; if feasibility fails, \
require a data path for the original disease or document limitations.
- feasibility_assess disease_id must match the gap disease{disease_id_hint}; \
do not use unrelated API/mock IDs.
"""

_UNMAPPED_DISEASE_REASON = (
    "no confident mapping — call pathology_disease_catalog / text_disease_matches "
    "to resolve a disease_id matching THIS gap's disease; "
    "never invent or default to BRCA-IDC / GC-ADC / other unrelated codes"
)


def _short_tool_focus(gap_text: str) -> str:
    """Shorter focus string for graph tools (disease phrase)."""
    text = gap_text.strip()
    lower = text.lower()
    for phrase, label in (
        ("nasopharyngeal carcinoma", "Nasopharyngeal carcinoma"),
        ("nasopharyngeal cancer", "Nasopharyngeal carcinoma"),
        ("nasopharyngeal", "Nasopharyngeal carcinoma"),
        ("鼻咽癌", "Nasopharyngeal carcinoma"),
        ("bilateral breast cancer", "Breast Cancer"),
        ("multifocal breast cancer", "Breast Cancer"),
        ("breast cancer", "Breast Cancer"),
        ("breast", "Breast Cancer"),
        ("乳腺癌", "Breast Cancer"),
        ("乳腺", "Breast Cancer"),
        ("gastric", "Gastric cancer"),
        ("胃腺癌", "Gastric adenocarcinoma"),
        ("lung", "Lung cancer"),
        ("colorectal", "Colorectal cancer"),
        ("hepatocellular", "Hepatocellular carcinoma"),
    ):
        if phrase in lower or phrase in text:
            return label
    return text[:80]


def bind_idea_tools(tools: dict[str, Any], gap_text: str | None) -> dict[str, Any]:
    """Bind focus + keyword tool args to the anchored gap text."""
    if not gap_text or not gap_text.strip():
        return tools
    import inspect

    anchor = gap_text.strip()
    tool_focus = _short_tool_focus(anchor)
    bound = bind_tools_with_focus(tools, tool_focus)

    for name, fn in tools.items():
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            continue
        if "keyword" not in params:
            continue

        def _wrap_keyword(f: Any, keyword: str):
            def _wrapped(**kwargs: Any) -> Any:
                if not kwargs.get("keyword"):
                    kwargs["keyword"] = keyword
                return f(**kwargs)

            return _wrapped

        bound[name] = _wrap_keyword(fn, anchor[:200])

    return bound


def _gap_disease_hint(gap_text: str) -> tuple[str | None, str]:
    """Resolve Fangxin disease_id for prompts; never invent an unrelated default."""
    client = None
    try:
        from feasibility.client import get_pathology_client

        client = get_pathology_client()
    except Exception:
        client = None

    disease_id, conf, reason = map_gap_to_disease(gap_text, client=client)
    if disease_id:
        return disease_id, f"{reason} (confidence {conf:.2f})"
    return None, _UNMAPPED_DISEASE_REASON


def _disease_id_rule_text(disease_id: str | None, disease_reason: str) -> str:
    if disease_id:
        return (
            f"Prefer disease_id={disease_id} ({disease_reason}). "
            "It must match the gap disease; organ_system and related fields must fit that disease "
            "(breast topics: breast/mammary; do not misuse gynecological)."
        )
    return (
        f"No automatic mapping yet ({disease_reason}). "
        "First resolve a matching code via pathology_disease_catalog / text_disease_matches, "
        "then call feasibility_assess; never default to BRCA-IDC or other unrelated diseases."
    )


def _gap_anchor_block(gap_text: str) -> str:
    disease_id, disease_reason = _gap_disease_hint(gap_text)
    return _GAP_ANCHOR_RULES.format(
        gap_text=gap_text.strip(),
        disease_id_rule=_disease_id_rule_text(disease_id, disease_reason),
    )


def _system_with_gap_anchor(base: str, gap_text: str, *, role: str) -> str:
    if not gap_text or not gap_text.strip():
        return base
    extra = _gap_anchor_block(gap_text)
    if role == "critic":
        disease_id, _ = _gap_disease_hint(gap_text)
        hint = (
            f" (recommended: {disease_id})"
            if disease_id
            else " (must match the gap disease; ban unrelated default IDs)"
        )
        extra += _CRITIC_ANCHOR_EXTRA.format(disease_id_hint=hint)
    return base + "\n\n" + extra


GENERATOR_SYSTEM_PROMPT = """\
You are an expert pathology AI / digital pathology research-proposal designer. You combine \
histopathology/WSI/cytopathology (and optional genomics) with deep learning to produce clinically \
valuable, technically novel, and executable plans. Do not rely on CT/MRI radiomics — Fangxin \
feasibility covers pathology slides and labels only.

You operate in a Generator × Critic loop:
- Round 1: produce a complete initial proposal (v1) for the research gap.
- Later rounds: revise the proposal using Critic feedback.

Language:
- Write the **entire proposal in English** (titles and body).
- Tool arguments may use English disease/topic keywords matching the gap.

Tool-use rules:
- Call SQL tools + graph_* tools + Fangxin feasibility tools (at least 5 tools, including 1 graph_*).
- Prefer metrics_for_topic (with evidence_quote) and author_limitations_for_topic.
- **Must** call public_dataset_assess (V-03) once to list recommended public datasets for the gap.
- Call datasets_for_topic when discussing external data; respect access_class \
(public|private|unknown). Prefer V-03 recommended_public when labeling public datasets.
- Use pathology_disease_catalog / pathology_tasks_for_disease / text_disease_matches to confirm \
Fangxin data support (disease must match the gap).
- The final reply must be the **full proposal Markdown** (all sections). Do not stop after \
"let me call a tool" without writing the proposal.
- After tool calls finish, send one final message **without tool_calls** containing the full Markdown.

Data-source rules (Fangxin first):
- Primary cohort must be Fangxin pathology data when feasibility supports the gap.
- Public datasets (from public_dataset_assess recommended_public, or access_class=public) \
may be used for pretraining, external validation, baselines, or supplementary experiments.
- Every public dataset used in the plan must be explicitly labeled, e.g. \
`public dataset: Camelyon17`.
- Do **not** replace Fangxin with public data as the sole train/validation cohort when Fangxin \
is feasible.
- If Fangxin is insufficient: keep a "Data Integration Limitations" section; public data may \
carry more weight but must still be labeled, with rationale.

End the proposal with:
REVISION_NOTE: <≤50 words summarizing this version's changes; use "Initial version" for v1>

Also append a structured Fangxin integration section:

## 9. Fangxin Data Integration Parameters
- **disease_id**: <e.g. GC-ADC>
- **task_type**: <e.g. survival_prediction>
- **required_labels**: [<label fields>]
- **required_molecular_markers**: [<markers, or none>]
- **required_annotations**: [<pathology annotations>]
- **min_followup_months**: <integer or N/A>

Required structure:
## 1. Background and Rationale
## 2. Research Objectives (overall + 3–4 specific aims)
## 3. Research Content (3 modules, each substantive)
## 4. Technical Approach (specific AI architecture, not vague "deep learning")
## 5. Clinical Study Design (design, eligibility, sample size, ethics)
## 6. Innovations (clinical topic + AI architecture + translation)
## 7. Expected Outcomes and Impact
## 8. Timeline (2–3 year quarterly plan)

No emoji.
"""

CRITIC_SYSTEM_PROMPT = """\
You are a strict pathology AI / digital pathology peer reviewer (Critic Agent).
Flag proposals that depend on radiology imaging data unavailable in Fangxin.

Review rules:
- Call KG tools to verify data claims (at least 2 tools).
- **Must** call feasibility_assess (V-01) to check disease_id / task_type / label requirements.
- **Must** call public_dataset_assess (V-03) when the proposal cites public datasets or omits them.
- If feasibility_score < 0.5, technical_feasibility must be ≤ 5 and accept must be false.
- If feasibility_score >= 0.8 and available_cohort_size >= 500, you may note "Fangxin data feasible".
- Check evidence_quote consistency; note extracted-corpus size limits.
- Data sources: Fangxin must be primary when feasible; public datasets must be explicitly labeled \
(`public dataset: <name>`); reject or demand revision if Fangxin-feasible proposals omit Fangxin \
entirely or use unlabeled public data as the sole cohort.
- Score five dimensions (each /20, total /100, report overall /10): scientific rigor, technical \
feasibility, clinical value, innovation, completeness.
- Below 7 requires substantive revision; 8+ may accept.

Output strict JSON (```json ... ```). Field values (issues, suggestions, verification text) \
must be in **English**:
{
  "overall_score": <float, 0-10>,
  "accept": <bool>,
  "feasibility_score": <float, 0-1, from feasibility_assess>,
  "available_cohort_size": <int>,
  "dimension_scores": {
    "scientific_rigor": <float>, "technical_feasibility": <float>,
    "clinical_value": <float>, "innovation": <float>, "completeness": <float>
  },
  "strengths": [...],
  "critical_issues": [{"section": "...", "issue": "...", "evidence": "...", "suggestion": "..."}],
  "kg_verification": "...",
  "data_feasibility_verification": "...",
  "revision_priority": "..."
}

No emoji.
"""

ACCEPT_SCORE = 8.0

_FINALIZE_PROPOSAL_INSTRUCTION = """\
You have finished (or should have finished) KG tool queries. **Immediately** output the complete \
Markdown research proposal in **English**:
- Include all nine sections (1–8 + Fangxin Data Integration Parameters) and a final REVISION_NOTE line
- Do not call tools; do not write only a plan or "let me check…"
- Ground claims in prior tool results; note corpus limitations where data are missing
"""


def _ensure_proposal_draft(
    gen_messages: list[dict],
    *,
    gap_text: str,
    round_num: int,
    draft: str | None = None,
) -> tuple[str, bool]:
    """Return (draft, was_finalized)."""
    text = (draft if draft is not None else best_assistant_content(gen_messages)).strip()
    if looks_like_proposal(text):
        return text, False
    instruction = (
        f"{_FINALIZE_PROPOSAL_INSTRUCTION}\n\n"
        f"{_gap_anchor_block(gap_text)}\n\n"
        f"Output proposal v{round_num} in English."
    )
    finalized = finalize_assistant_content(gen_messages, instruction=instruction).strip()
    return (finalized or text), bool(finalized)


def _normalize_target_difficulty(target_difficulty: str | None) -> str:
    target = (target_difficulty or "moderate").strip().lower()
    return target if target in DIFFICULTY_LEVELS else "moderate"


_DIFFICULTY_STEERING_SUFFIX = (
    "Fangxin remains primary when feasible; label any public datasets. "
    "Assessed difficulty is computed by the host (do not invent it)."
)


def _difficulty_steering_text(target_difficulty: str) -> str:
    if target_difficulty == "easy":
        tier = (
            "Target implementation difficulty: easy. Prefer landable methods, established "
            "architectures, and evidence/data requirements achievable with the available cohort."
        )
    elif target_difficulty == "hard":
        tier = (
            "Target implementation difficulty: hard. Ambitious high-contribution methods are "
            "appropriate, while retaining Fangxin-first and explicitly labeled public-data rules."
        )
    else:
        tier = (
            "Target implementation difficulty: moderate. Balance methodological novelty with a "
            "realistic engineering and clinical-validation path."
        )
    return f"{tier} {_DIFFICULTY_STEERING_SUFFIX}"


def _prepend_difficulty_header(content: str, result: dict[str, Any]) -> str:
    if "> **Difficulty**" in content:
        return content
    header = format_difficulty_markdown_header(result).rstrip()
    return f"{header}\n\n{content.lstrip()}"


def stream_idea_agent(
    gap_text: str,
    gap_data: dict | None = None,
    max_rounds: int = 3,
    accept_score: float = ACCEPT_SCORE,
    target_difficulty: str = "moderate",
) -> Generator[dict, None, None]:
    target_difficulty = _normalize_target_difficulty(target_difficulty)
    yield {
        "type": "start",
        "gap_text": gap_text,
        "max_rounds": max_rounds,
        "target_difficulty": target_difficulty,
    }

    gap_context = ""
    disease_id, disease_reason = _gap_disease_hint(gap_text)
    if disease_id:
        gap_context = (
            f"\n\nFangxin disease mapping hint: disease_id={disease_id} ({disease_reason})"
        )
    else:
        gap_context = (
            "\n\nFangxin disease_id is not auto-mapped yet. "
            f"({disease_reason}) Resolve a disease_id matching this gap before feasibility assessment."
        )
    if gap_data:
        gap_context += (
            "\n\nKG analysis supporting data:\n"
            f"```json\n{json.dumps(gap_data, ensure_ascii=False, indent=2)[:2000]}\n```"
        )

    idea_tools = bind_idea_tools(IDEA_TOOLS, gap_text)
    anchor_block = _gap_anchor_block(gap_text)

    current_draft = ""
    last_feedback: dict = {}
    final_score = 0.0
    completed_rounds = 0
    feasibility_score: float | None = None
    available_cohort_size: int | None = None
    if gap_data:
        assess = gap_data.get("feasibility_assessment") or {}
        raw = assess.get("feasibility_score")
        if raw is not None and str(raw).strip() != "":
            try:
                feasibility_score = float(raw)
            except (TypeError, ValueError):
                pass
        raw_cohort = assess.get("available_cohort_size")
        if raw_cohort is not None and str(raw_cohort).strip() != "":
            try:
                available_cohort_size = int(raw_cohort)
            except (TypeError, ValueError):
                pass

    def _capture_feasibility_from_event(event: dict) -> None:
        nonlocal feasibility_score, available_cohort_size
        if event.get("type") != "tool_result":
            return
        if event.get("name") not in ("feasibility_assess", "tool_feasibility_assess"):
            return
        result = event.get("result")
        if not isinstance(result, dict):
            return
        raw_score = result.get("feasibility_score")
        if raw_score is not None and str(raw_score).strip() != "":
            try:
                feasibility_score = float(raw_score)
            except (TypeError, ValueError):
                pass
        raw_cohort = result.get("available_cohort_size")
        if raw_cohort is not None and str(raw_cohort).strip() != "":
            try:
                available_cohort_size = int(raw_cohort)
            except (TypeError, ValueError):
                pass

    def _assess_difficulty() -> dict[str, Any]:
        papers: list[dict[str, Any]] = []
        if gap_data:
            linked_papers = gap_data.get("papers")
            if isinstance(linked_papers, list):
                papers = [row for row in linked_papers if isinstance(row, dict)]
            if not papers:
                support_pmids = gap_data.get("support_pmids")
                if isinstance(support_pmids, list) and support_pmids:
                    papers = load_supporting_papers_by_pmids(support_pmids)
        if not papers:
            papers = load_supporting_papers_for_keyword(gap_text)
        public_datasets: list[str] = []
        if gap_data:
            pda = gap_data.get("public_dataset_assessment") or {}
            if isinstance(pda, dict):
                public_datasets = [
                    str(r["dataset"])
                    for r in (pda.get("recommended_public") or [])
                    if isinstance(r, dict) and r.get("dataset")
                ]
        if not public_datasets:
            public_datasets = load_public_datasets_for_keyword(gap_text)
        return assess_implementation_difficulty(
            target_difficulty=target_difficulty,
            papers=papers,
            feasibility_score=feasibility_score,
            available_cohort_size=available_cohort_size,
            public_datasets=public_datasets,
        )

    for round_num in range(1, max_rounds + 1):
        yield {"type": "round_start", "round": round_num, "max_rounds": max_rounds}

        if round_num == 1:
            gen_user = (
                "Draft a complete English pathology AI / digital pathology research proposal (v1) "
                "for the following gap:\n\n"
                f"{anchor_block}\n\n"
                f"**Research gap**:\n{gap_text}\n{gap_context}\n\n"
                f"{_difficulty_steering_text(target_difficulty)}\n\n"
                "Call at least 5 tools (including 1 graph_* and public_dataset_assess), "
                "then output the full English proposal."
            )
        else:
            issues_text = "\n".join(
                f"  [{item.get('section', '')}] {item.get('issue', '')}  "
                f"→ suggestion: {item.get('suggestion', '')}"
                for item in last_feedback.get("critical_issues", [])
            )
            gen_user = (
                f"{anchor_block}\n\n"
                f"**Anchored research gap (do not change topic)**:\n{gap_text}\n\n"
                f"Critic feedback (v{round_num - 1}):\n"
                f"**Score**: {last_feedback.get('overall_score', 0):.1f}/10\n"
                f"**Revision priority**: {last_feedback.get('revision_priority', '')}\n"
                f"**Issues**:\n{issues_text}\n"
                f"**KG verification**: {last_feedback.get('kg_verification', '')}\n\n"
                f"{_difficulty_steering_text(target_difficulty)}\n\n"
                f"Produce revised proposal v{round_num} in English for the same gap; "
                "do not change disease or topic; gather more tool evidence if needed."
            )

        gen_messages: list[dict] = [
            {
                "role": "system",
                "content": _system_with_gap_anchor(
                    GENERATOR_SYSTEM_PROMPT, gap_text, role="generator"
                ),
            },
            {"role": "user", "content": gen_user},
        ]
        agent_failed = False
        for event in run_tool_agent(
            messages=gen_messages,
            tools=idea_tools,
            tool_schemas=IDEA_TOOL_SCHEMAS,
            role="generator",
            max_iters=20,
            temperature=0.45,
        ):
            if event.get("type") == "error":
                agent_failed = True
                yield event
                break
            _capture_feasibility_from_event(event)
            yield event
        pre_draft = best_assistant_content(gen_messages)
        if not looks_like_proposal(pre_draft):
            yield {
                "type": "finalizing_draft",
                "round": round_num,
                "message": "Tool loop ended without a full proposal; requesting final Markdown…",
            }
        current_draft, _ = _ensure_proposal_draft(
            gen_messages, gap_text=gap_text, round_num=round_num, draft=pre_draft
        )
        if agent_failed and not current_draft:
            difficulty = _assess_difficulty()
            yield {"type": "difficulty_assessed", **difficulty}
            yield {
                "type": "final",
                "content": "",
                "rounds": completed_rounds,
                "final_score": final_score,
                "feasibility_score": feasibility_score,
                "available_cohort_size": available_cohort_size,
                "target_difficulty": difficulty["target_difficulty"],
                "assessed_difficulty": difficulty["assessed_difficulty"],
                "difficulty_delta": difficulty["difficulty_delta"],
                "difficulty_color": difficulty["color"],
                "difficulty_summary": difficulty["summary_line"],
                "q_coverage_low": difficulty["q_coverage_low"],
                "difficulty_breakdown": difficulty["breakdown"],
                "aborted": True,
            }
            return
        yield {"type": "draft", "round": round_num, "content": current_draft}

        if agent_failed:
            break

        feas_hint = (
            f"For Fangxin feasibility, prefer disease_id={disease_id} (must match the gap disease).\n"
            if disease_id
            else (
                "For Fangxin feasibility, use a disease_id that matches the gap disease "
                "(resolve via catalog/text_disease_matches first; never default to BRCA-IDC).\n"
            )
        )
        critic_user = (
            f"{anchor_block}\n\n"
            f"Review the following research proposal (v{round_num}) in English:\n\n"
            f"**Original gap (must not drift)**:\n{gap_text}\n\n"
            f"**Proposal**:\n{current_draft}\n\n"
            f"{feas_hint}"
            "First call feasibility_assess and public_dataset_assess, then at least one KG tool "
            "to verify key claims, "
            "then output the JSON review (English field values)."
        )
        critic_messages: list[dict] = [
            {
                "role": "system",
                "content": _system_with_gap_anchor(
                    CRITIC_SYSTEM_PROMPT, gap_text, role="critic"
                ),
            },
            {"role": "user", "content": critic_user},
        ]
        for event in run_tool_agent(
            messages=critic_messages,
            tools=idea_tools,
            tool_schemas=IDEA_TOOL_SCHEMAS,
            role="critic",
            max_iters=12,
            temperature=0.3,
        ):
            if event.get("type") == "error":
                agent_failed = True
                yield event
                break
            _capture_feasibility_from_event(event)
            yield event
        critic_text = last_assistant_content(critic_messages)
        if agent_failed and not critic_text:
            break
        last_feedback = parse_json_block(
            critic_text,
            fallback={
                "overall_score": 5.0,
                "accept": False,
                "dimension_scores": {},
                "strengths": [],
                "critical_issues": [],
                "kg_verification": "JSON parse failed",
                "revision_priority": critic_text[:500],
            },
        )
        final_score = float(last_feedback.get("overall_score") or 0.0)
        raw_feas = last_feedback.get("feasibility_score")
        if raw_feas is not None and str(raw_feas).strip() != "":
            try:
                feasibility_score = float(raw_feas)
            except (TypeError, ValueError):
                pass
        raw_cohort = last_feedback.get("available_cohort_size")
        if raw_cohort is not None and str(raw_cohort).strip() != "":
            try:
                available_cohort_size = int(raw_cohort)
            except (TypeError, ValueError):
                pass
        # Missing critic score must not block accept; only assessed low scores do.
        feas_for_accept = (
            feasibility_score if feasibility_score is not None else 1.0
        )
        accept = bool(last_feedback.get("accept", False)) or final_score >= accept_score
        if feas_for_accept < config.FEASIBILITY_SCORE_MARGINAL:
            accept = False
        completed_rounds = round_num

        yield {
            "type": "feedback",
            "round": round_num,
            "content": critic_text,
            "score": final_score,
            "accept": accept,
            "feasibility_score": feasibility_score,
            "dimension_scores": last_feedback.get("dimension_scores", {}),
            "strengths": last_feedback.get("strengths", []),
            "critical_issues": last_feedback.get("critical_issues", []),
            "revision_priority": last_feedback.get("revision_priority", ""),
        }

        if accept or round_num == max_rounds:
            break

    difficulty = _assess_difficulty()
    current_draft = _prepend_difficulty_header(current_draft, difficulty)
    yield {"type": "difficulty_assessed", **difficulty}
    yield {
        "type": "final",
        "content": current_draft,
        "rounds": completed_rounds,
        "final_score": final_score,
        "feasibility_score": feasibility_score,
        "available_cohort_size": available_cohort_size,
        "target_difficulty": difficulty["target_difficulty"],
        "assessed_difficulty": difficulty["assessed_difficulty"],
        "difficulty_delta": difficulty["difficulty_delta"],
        "difficulty_color": difficulty["color"],
        "difficulty_summary": difficulty["summary_line"],
        "q_coverage_low": difficulty["q_coverage_low"],
        "difficulty_breakdown": difficulty["breakdown"],
    }


def run_idea_agent(
    gap_text: str,
    gap_data: dict | None = None,
    max_rounds: int = 3,
    verbose: bool = False,
    target_difficulty: str = "moderate",
) -> tuple[str, dict]:
    print(f"\n{'='*60}")
    print("Research Proposal — Generator x Critic")
    print(f"  Gap: {gap_text[:80]}...")
    print(f"  Max rounds: {max_rounds}")
    print(f"{'='*60}\n")

    proposal = ""
    meta: dict = {
        "final_score": 0.0,
        "feasibility_score": None,
        "rounds": 0,
    }
    for event in stream_idea_agent(
        gap_text=gap_text,
        gap_data=gap_data,
        max_rounds=max_rounds,
        target_difficulty=target_difficulty,
    ):
        etype = event["type"]
        if etype == "round_start":
            print(f"\n--- Round {event['round']} / {event['max_rounds']} ---")
        elif etype == "tool_call":
            print(f"  [{event['role']}][tool] {event['name']}({event.get('args', {})})")
        elif etype == "tool_error":
            print(f"  [{event['role']}][error] {event['name']}: {event['error']}")
        elif etype == "thinking" and verbose:
            print(f"  [{event['role']}][thinking] {event['content'][:100]}...")
        elif etype == "draft":
            print(f"\n  [draft v{event['round']}] {len(event['content'])} chars")
        elif etype == "feedback":
            print(f"\n  [critic] score={event['score']:.1f}/10  accept={event['accept']}")
            if event.get("feasibility_score") is not None:
                meta["feasibility_score"] = event["feasibility_score"]
        elif etype == "final":
            proposal = event["content"]
            meta["final_score"] = float(event.get("final_score") or 0.0)
            meta["rounds"] = int(event.get("rounds") or 0)
            if event.get("feasibility_score") is not None:
                meta["feasibility_score"] = event["feasibility_score"]
            print(
                f"\nFinalised after {event['rounds']} round(s), "
                f"score {event['final_score']:.1f}/10\n"
            )
        elif etype == "error":
            print(f"\n[warning] {event['content']}")
    return proposal, meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Research Proposal Agent")
    parser.add_argument("--gap", "-g", default=None)
    parser.add_argument("--interactive", "-i", action="store_true")
    parser.add_argument("--rounds", "-r", type=int, default=3)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    init_db()

    if args.interactive:
        print("Enter research gap description (end with Ctrl+Z / Ctrl+D):")
        gap_text = sys.stdin.read().strip()
    elif args.gap:
        gap_text = args.gap
    else:
        parser.print_help()
        sys.exit(1)

    proposal, _meta = run_idea_agent(gap_text=gap_text, max_rounds=args.rounds, verbose=args.verbose)

    print("\n" + "=" * 60)
    print(proposal[:2000] + ("..." if len(proposal) > 2000 else ""))
    print("=" * 60)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            header = textwrap.dedent(f"""\
                # Pathomics/Radiomics Research Proposal

                > Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
                > Gap: {gap_text[:100]}
                > Tool: idea_agent.py (Generator x Critic)

                ---

            """)
            f.write(header + proposal)
        print(f"\nProposal saved: {args.output}")
