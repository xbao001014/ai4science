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
)
from analysis.graph_tools import GAP_TOOLS, GAP_TOOL_SCHEMAS, init_gap_registry
from analysis.feasibility_tools import build_gap_feasibility_tools
from analysis.focus_filter import normalize_focus
from db.schema import db_stats, init_db

init_gap_registry()
GAP_FEASIBILITY_TOOLS, GAP_FEASIBILITY_SCHEMAS = build_gap_feasibility_tools()

ACCEPT_DEBATE_SCORE = 7.5

_FOCUS_MANDATE = """\
[Research focus constraint — mandatory]
The user specified research focus: {focus}
- All candidate gaps, verification conclusions, and the final report must **directly serve this focus** \
(disease/task/method must be related).
- Each gap title or research question must explicitly state its link to "{focus}".
- **Do not** output clearly off-topic gaps (other cancers, cardiotoxicity, unrelated imaging modalities, etc.).
- If corpus coverage for this focus is sparse, say so in the summary; **do not** pad with unrelated topics.
- When calling KG tools, set focus="{focus}" (the system also injects it, but pass it explicitly).
"""

_SKEPTIC_FOCUS_EXTRA = """\
- Put candidates that drift from "{focus}" into false_gaps, with reason noting off-topic / not related to the focus.
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
        return "No research focus specified — analyze the full pathomics/radiomics corpus."
    return (
        f"[Mandatory focus] {foc}\n"
        f"- Analyze only research gaps directly related to this topic.\n"
        f"- Call corpus_focus_coverage first, then other tools.\n"
        f"- Tool calls must include focus=\"{foc}\".\n"
        f"- Do not substitute full-corpus paper totals for the focus subset size.\n"
        f"- Do not output candidates unrelated to \"{foc}\" (e.g. gaps in other disease areas)."
    )

OPTIMIST_SYSTEM_PROMPT = """\
You are a pathology AI / pathomics / radiomics research-opportunity analyst (Opportunity Scout / Optimist Agent).
Your job is to identify academically and clinically valuable research gaps from the knowledge graph, \
emphasizing feasibility and innovation opportunities.

Corpus: pathomics/radiomics full-text extraction KG (author-stated limitations, results-section metric \
evidence, method–disease combination gaps, graph structure analysis). Prefer recent literature when tools provide year fields.

Language: write all candidate gap Markdown in **English**.

Tool-use rules:
- If a focus is set, the **first tool call must be corpus_focus_coverage**; the summary must distinguish \
focus_subset.papers from global.papers.
- Call at least 5 tools, including at least 1 graph_* traversal tool.
- Prefer limitation_temporal_profile / limitation_gap_status (limitation timeline + follow-up signals).
- Pair with author_stated_gaps / limitation_impact_rank (author limitations + citation impact).
- Use combo_gap_temporal to find method×disease combos with later follow-up.
- Use hotspot_entities and recent_highcite_papers for high-impact frontier directions.
- Use emerging_gap_opportunities for “recent heating × literature gap” crossings (weekly hotspots).
- Every quantitative claim must cite exact tool values (including first_year, recent_ratio, \
resolution_signal, avg_cite, impact_score).
- If focus_subset.papers < 30, do not claim persistent temporal trends or cite full-corpus scale; \
mark “insufficient corpus coverage”.

Output format (Markdown, no emoji):

## Candidate research gap summary
[Briefly list tools used, data coverage, and corpus-size limits]

## Candidate research gap list

### Candidate gap 1: [direction name]
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
- If focus is set, **call corpus_focus_coverage first** and cite focus_subset size in corpus_limitations.
- Independently call KG tools (at least 3) to verify Opportunity Scout’s key quantitative claims.
- Must call limitation_temporal_profile and limitation_gap_status for the temporal dimension.
- Do not label a limitation as a persistent gap if temporal_status=declining and resolution_signal=moderate.
- May raise confidence if temporal_status=persistent and resolution_signal=none.
- For each gap, check supporting paper counts, avg_cite, impact_tier; do not over-extrapolate from a single low-cite paper.
- Corpus caveat: global.papers is full-corpus scale; the focus subset may be only tens of papers — do not mix them.
- If citation/IF data are missing (impact_tier=Unknown), note in corpus_limitations that enrich-s2 / import-if is needed.
- Distinguish true gaps, corpus non-coverage, and weak evidence (rules below).

Classification (strict):
- **false_gaps**: Scout numbers contradict tool results; or full-corpus scale used as focus evidence; \
or directly refuted by tools such as graph_disease_method_reach.
- **weak_evidence_gaps**: Clinically plausible, but focus subset too small, tools sparse, or inference \
only from “not found”; do not mark as false.
- **verified_gaps**: Every quantitative Scout claim has a matching field in this round’s tool outputs.

