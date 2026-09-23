"""
gap_agent.py — Debate Multi-Agent Gap Identification (Scheme C)

Architecture
------------
  Debate Round 1 … N:
    Optimist Agent   →  KG tools  →  candidate gap proposals
    Skeptic Agent    →  KG tools  →  structured cross-validation JSON
    Moderator Agent  →  optional tools  →  final report OR debate feedback

Event stream (yielded dicts):
  start / debate_round_start / phase_start
  tool_call / tool_result / tool_error / thinking  (with role)
  optimist_proposal / skeptic_review / debate_feedback
  final / error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from datetime import datetime
from typing import Any, Generator

import config
from analysis.agent_utils import (
    bind_tools_with_focus,
    last_assistant_content,
    parse_json_block,
    run_tool_agent,
    select_tool_bundle,
)
from analysis.debate_memory import (
    checkpoint_phase,
    complete_debate_session,
    create_debate_session,
    format_handoff_block,
    load_debate_outputs,
    persist_tool_event,
    resume_cursor,
    resume_debate_session,
    stabilize_candidate_ids,
)
from analysis.candidate_evidence_packet import (
    SCHEMA_VERSION as EVIDENCE_PACKET_SCHEMA_VERSION,
    build_candidate_evidence_packets,
)
from analysis.graph_tools import GAP_TOOLS, GAP_TOOL_SCHEMAS, init_gap_registry
from analysis.feasibility_tools import build_gap_feasibility_tools
from analysis.focus_filter import normalize_focus
from db.schema import db_stats, init_db
from debate_labels import unwrap_outer_markdown_fence
from analysis.evidence_contract import EVIDENCE_POLICY, compact_json, number
from analysis.research_quality import (
    RESEARCH_JUDGMENT_CONTRACT,
    enforce_moderator_handoff,
    validate_moderator_handoff,
    validate_review,
    with_evidence_records,
)

init_gap_registry()
GAP_FEASIBILITY_TOOLS, GAP_FEASIBILITY_SCHEMAS = build_gap_feasibility_tools()

OPTIMIST_TOOL_NAMES = [
    "corpus_focus_coverage",
    "limitation_temporal_profile",
    "literature_evidence_search",
    "emerging_gap_opportunities",
    "improvement_suggestions_by_topic",
    "disease_task_coverage",
]

SKEPTIC_TOOL_NAMES = [
    "corpus_focus_coverage",
    "limitation_temporal_profile",
    "author_stated_gaps",
    "literature_evidence_search",
    "improvement_suggestions_by_topic",
    "execute_kg_sql",
]

MODERATOR_TOOL_NAMES = [
    "literature_data_cross_matrix",
    "pathology_disease_catalog",
    "corpus_focus_coverage",
    "execute_kg_sql",
]


def build_role_tool_bundle(role: str) -> tuple[dict[str, Any], list[dict]]:
    role = role.lower().strip()
    if role == "optimist":
        return select_tool_bundle(OPTIMIST_TOOL_NAMES, GAP_TOOLS, GAP_TOOL_SCHEMAS)
    if role == "skeptic":
        return select_tool_bundle(SKEPTIC_TOOL_NAMES, GAP_TOOLS, GAP_TOOL_SCHEMAS)
    if role == "moderator":
        # Moderator needs KG tools + feasibility tools
        merged_tools = {**GAP_TOOLS, **GAP_FEASIBILITY_TOOLS}
        merged_schemas = GAP_TOOL_SCHEMAS + GAP_FEASIBILITY_SCHEMAS
        return select_tool_bundle(MODERATOR_TOOL_NAMES, merged_tools, merged_schemas)
    raise ValueError(f"Unknown debate role: {role}")


ACCEPT_DEBATE_SCORE = 7.5

_FOCUS_MANDATE = """\
[Research focus constraint — mandatory]
The user specified research focus: {focus}
- All candidate gaps, verification conclusions, and the final report must **directly serve this focus** \
(disease/task/method must be related).
- Each gap title or research question must explicitly state its link to "{focus}".
- **Do not** output clearly off-topic gaps (other cancers, cardiotoxicity, radiology-only CT/MRI topics, etc.).
- If corpus coverage for this focus is sparse, say so in the summary; **do not** pad with unrelated topics.
- When calling KG tools, set focus="{focus}" (the system also injects it, but pass it explicitly).
"""

_SKEPTIC_FOCUS_EXTRA = """\
- First classify the CANDIDATE'S scope separately from each EVIDENCE RECORD'S scope.
- A candidate that itself drifts from "{focus}" may go to false_gaps as out-of-scope for this report.
- If the candidate is in scope but the supplied evidence is about another disease, endpoint, modality,
  or task, put the candidate in weak_evidence_gaps. Off-topic evidence is missing evidence, never a
  completed same-scope counterexample and never a reason by itself to use false_gaps.
- Do not spend space on unrelated gaps; verified_gaps must only keep items directly related to "{focus}".
"""

_MODERATOR_FOCUS_EXTRA = """\
- Every Research gap in the final report must be directly related to "{focus}"; drop Skeptic-marked off-topic items.
- In Data summary, state coverage of this report on the "{focus}" subset corpus.
"""


def _system_with_focus(base: str, focus: str | None, *, role: str) -> str:
    foc = normalize_focus(focus)
    if not foc:
        return base
    extra = _FOCUS_MANDATE.format(focus=foc)
    if role == "skeptic":
        extra += _SKEPTIC_FOCUS_EXTRA.format(focus=foc)
    elif role == "moderator":
        extra += _MODERATOR_FOCUS_EXTRA.format(focus=foc)
    return base + "\n" + extra


def _focus_hint(focus: str | None) -> str:
    foc = normalize_focus(focus)
    if not foc:
        return "No research focus specified — analyze the full pathology AI / digital pathology corpus."
    return (
        f"[Mandatory focus] {foc}\n"
        f"- Analyze only research gaps directly related to this topic.\n"
        f"- Call corpus_focus_coverage first, then other tools.\n"
        f"- Tool calls must include focus=\"{foc}\".\n"
        f"- Do not substitute full-corpus paper totals for the focus subset size.\n"
        f"- Do not output candidates unrelated to \"{foc}\" (e.g. gaps in other disease areas)."
    )

SQL_FALLBACK_GUIDANCE = """\
- Use curated tools first for standard gap-analysis questions.
- Use execute_kg_sql only for a custom join, grouped count, year filter, or exact evidence cross-check \
not exposed by an existing tool.
- Keep SQL narrow: select explicit columns, use a meaningful WHERE clause, and include LIMIT.
- When mixing AND with OR in WHERE, always parenthesize groups \
(e.g. (disease_a OR disease_b) AND (method_x OR method_y)). Bare AND/OR chains are wrong because \
AND binds tighter than OR and creates false hits.
- After an empty SQL result, do not rescan with new title/keyword OR clauses; use curated tools \
or finish with the evidence you already have.
- Do not query raw document_sections unless exact section text is necessary.
- When focus is set, pass focus=... into execute_kg_sql and reuse the returned focus_expansion \
(phrases / suggested_sql_filter) for disease or title filters — never rely on a single spelling.
"""


OPTIMIST_SYSTEM_PROMPT = """\
You are a pathology AI / digital pathology / computational pathology research-opportunity analyst \
(Opportunity Scout / Optimist Agent).
Your job is to identify academically and clinically valuable research gaps from the knowledge graph, \
emphasizing feasibility and innovation opportunities (Fangxin pathology data — no radiology imaging).

Corpus: pathology AI full-text extraction KG (author-stated limitations, results-section metric \
evidence, method–disease combination gaps, graph structure analysis). Prefer recent literature when tools provide year fields.
Prefer gaps grounded in WSI / histopathology / cytopathology / IHC rather than CT/MRI radiomics.

Language: write all candidate gap Markdown in **English**.

Tool-use rules:
- If a focus is set, the **first tool call must be corpus_focus_coverage**; the summary must distinguish \
focus_subset.papers from global.papers.
- Use at most 6 tool calls.
- Do not call the same tool twice in one phase.
- Preferred order: corpus_focus_coverage → limitation_temporal_profile → emerging_gap_opportunities → \
improvement_suggestions_by_topic → recent_highcite_papers → disease_task_coverage.
- Use emerging_gap_opportunities for task-bridged transfer candidates, not Cartesian coverage holes.
- Do not treat coverage holes as research opportunities.
- Do not call tools outside your available tool list.
- Every quantitative claim must cite exact tool values (including first_year, recent_ratio, \
resolution_signal, avg_cite, impact_score).
- If focus_subset.papers < 30, do not claim persistent temporal trends or cite full-corpus scale; \
mark “insufficient corpus coverage”.

Output format (Markdown, no emoji):

## Candidate research gap summary
[Briefly list tools used, data coverage, and corpus-size limits]

## Candidate research gap list

### Candidate gap 1: [direction name]
**Candidate ID**: G01 (use stable G02, G03, ... for later candidates and preserve IDs on revision)
**Research question**: [testable scientific question]
**Evidence basis**: [exact tool values, including temporal_status / resolution_signal]
**Temporal profile**: [first_year–last_year, temporal_status, recent_ratio]
**Opportunity rationale**: [why it is worth pursuing]
**Feasibility**: [data / technical / clinical availability]
**Expected impact**: [journal direction, scientific significance]

---
[Repeat until top_n items]

## Opportunity Scout summary
[Core recommendation in ≤100 words]
"""

SKEPTIC_SYSTEM_PROMPT = """\
You are a strict pathology-AI research-gap auditor (Evidence Reviewer / Skeptic Agent).
Your job is to cross-check Opportunity Scout candidates, catch false gaps, weak evidence, and over-claims.

Language: JSON string field values must be in **English**.

Review principles:
""" + SQL_FALLBACK_GUIDANCE + """\
- Use at most 5 tool calls.
- Prefer corpus_focus_coverage, limitation_temporal_profile, and author_stated_gaps, in that order.
- Use literature_evidence_search with a scoped query and explicit cut-off to collect individually attributable
  opportunity evidence and completed-work counterevidence. Empty results mean only in-corpus absence.