- Challenge small-sample extrapolation and whether unexplored combos may already be common outside this corpus.

Output format (strict JSON inside a ```json ... ``` fence):

```json
{
  "overall_confidence": <float, 0-10, overall trust in the Scout proposal>,
  "verified_gaps": [
    {"title": "...", "evidence": "tool-backed rationale", "confidence": <0-10>}
  ],
  "false_gaps": [
    {"title": "...", "reason": "why this is a false gap", "counter_evidence": "..."}
  ],
  "weak_evidence_gaps": [
    {"title": "...", "issue": "where evidence is weak", "suggestion": "how to strengthen"}
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
- Keep high-confidence gaps verified by the Evidence Reviewer; drop or downgrade false_gaps.
- For weak_evidence_gaps, either require softer wording or explicitly mark evidence limits.
- In Data summary, state corpus size and extracted-paper limits.
- **Must** call literature_data_cross_matrix (or literature_impact_priority_matrix) and pathology_disease_catalog; \
append “Fangxin data support” and “Literature impact” (avg_cite, impact_tier, cross_priority_score) to each gap.
- Prefer crossings of “literature gap + adequate Fangxin data + impact_tier High/Medium”.
- All quantitative claims must cite tool data; no emoji.

If overall_confidence >= 7.5 or this is the last debate round, output the full final report (Markdown):

## Data summary
[Tools called, record counts, corpus scale, Review consensus score]

## Research gap analysis

### Research gap 1: [direction name]
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
| Rank | Direction | Difficulty | Novelty | Impact tier | cross_priority_score | Clinical value |
|------|-----------|------------|---------|-------------|----------------------|----------------|

## Overall recommendation
[150–200 words of strategic advice]

## Review process summary
[Key Scout vs Reviewer disagreements and Final Synthesizer rulings]

---
If confidence is insufficient and this is not the last round, output JSON (```json ... ```):
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
) -> Generator[dict, None, None]:
    """Debate multi-agent gap identification loop."""
    focus = normalize_focus(focus)
    yield {
        "type": "start",
        "focus": focus,
        "top_n": top_n,
        "max_debate_rounds": max_debate_rounds,
    }

    corpus_ctx = _corpus_context(focus)
    focus_hint = _focus_hint(focus)
    memory_block = resolve_ops_memory_block(focus, use_ops_memory)
    debate_tools = bind_tools_with_focus(GAP_TOOLS, focus)
    moderator_tools = bind_tools_with_focus(GAP_FEASIBILITY_TOOLS, focus)

    optimist_proposal = ""
    skeptic_review: dict = {}
    final_report = ""
    final_confidence = 0.0
    completed_rounds = 0
    debate_feedback: dict = {}

    for round_num in range(1, max_debate_rounds + 1):
        yield {
            "type": "debate_round_start",
            "round": round_num,
            "max_rounds": max_debate_rounds,
        }

        # ── Optimist ──────────────────────────────────────────────────────
        yield {"type": "phase_start", "round": round_num, "role": "optimist"}

        if round_num == 1:
            coverage_first = (
                "First step: call corpus_focus_coverage (when focus is set).\n"
                if focus
                else ""
            )
            opt_user = _append_memory_block(
                f"Identify {top_n} pathomics/radiomics research-gap candidates in English.\n"
                f"{coverage_first}"
                f"{focus_hint}\n{corpus_ctx}\n"
                "Then call at least 5 tools (including 1 graph_*), "
                "and finally output the candidate-gap Markdown.",
                memory_block,
            )
        else:
            opt_user = _append_memory_block(
                f"Previous Final Synthesizer feedback:\n"
                f"**Revision priority**: {debate_feedback.get('revision_priority', '')}\n"
                f"**Revise**: {debate_feedback.get('gaps_to_revise', [])}\n"
                f"**Drop**: {debate_feedback.get('gaps_to_drop', [])}\n\n"
                f"Evidence Reviewer corpus-limitation note: "
                f"{skeptic_review.get('corpus_limitations', '')}\n\n"
                f"{focus_hint}\n\n"
                f"Revise the candidate gaps (still output {top_n} items in English); "
                "gather more tool evidence before writing Markdown.",
                memory_block,
            )

        opt_messages: list[dict] = [
            {"role": "system", "content": _system_with_focus(OPTIMIST_SYSTEM_PROMPT, focus, role="optimist")},
            {"role": "user", "content": opt_user},
        ]
        yield from run_tool_agent(
            messages=opt_messages,
            tools=debate_tools,
            tool_schemas=GAP_TOOL_SCHEMAS,
            role="optimist",
            max_iters=18,
            temperature=0.45,
        )
        optimist_proposal = last_assistant_content(opt_messages)
        yield {"type": "optimist_proposal", "round": round_num, "content": optimist_proposal}

        # ── Skeptic ───────────────────────────────────────────────────────
        yield {"type": "phase_start", "round": round_num, "role": "skeptic"}

        ske_user = _append_memory_block(
            f"Cross-check the following Opportunity Scout candidates (round {round_num}):\n\n"
            f"{optimist_proposal}\n\n"
            f"{focus_hint}\n{corpus_ctx}\n"
            + (
                "Call corpus_focus_coverage first, then at least 3 tools to verify key claims.\n"
                if focus
                else "Call at least 3 tools first to verify key claims, "
            )
            + "then output the required JSON (verified / weak_evidence / false).",
            memory_block,
        )
        ske_messages: list[dict] = [
            {"role": "system", "content": _system_with_focus(SKEPTIC_SYSTEM_PROMPT, focus, role="skeptic")},
            {"role": "user", "content": ske_user},
        ]
        yield from run_tool_agent(
            messages=ske_messages,
            tools=debate_tools,
            tool_schemas=GAP_TOOL_SCHEMAS,
            role="skeptic",
            max_iters=12,
            temperature=0.3,
        )
        skeptic_text = last_assistant_content(ske_messages)
        skeptic_review = parse_json_block(
            skeptic_text,
            fallback={
                "overall_confidence": 5.0,
                "verified_gaps": [],
                "false_gaps": [],
                "weak_evidence_gaps": [],
                "corpus_limitations": skeptic_text[:500],
                "data_concerns": [],
                "revision_priority": skeptic_text[:300],
            },
        )
        confidence = float(skeptic_review.get("overall_confidence", 5.0))
        verified = skeptic_review.get("verified_gaps", [])
        false_g = skeptic_review.get("false_gaps", [])
        yield {
            "type": "skeptic_review",
            "round": round_num,
            "content": skeptic_text,
            "confidence": confidence,
            "verified_count": len(verified) if isinstance(verified, list) else 0,
            "false_count": len(false_g) if isinstance(false_g, list) else 0,
        }

        # ── Moderator ─────────────────────────────────────────────────────
        yield {"type": "phase_start", "round": round_num, "role": "moderator"}

        is_last = round_num == max_debate_rounds
        mod_user = _append_memory_block(
            f"Synthesize Opportunity Scout and Evidence Reviewer outputs into a final "
            f"{top_n}-gap research report in English.\n\n"
            f"**Opportunity Scout proposal**:\n{optimist_proposal}\n\n"
            f"**Evidence Reviewer verification** (confidence={confidence:.1f}/10):\n"
            f"```json\n{json.dumps(skeptic_review, ensure_ascii=False, indent=2)[:3000]}\n```\n\n"
            f"{focus_hint}\n{corpus_ctx}\n"
            f"Round {round_num}/{max_debate_rounds}."
            + (
                " This is the last round — output the complete Markdown final report."
                if is_last
                else (
                    f" If Evidence Reviewer confidence >= {accept_score}, "
                    "output the complete Markdown report; otherwise output revision JSON."
                )
            ),
            memory_block,
        )
        mod_messages: list[dict] = [
            {"role": "system", "content": _system_with_focus(MODERATOR_SYSTEM_PROMPT, focus, role="moderator")},
            {"role": "user", "content": mod_user},
        ]
        yield from run_tool_agent(
            messages=mod_messages,
            tools=moderator_tools,
            tool_schemas=GAP_FEASIBILITY_SCHEMAS,
            role="moderator",
            max_iters=10,
            temperature=0.35,
            max_tokens=max(config.LLM_MAX_TOKENS, 8192),
        )
        mod_text = last_assistant_content(mod_messages)
        completed_rounds = round_num

        mod_json = parse_json_block(mod_text, fallback={})
        accept = bool(mod_json.get("accept", False))
        mod_confidence = float(
            mod_json.get("overall_confidence", confidence)
        )

        if "```json" in mod_text and not mod_text.strip().startswith("#"):
            debate_feedback = mod_json
            yield {
                "type": "debate_feedback",
                "round": round_num,
                "revision_priority": mod_json.get("revision_priority", ""),
                "content": mod_text,
            }
            if not is_last and mod_confidence < accept_score:
                continue

        final_report = mod_text
        final_confidence = mod_confidence if mod_confidence else confidence

        if (confidence >= accept_score or is_last or accept or
                final_report.strip().startswith("#")):
            break

    yield {
        "type": "final",
        "content": final_report or optimist_proposal,
        "rounds": completed_rounds,
        "confidence": final_confidence,
    }


def run_gap_debate_agent(
    focus: str | None = None,
    top_n: int = 6,
    max_debate_rounds: int = 2,
    verbose: bool = False,
    use_ops_memory: bool | None = None,
) -> str:
    print(f"\n{'='*60}")
    print("Gap Debate Multi-Agent — pathomics/radiomics")
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
    ):
        etype = event["type"]
        if etype == "debate_round_start":
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