- Use improvement_suggestions_by_topic for action_type / follow-up evidence (do not SQL-scan \
paper_improvement_suggestions for the same).
- Use execute_kg_sql for targeted verification at most 2 times.
- If focus is set, **call corpus_focus_coverage first** and cite focus_subset size in corpus_limitations.
- Independently verify the Opportunity Scout’s key quantitative claims.
- Use limitation_temporal_profile for the temporal dimension.
- Do not call tools outside your available tool list.
- Never invent tools. Especially never call a tool named json/markdown/text — \
JSON is **message content only** (use a ```json fence), not a tool call.
- Do not label a limitation as a persistent gap if temporal_status=declining and resolution_signal=moderate.
- May raise confidence if temporal_status=persistent and resolution_signal=none.
- For each gap, check supporting paper counts, avg_cite, impact_tier; do not over-extrapolate from a single low-cite paper.
- Corpus caveat: global.papers is full-corpus scale; the focus subset may be only tens of papers — do not mix them.
- If citation/IF data are missing (impact_tier=Unknown), note in corpus_limitations that enrich-s2 / import-if is needed.
- Distinguish true gaps, corpus non-coverage, and weak evidence (rules below).

Classification (strict):
- **false_gaps**: A directly contradicted concrete fact or a completed study that answers the same \
disease/task/protocol question. Merely showing that a novelty argument is invalid is NOT such a counterexample.
- **weak_evidence_gaps**: Insufficient direct evidence, failed/empty search, sparse focus, unsupported \
universal claims or missing historical coverage. A claim of a multi-year gap based only on a small \
single-year corpus is unestablished, not proof that the underlying gap has been resolved.
- **verified_gaps**: Direct positive sources support an unresolved scoped question, quantitative claims \
match this round's tools, and no relevant pre-cutoff counterexample exists. Matching counts alone is insufficient.

Output each original candidate once. Put wording defects or recommended rewrites in its rationale/suggestion, \
not a second classification. Judge whether the scientific question is established/refuted/unknown separately \
from whether the Scout's proof is valid. Example: a search failure or zero keyword matches presented as proof \
of novelty belongs only in weak_evidence_gaps; explain the invalid proof there. A separate completed experiment \
answering the exact question is needed to classify that gap as false.

- Challenge small-sample extrapolation and whether unexplored combos may already be common outside this corpus.
- Prefer pathology-native gaps (WSI / histopathology / cytopathology / IHC). Put CT/MRI radiomics-only \
directions in false_gaps or weak_evidence_gaps (Fangxin has pathology slides, not radiology imaging).

Output format (strict JSON inside a ```json ... ``` fence in the **message content**; \
never call a tool named json):

```json
{
  "overall_confidence": <float, 0-10, overall trust in the Scout proposal>,
  "verified_gaps": [
    {"candidate_id": "original ID", "title": "...", "evidence": "tool-backed rationale", "confidence": <0-10>,
     "evidence_refs": [{"evidence_id": "supplied ID", "quote": "contiguous source excerpt", "stance": "supports_gap"}]}
  ],
  "false_gaps": [
    {"candidate_id": "original ID", "title": "...", "reason": "direct counterexample", "counter_evidence": "...",
     "evidence_refs": [{"evidence_id": "supplied ID", "quote": "contiguous source excerpt", "stance": "refutes_gap"}]}
  ],
  "weak_evidence_gaps": [
    {"candidate_id": "original ID", "title": "...", "issue": "where evidence is weak", "suggestion": "how to strengthen",
     "evidence_refs": [{"evidence_id": "supplied ID", "quote": "contiguous source excerpt", "stance": "context"}]}
  ],
  "corpus_limitations": "<corpus size, extraction coverage, and other systemic limits>",
  "data_concerns": ["<specific data issue 1>", "..."],
  "revision_priority": "<most important revision direction for Synthesizer/Scout>"
}
```

No emoji.
"""

MODERATOR_SYSTEM_PROMPT = """\
You are a pathology-AI research strategy synthesizer (Final Synthesizer / Moderator Agent).
Your job is to combine Opportunity Scout candidates with Evidence Reviewer cross-checks into the final research-gap report.

Role mapping for the user-facing report: Opportunity Scout = Optimist, Evidence Reviewer = Skeptic, \
Final Synthesizer = Moderator.
**The final Markdown report must use the user-facing English role names; do not use Optimist/Skeptic/Moderator \
as labels in the delivered report.**

Language: write the entire final report in **English**.

Synthesis principles:
""" + SQL_FALLBACK_GUIDANCE + """\
- Use at most 4 tool calls.
- Prefer literature_data_cross_matrix and pathology_disease_catalog, in that order.
- Use corpus_focus_coverage only when needed for scale statements.
- Use execute_kg_sql only to resolve conflicts between Scout claims, Reviewer findings, and curated-tool evidence.
- Prefer limitation_temporal_profile / author_stated_gaps over SELECT limitation_temporal \
(that cache table is often empty).
- Call pathology_disease_catalog **without** organ_system first (or with a known-correct organ). \
Do **not** guess organ_system (e.g. respiratory for nasopharyngeal / NPC); match disease_id \
from catalog results to the focus disease.
- Do not call tools outside your available tool list.
- Never invent tools. Especially never call a tool named json/markdown/text — \
JSON or Markdown are **message content only**, not tool calls. \
Revision JSON may use a ```json fence; the final Markdown report must be raw Markdown \
(start with # or ##) — never wrap the whole report in a ```markdown fence.
- Keep high-confidence gaps verified by the Evidence Reviewer; drop or downgrade false_gaps.
- For weak_evidence_gaps, either require softer wording or explicitly mark evidence limits.
- In Data summary, state corpus size and extracted-paper limits.
- **Must** call literature_data_cross_matrix and pathology_disease_catalog; \
append “Fangxin data support” and “Literature impact” (avg_cite, impact_tier, cross_priority_score) to each gap.
- Prefer crossings of “literature gap + adequate Fangxin data + impact_tier High/Medium”.
- Prefer pathology-native directions; deprioritize radiology-only (CT/MRI radiomics) gaps.
- All quantitative claims must cite tool data; no emoji.

If overall_confidence >= 7.5 or this is the last debate round, output the full final report (Markdown):

## Data summary
[Tools called, record counts, corpus scale, Review consensus score]

## Research gap analysis

### Research gap 1: [direction name]
**Candidate ID**: [original Gxx ID; required]
**Research question**:
**Evidence basis**:
**Temporal profile**: (first_year–last_year, temporal_status, recent_ratio)
**Follow-up signal**: (resolution_signal, followup_paper_cnt, first_followup_year)
**Feasibility analysis**:
**Fangxin data support**: (mock_cohort_size / cohort_size, data_support, available task_type)
**Literature impact**: (avg_cite, avg_if, impact_tier, cross_priority_score)
**Expected academic impact**:
**Main challenges**:
**Distinction from prior work**:
**Review consensus**: Opportunity Scout proposal / Evidence Reviewer conclusion
**Difficulty**: Low / Medium / High / Very high
**Novelty**: Moderate / High / Very high

---
[Gaps 2…top_n, same format]

## Priority ranking
| Rank | Candidate ID | Direction | Difficulty | Novelty | Impact tier | cross_priority_score | Clinical value |
|------|--------------|-----------|------------|---------|-------------|----------------------|----------------|

## Overall recommendation
[150–200 words of strategic advice]

## Review process summary
[Key Scout vs Reviewer disagreements and Final Synthesizer rulings]

---
If confidence is insufficient and this is not the last round, output JSON in the message \
content (```json ... ``` fence; never call a tool named json):
```json
{
  "accept": false,
  "overall_confidence": <float>,
  "revision_priority": "<next round focus for Opportunity Scout>",
  "gaps_to_revise": ["..."],
  "gaps_to_drop": ["..."]
}
```
"""


OPTIMIST_SYSTEM_PROMPT += EVIDENCE_POLICY
SKEPTIC_SYSTEM_PROMPT += EVIDENCE_POLICY + RESEARCH_JUDGMENT_CONTRACT
MODERATOR_SYSTEM_PROMPT += EVIDENCE_POLICY
MODERATOR_SYSTEM_PROMPT += "\nUse the validated review and quality_audit. Never promote a provenance-downgraded candidate back to verified. A located source is not proof of worldwide novelty. Preserve candidate IDs and cite evidence records in the final report.\n"


def _corpus_context(focus: str | None = None) -> str:
    from analysis.gap_tools import tool_corpus_focus_coverage

    stats = db_stats()
    coverage = tool_corpus_focus_coverage(focus=focus)
    lines = [
        "\n\nCorpus statistics (must be cited in the analysis):",
        f"- Full-corpus PubMed papers: {stats['papers']}",
        f"- Full-corpus full text available: {stats['fulltext_available']}",
        f"- Full-corpus LLM-extracted: {stats['extracted']}",
        f"- S2 citation enriched: {stats.get('s2_enriched', 0)}",
        f"- Full-text relations: {stats['relations_fulltext']}",
    ]

    foc = normalize_focus(focus)
    sub = coverage.get("focus_subset")
    if foc and sub:
        lines.extend([
            f"\n**Focus \"{foc}\" subset (topic-specific claims may use only these numbers)**:",
            f"- Focus papers: {sub['papers']} (full corpus {stats['papers']}, "
            f"share {coverage.get('coverage_ratio', 0):.2%})",
            f"- Focus extracted: {sub.get('extracted', 0)}",
            f"- Focus limitation relations: {sub.get('limitation_relations', 0)}",
            f"- Focus method entities: {sub.get('method_entities', 0)}",
            f"- analysis_ready (>=30 papers): {coverage.get('analysis_ready', False)}",
        ])
        for w in coverage.get("warnings") or []:
            lines.append(f"- Warning: {w}")

    return "\n".join(lines)


def resolve_ops_memory_block(
    focus: str | None,
    use_ops_memory: bool | None,
) -> str:
    """Load formatted ops-memory prompt block when enabled."""
    from analysis.ops_memory import format_memory_prompt_block, load_recent_gaps

    enabled = config.OPS_MEMORY_ENABLED if use_ops_memory is None else use_ops_memory
    if not enabled:
        return ""
    return format_memory_prompt_block(load_recent_gaps(focus))


def _append_memory_block(text: str, memory_block: str) -> str:
    if not memory_block:
        return text
    return f"{text.rstrip()}\n\n{memory_block}"


def stream_gap_debate_agent(
    focus: str | None = None,
    top_n: int = 6,
    max_debate_rounds: int = 2,
    accept_score: float = ACCEPT_DEBATE_SCORE,
    use_ops_memory: bool | None = None,
    resume_session_id: str | None = None,
) -> Generator[dict, None, None]:
    """Debate multi-agent gap identification loop."""
    resumed = bool(resume_session_id)
    if resume_session_id:
        session_state = resume_debate_session(resume_session_id)
        focus = normalize_focus(session_state.focus_raw)
        max_debate_rounds = session_state.max_rounds
        top_n = session_state.top_n
    else:
        focus = normalize_focus(focus)
        session_state = create_debate_session(
            focus=focus,
            max_rounds=max_debate_rounds,
            top_n=top_n,
        )
    yield {
        "type": "start",
        "session_id": session_state.session_id,
        "resumed": resumed,
        "resume_round": session_state.current_round if resumed else 0,
        "resume_role": session_state.next_role if resumed else "optimist",
        "focus": focus,
        "top_n": top_n,
        "max_debate_rounds": max_debate_rounds,
    }

    corpus_ctx = _corpus_context(focus)
    focus_hint = _focus_hint(focus)
    memory_block = resolve_ops_memory_block(focus, use_ops_memory)
    opt_tools_raw, opt_schemas = build_role_tool_bundle("optimist")
    ske_tools_raw, ske_schemas = build_role_tool_bundle("skeptic")
    mod_tools_raw, mod_schemas = build_role_tool_bundle("moderator")
    opt_tools = bind_tools_with_focus(with_evidence_records(opt_tools_raw), focus)
    ske_tools = bind_tools_with_focus(with_evidence_records(ske_tools_raw), focus)
    mod_tools = bind_tools_with_focus(with_evidence_records(mod_tools_raw), focus)

    optimist_proposal = ""
    skeptic_review: dict = {}
    final_report = ""
    final_confidence = 0.0
    completed_rounds = 0
    debate_feedback: dict = {}
    evidence_ledger: dict[str, dict[str, dict]] = {}
    def run_phase(*, round_num: int, **kwargs):
        role = kwargs["role"]
        evidence_ledger[role] = {}
        for event in run_tool_agent(**kwargs):
            persist_tool_event(
                session_state,
                round_no=round_num,
                role=role,
                event=event,
            )
            if event.get("type") == "tool_result" and isinstance(event.get("result"), dict) and "error" not in event["result"]:
                key = event["name"]
                if key in evidence_ledger[role]:
                    suffix = 2
                    while f"{key}#{suffix}" in evidence_ledger[role]:
                        suffix += 1
                    key = f"{key}#{suffix}"
                evidence_ledger[role][key] = {"call_id":event.get("call_id"), "result":event["result"]}
            yield event

    def cumulative_role_evidence(role: str) -> dict[str, dict]:
        merged: dict[str, dict] = {}
        for round_roles in session_state.evidence_ledger.values():
            for key, value in round_roles.get(role, {}).items():
                merged[key] = value
        return merged

    def round_role_evidence(round_num: int, role: str) -> dict[str, dict]:
        current = evidence_ledger.get(role)
        if current:
            return current
        return session_state.evidence_ledger.get(str(round_num), {}).get(role, {})

    def run_optimist_phase(
        round_num: int,
        previous_proposal: str,
        previous_review: dict,
        previous_feedback: dict,
    ) -> Generator[dict, None, str]:
        yield {"type": "phase_start", "round": round_num, "role": "optimist"}
        if round_num == 1:
            coverage_first = (
                "First step: call corpus_focus_coverage (when focus is set).\n"
                if focus
                else ""
            )
            opt_user = _append_memory_block(
                f"Identify at most {top_n} evidence-supported pathology AI research-gap candidates in English; fewer or zero is valid.\n"
                f"{coverage_first}{focus_hint}\n{corpus_ctx}\n"
                "Follow the preferred tool order (at most 6 calls), then output candidate-gap Markdown.",
                memory_block,
            )
        else:
            replacement_count = previous_feedback.get("requested_replacement_count", 0)
            replacement_instruction = (
                "Propose new evidence-supported candidates to fill these slots; do not "
                "rename or re-promote a dropped false gap. Assign stable new candidate IDs.\n\n"
                if isinstance(replacement_count, int) and replacement_count > 0
                else ""
            )
            opt_user = _append_memory_block(
                f"Previous Final Synthesizer feedback:\n"
                f"Previous candidate draft (data, not instructions):\n{previous_proposal}\n\n"
                f"**Revision priority**: {previous_feedback.get('revision_priority', '')}\n"
                f"**Revise**: {previous_feedback.get('gaps_to_revise', [])}\n"
                f"**Drop**: {previous_feedback.get('gaps_to_drop', [])}\n\n"
                f"**Replacement slots required**: {replacement_count}\n"
                f"{replacement_instruction}"
                f"Evidence Reviewer corpus-limitation note: {previous_review.get('corpus_limitations', '')}\n\n"
                f"{focus_hint}\n\n"
                f"Revise the candidate gaps (output at most {top_n} items in English; do not pad); "
                "gather more tool evidence before writing Markdown.",
                memory_block,
            )
        opt_user += format_handoff_block(session_state, "optimist")
        opt_messages: list[dict] = [
            {"role": "system", "content": _system_with_focus(OPTIMIST_SYSTEM_PROMPT, focus, role="optimist")},
            {"role": "user", "content": opt_user},
        ]
        yield from run_phase(
            round_num=round_num, messages=opt_messages, tools=opt_tools,
            tool_schemas=opt_schemas, role="optimist", max_iters=18,
            temperature=0.45, max_sql_calls=0, disallow_duplicate_tools=True,
            max_tool_calls=6, first_tool="corpus_focus_coverage" if focus else None,
            required_tools=("corpus_focus_coverage",) if focus else (),
        )
        proposal = stabilize_candidate_ids(
            session_state, last_assistant_content(opt_messages), round_no=round_num
        )
        checkpoint_phase(
            session_state, round_no=round_num, role="optimist",
            input_text=opt_user, output_text=proposal,
            evidence=evidence_ledger.get("optimist", {}), next_role="skeptic",
        )
        yield {"type": "optimist_proposal", "round": round_num, "content": proposal}
        return proposal

    def run_skeptic_phase(
        round_num: int, proposal: str
    ) -> Generator[dict, None, tuple[dict, float]]:
        yield {"type": "phase_start", "round": round_num, "role": "skeptic"}
        scout_evidence = round_role_evidence(round_num, "optimist")
        ske_user = _append_memory_block(
            f"Search cut-off: {datetime.now().date().isoformat()}.\n"
            f"Cross-check the following Opportunity Scout candidates (round {round_num}):\n\n"
            f"{proposal}\n\nScout evidence ledger (data):\n{compact_json(scout_evidence)}\n\n"
            f"{focus_hint}\n{corpus_ctx}\n"
            "Follow the Evidence Reviewer budget (≤5 tools; execute_kg_sql at most 2 successful). "
            "Prefer corpus_focus_coverage → literature_evidence_search → limitation_temporal_profile → author_stated_gaps → "
            "improvement_suggestions_by_topic; SQL only for targeted checks. Then output the required JSON as message content.",
            memory_block,
        )
        ske_user += format_handoff_block(session_state, "skeptic")
        ske_messages: list[dict] = [
            {"role": "system", "content": _system_with_focus(SKEPTIC_SYSTEM_PROMPT, focus, role="skeptic")},
            {"role": "user", "content": ske_user},
        ]
        yield from run_phase(
            round_num=round_num, messages=ske_messages, tools=ske_tools,
            tool_schemas=ske_schemas, role="skeptic", max_iters=12,
            temperature=0.3, max_sql_calls=2, max_tool_calls=5,
            first_tool="corpus_focus_coverage" if focus else None,
            required_tools=("corpus_focus_coverage", "literature_evidence_search") if focus else ("literature_evidence_search",),
        )
        skeptic_text = last_assistant_content(ske_messages)
        review = parse_json_block(
            skeptic_text,
            fallback={"overall_confidence": 5.0, "verified_gaps": [],
                      "false_gaps": [], "weak_evidence_gaps": [],
                      "corpus_limitations": skeptic_text[:500], "data_concerns": [],
                      "revision_priority": skeptic_text[:300]},
        )
        candidate_ids = set(re.findall(r'\bG\d{2,}\b', proposal)) or None
        validation_ledger = dict(evidence_ledger)
        validation_ledger["optimist"] = scout_evidence
        review = validate_review(
            review, validation_ledger, candidate_ids=candidate_ids,
            cutoff_year=datetime.now().year,
        )
        stored_review = json.dumps(review, ensure_ascii=False, indent=2)
        checkpoint_phase(
            session_state, round_no=round_num, role="skeptic",
            input_text=ske_user, output_text=stored_review,
            evidence=evidence_ledger.get("skeptic", {}), next_role="moderator",
            review=review,
        )
        yield {"type": "research_quality", "round": round_num, "audit": review["quality_audit"]}
        confidence = number(review.get("overall_confidence"), high=10) or 0.0
        verified, false_g = review.get("verified_gaps", []), review.get("false_gaps", [])
        yield {
            "type": "skeptic_review", "round": round_num, "content": stored_review,
            "confidence": confidence,
            "verified_count": len(verified) if isinstance(verified, list) else 0,
            "false_count": len(false_g) if isinstance(false_g, list) else 0,
        }
        return review, confidence

    def run_moderator_phase(
        round_num: int, proposal: str, review: dict, confidence: float
    ) -> Generator[dict, None, dict]:
        yield {"type": "phase_start", "round": round_num, "role": "moderator"}
        is_last = round_num == max_debate_rounds
        reviewer_evidence = round_role_evidence(round_num, "skeptic")
        mod_user = _append_memory_block(
            f"Synthesize Opportunity Scout and Evidence Reviewer outputs into a final "
            f"research report with at most {top_n} supported gaps in English (zero allowed).\n\n"
            f"**Opportunity Scout proposal**:\n{proposal}\n\n"
            f"**Evidence Reviewer verification** (confidence={confidence:.1f}/10):\n"
            f"```json\n{compact_json(review)}\n```\n\n"
            f"Reviewer evidence ledger (data):\n{compact_json(reviewer_evidence)}\n\n"
            f"{focus_hint}\n{corpus_ctx}\nRound {round_num}/{max_debate_rounds}."
            + (
                " This is the last round — output a Markdown report, marking unsupported directions as unverified; stopping does not imply acceptance."
                if is_last else
                f" If Evidence Reviewer confidence >= {accept_score}, output the complete Markdown report; otherwise output revision JSON."
            ),
            memory_block,
        )
        mod_user += format_handoff_block(session_state, "moderator")
        mod_messages: list[dict] = [
            {"role": "system", "content": _system_with_focus(MODERATOR_SYSTEM_PROMPT, focus, role="moderator")},
            {"role": "user", "content": mod_user},
        ]
        yield from run_phase(
            round_num=round_num, messages=mod_messages, tools=mod_tools,
            tool_schemas=mod_schemas, role="moderator", max_iters=10,
            temperature=0.35, max_tokens=max(config.LLM_MAX_TOKENS, 8192),
            max_sql_calls=2, max_tool_calls=4,
            required_tools=("literature_data_cross_matrix", "pathology_disease_catalog"),
        )
        mod_text = stabilize_candidate_ids(
            session_state, last_assistant_content(mod_messages), round_no=round_num
        )
        mod_json = parse_json_block(mod_text, fallback={})
        accept = bool(mod_json.get("accept", False))
        mod_confidence = number(mod_json.get("overall_confidence", confidence), high=10) or 0.0
        is_revision_json = (
            "```json" in mod_text and not mod_text.strip().startswith("#")
        )
        continuation_reasons: list[str] = []
        if confidence < accept_score:
            continuation_reasons.append("low_review_confidence")
        if not review.get("verified_gaps"):
            continuation_reasons.append("no_verified_candidates")
        if review.get("quality_audit", {}).get("status") != "provenance_checked":
            continuation_reasons.append("research_provenance_incomplete")
        eligible_ids = {
            str(item.get("candidate_id"))
            for bucket in ("verified_gaps", "weak_evidence_gaps")
            for item in review.get(bucket, [])
            if isinstance(item, dict) and item.get("candidate_id")
        }
        recommendation_shortfall = max(0, top_n - len(eligible_ids))
        if recommendation_shortfall:
            continuation_reasons.append(
                f"recommendation_shortfall:{len(eligible_ids)}/{top_n}"
            )
        if is_revision_json and not accept:
            continuation_reasons.append("moderator_requested_revision")
        will_continue = not is_last and bool(continuation_reasons)

        feedback_json = mod_json
        if will_continue:
            revise_ids = sorted({
                str(item.get("candidate_id"))
                for bucket in ("verified_gaps", "weak_evidence_gaps")
                for item in review.get(bucket, [])
                if isinstance(item, dict) and item.get("candidate_id")
            })
            drop_ids = sorted({
                str(item.get("candidate_id"))
                for item in review.get("false_gaps", [])
                if isinstance(item, dict) and item.get("candidate_id")
            })
            reviewer_priority = (
                mod_json.get("revision_priority")
                or review.get("revision_priority")
                or "Resolve evidence and provenance issues before final synthesis."
            )
            if recommendation_shortfall:
                reviewer_priority = (
                    f"{reviewer_priority} Replace {recommendation_shortfall} rejected or missing "
                    f"candidate slot(s) so the next review evaluates {top_n} eligible directions."
                )
            feedback_json = {
                **(mod_json if isinstance(mod_json, dict) else {}),
                "accept": False,
                "overall_confidence": mod_confidence,
                "revision_priority": reviewer_priority,
                "gaps_to_revise": mod_json.get("gaps_to_revise") or revise_ids,
                "gaps_to_drop": mod_json.get("gaps_to_drop") or drop_ids,
                "recommendation_target": top_n,
                "eligible_candidate_count": len(eligible_ids),
                "requested_replacement_count": recommendation_shortfall,
                "continuation_reasons": sorted(set(continuation_reasons)),
                "moderator_output_format": (
                    "revision_json" if is_revision_json else "markdown_draft"
                ),
            }
        stored_mod_output = (
            json.dumps(feedback_json, ensure_ascii=False, indent=2)
            if will_continue
            else mod_text
        )
        checkpoint_phase(
            session_state, round_no=round_num, role="moderator",
            input_text=mod_user, output_text=stored_mod_output,
            evidence=evidence_ledger.get("moderator", {}),
            next_role="optimist" if will_continue else "complete",
            review=feedback_json,
        )
        if will_continue:
            yield {"type": "debate_feedback", "round": round_num,
                   "revision_priority": feedback_json.get("revision_priority", ""),
                   "continuation_reasons": feedback_json.get("continuation_reasons", []),
                   "content": mod_text,
                   "structured_feedback": feedback_json}
        return {"text": mod_text, "json": feedback_json, "accept": accept,
                "confidence": mod_confidence, "is_last": is_last,
                "will_continue": will_continue}

    saved_outputs = load_debate_outputs(session_state.session_id) if resumed else {}
    def latest_output(role: str) -> str:
        rows = [(round_no, text) for (round_no, saved_role), text in saved_outputs.items()
                if saved_role == role]
        return max(rows, default=(0, ""), key=lambda item: item[0])[1]

    optimist_proposal = latest_output("optimist")
    skeptic_review = parse_json_block(latest_output("skeptic"), fallback={})
    debate_feedback = parse_json_block(latest_output("moderator"), fallback={})
    final_confidence = number(skeptic_review.get("overall_confidence"), high=10) or 0.0
    start_round, start_role = resume_cursor(session_state) if resumed else (1, "optimist")
    completed_rounds = session_state.current_round if resumed else 0

    if start_role == "complete":
        final_report = unwrap_outer_markdown_fence(latest_output("moderator"))
        mod_saved = parse_json_block(latest_output("moderator"), fallback={})
        final_confidence = number(mod_saved.get("overall_confidence"), high=10) or final_confidence
    else:
        role_order = {"optimist": 0, "skeptic": 1, "moderator": 2}
        for round_num in range(start_round, max_debate_rounds + 1):
            yield {"type": "debate_round_start", "round": round_num,
                   "max_rounds": max_debate_rounds,
                   "resumed": resumed and round_num == start_round}
            floor = role_order[start_role] if resumed and round_num == start_round else 0
            if floor <= 0:
                optimist_proposal = yield from run_optimist_phase(
                    round_num, optimist_proposal, skeptic_review, debate_feedback
                )
            else:
                optimist_proposal = saved_outputs.get(
                    (round_num, "optimist"), optimist_proposal
                )
            if floor <= 1:
                skeptic_review, confidence = yield from run_skeptic_phase(
                    round_num, optimist_proposal
                )
            else:
                skeptic_review = parse_json_block(
                    saved_outputs.get((round_num, "skeptic"), ""), fallback={}
                )
                confidence = number(skeptic_review.get("overall_confidence"), high=10) or 0.0
            moderator = yield from run_moderator_phase(
                round_num, optimist_proposal, skeptic_review, confidence
            )
            completed_rounds = round_num
            debate_feedback = moderator["json"]
            if moderator["will_continue"]:
                start_role = "optimist"
                continue
            final_report = unwrap_outer_markdown_fence(moderator["text"])
            final_confidence = moderator["confidence"] or confidence
            if (confidence >= accept_score or moderator["is_last"]
                    or moderator["accept"] or final_report.strip().startswith("#")):
                break

    required = {
        "moderator": ("literature_data_cross_matrix", "pathology_disease_catalog"),
        "skeptic": ("literature_evidence_search",),
    }
    if focus:
        required.update(
            optimist=("corpus_focus_coverage",),
            skeptic=("corpus_focus_coverage", "literature_evidence_search"),
        )
    missing = [
        f"{role}.{name}"
        for role, names in required.items()
        for name in names
        if name not in cumulative_role_evidence(role)
    ]
    validation_reasons = ["missing_required_tool:" + x for x in missing]
    if final_confidence < accept_score: validation_reasons.append("low_review_confidence")
    if not skeptic_review.get("verified_gaps"): validation_reasons.append("no_verified_candidates")
    if skeptic_review.get("quality_audit", {}).get("status") != "provenance_checked":
        validation_reasons.append("research_provenance_incomplete")
    for role in ("optimist", "skeptic"):
        coverage = cumulative_role_evidence(role).get(
            "corpus_focus_coverage", {}
        ).get("result", {})
        n = coverage.get("focus_subset", {}).get("papers")
        if focus and isinstance(n, (int,float)) and n < 30:
            validation_reasons.append("insufficient_focus_coverage")
    status = "needs_verification" if validation_reasons else "evidence_checked"
    report = unwrap_outer_markdown_fence(final_report or optimist_proposal)
    report, handoff_enforcement = enforce_moderator_handoff(
        report, skeptic_review, target_count=top_n
    )
    handoff_audit = validate_moderator_handoff(report, skeptic_review)
    validation_reasons.extend(
        "moderator_handoff:" + issue for issue in handoff_audit["issues"]
    )
    status = "needs_verification" if validation_reasons else "evidence_checked"
    if validation_reasons:
        report = "> Verification incomplete: " + "; ".join(sorted(set(validation_reasons))) + "\n\n" + report
    candidate_evidence_packets = build_candidate_evidence_packets(
        report_text=report,
        reviewer=skeptic_review,
        evidence_source=session_state.evidence_ledger,
        focus=focus,
        debate_session_id=session_state.session_id,
        validation_status=status,
    )
    session_state.candidate_evidence_packets = candidate_evidence_packets
    complete_debate_session(
        session_state,
        final_report=report,
        validation_status=status,
    )
    yield {
        "type": "final",
        "session_id": session_state.session_id,
        "focus": focus,
        "content": report,
        "validation_status":status,
        "validation_reasons":sorted(set(validation_reasons)),
        "research_quality":skeptic_review.get("quality_audit", {}),
        "handoff_audit": handoff_audit,
        "handoff_enforcement": handoff_enforcement,
        "candidate_evidence_packets": candidate_evidence_packets,
        "evidence_packet_schema_version": EVIDENCE_PACKET_SCHEMA_VERSION,
        "rounds": completed_rounds,
        "confidence": final_confidence,
    }


def run_gap_debate_agent(
    focus: str | None = None,
    top_n: int = 6,
    max_debate_rounds: int = 2,
    verbose: bool = False,
    use_ops_memory: bool | None = None,
    result_meta: dict[str, Any] | None = None,
    resume_session_id: str | None = None,
) -> str:
    print(f"\n{'='*60}")
    print("Gap Debate Multi-Agent — pathology AI / digital pathology")
    print(f"  Focus: {focus or 'all'}")
    print(f"  Top-N: {top_n}")
    print(f"  Debate rounds: {max_debate_rounds}")
    print(f"{'='*60}\n")

    report = ""
    for event in stream_gap_debate_agent(
        focus=focus,
        top_n=top_n,
        max_debate_rounds=max_debate_rounds,
        use_ops_memory=use_ops_memory,
        resume_session_id=resume_session_id,
    ):
        etype = event["type"]
        if etype == "start":
            if result_meta is not None:
                result_meta.update(
                    {
                        "session_id": event.get("session_id", ""),
                        "focus": event.get("focus"),
                        "resumed": bool(event.get("resumed")),
                    }
                )
        elif etype == "debate_round_start":
            print(f"\n--- Debate Round {event['round']} / {event['max_rounds']} ---")
        elif etype == "phase_start":
            print(f"  [{event['role']}] phase started")
        elif etype == "tool_call":
            print(f"  [{event['role']}][tool] {event['name']}({event.get('args', {})})")
        elif etype == "tool_error":
            print(f"  [{event['role']}][error] {event['name']}: {event['error']}")
        elif etype == "thinking" and verbose:
            print(f"  [{event['role']}][thinking] {event['content'][:100]}...")
        elif etype == "skeptic_review":
            print(f"  [skeptic] confidence={event['confidence']:.1f}/10  "
                  f"verified={event['verified_count']} false={event['false_count']}")
        elif etype == "final":
            report = event["content"]
            if result_meta is not None:
                result_meta.update(
                    {
                        "session_id": event.get("session_id", ""),
                        "validation_status": event.get(
                            "validation_status", "needs_verification"
                        ),
                        "validation_reasons": event.get("validation_reasons", []),
                        "rounds": event.get("rounds", 0),
                        "confidence": event.get("confidence", 0.0),
                    }
                )
            print(f"\nFinal report after {event['rounds']} round(s), "
                  f"confidence {event['confidence']:.1f}/10\n")
        elif etype == "error":
            print(f"\n[warning] {event['content']}")
    return report


def save_report(content: str, path: str, focus: str | None = None) -> None:
    from debate_labels import humanize_debate_report

    body = humanize_debate_report(content)
    header = textwrap.dedent(f"""\
        # Pathomics/Radiomics Research Gap Report

        > Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        > Focus: {focus or 'All domains'}
        > Flow: Opportunity Scout → Evidence Reviewer → Final Synthesizer

        ---

    """)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gap Debate Multi-Agent")
    parser.add_argument("--focus", "-f", default=None)
    parser.add_argument("--top", "-n", type=int, default=6)
    parser.add_argument("--rounds", "-r", type=int, default=2)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    init_db()
    report = run_gap_debate_agent(
        focus=args.focus,
        top_n=args.top,
        max_debate_rounds=args.rounds,
        verbose=args.verbose,
    )

    print("\n" + "=" * 60)
    print(report[:2000] + ("..." if len(report) > 2000 else ""))
    print("=" * 60)

    if args.output:
        save_report(report, args.output, focus=args.focus)
        print(f"\nReport saved: {args.output}")
    elif report:
        default_path = f"{config.OUTPUT_DIR}/gap_debate_report.md"
        save_report(report, default_path, focus=args.focus)
        print(f"\nReport saved: {default_path}")
