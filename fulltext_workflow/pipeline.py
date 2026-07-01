"""
End-to-end pipeline: 研究空白 → 数据可行性核验 → 假说生成

Orchestrates gap debate, V-01/V-02 feasibility, evolution, and idea generation.
"""
from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import config
from analysis.feasibility_tools import tool_literature_data_cross_matrix
from db.schema import db_stats, init_db, save_feasibility_assessment
from evolution_agent import evolve_hypothesis
from feasibility.client import PathologyDataClient
from feasibility.disease_mapper import map_gap_to_disease
from feasibility.hypothesis import HypothesisRequest
from feasibility.landscape import bootstrap_landscape
from gap_agent import run_gap_debate_agent, save_report
from idea_agent import run_idea_agent
from pipeline_utils import parse_gap_sections, parse_gap_titles


@dataclass
class GapFeasibilityResult:
    gap_title: str
    gap_text: str
    disease_id: str | None
    map_confidence: float
    map_reason: str
    hypothesis: HypothesisRequest | None = None
    assessment: dict[str, Any] = field(default_factory=dict)
    status: str = "PENDING"
    evolution_log: list[dict[str, Any]] = field(default_factory=list)
    proposal: str = ""


def ensure_prerequisites() -> dict[str, Any]:
    stats = db_stats()
    warnings: list[str] = []
    if stats["papers"] == 0:
        warnings.append("No papers in KG — run: python main.py run-all")
    if stats["extracted"] == 0:
        warnings.append("No extracted relations — run: python main.py extract")
    return {"stats": stats, "warnings": warnings}


def assess_gap_feasibility(
    gap_title: str,
    gap_text: str = "",
    client: PathologyDataClient | None = None,
) -> GapFeasibilityResult:
    client = client or PathologyDataClient()
    disease_id, confidence, reason = map_gap_to_disease(
        gap_title + " " + gap_text, client=client
    )
    result = GapFeasibilityResult(
        gap_title=gap_title,
        gap_text=gap_text or gap_title,
        disease_id=disease_id,
        map_confidence=confidence,
        map_reason=reason,
    )

    if not disease_id:
        result.status = "REJECTED_NO_DISEASE_MAPPING"
        return result

    hypothesis = HypothesisRequest.from_gap(
        gap_title=gap_title,
        disease_id=disease_id,
        gap_text=gap_text,
    )
    result.hypothesis = hypothesis

    assessment = client.assess_feasibility(hypothesis)
    result.assessment = assessment
    score = float(assessment.get("feasibility_score", 0))
    status = client.feasibility_status(score)

    if status == "REFINED":
        gap_analysis = client.gap_analysis(hypothesis)
        refined, evo_log = evolve_hypothesis(hypothesis, gap_analysis)
        result.evolution_log = evo_log
        result.hypothesis = refined
        assessment = client.assess_feasibility(refined)
        result.assessment = assessment
        score = float(assessment.get("feasibility_score", 0))
        status = client.feasibility_status(score)

    result.status = status
    save_feasibility_assessment(
        gap_title=gap_title,
        hypothesis_id=hypothesis.hypothesis_id,
        hypothesis=hypothesis.to_api_body(),
        score=score,
        status=status,
        assessment=assessment,
    )
    return result


def run_idea_pipeline(
    focus: str | None = None,
    top_n: int = 3,
    debate_rounds: int = 2,
    idea_rounds: int = 3,
    gap_report_path: str | None = None,
    skip_debate: bool = False,
    skip_ideas: bool = False,
    verbose: bool = False,
) -> tuple[str, list[GapFeasibilityResult]]:
    init_db()
    prereq = ensure_prerequisites()
    for w in prereq["warnings"]:
        print(f"[Pipeline][warn] {w}")

    landscape = bootstrap_landscape()
    if not landscape.get("skipped"):
        print(f"[Pipeline] Bootstrapped landscape: {landscape['disease_count']} diseases")

    if skip_debate and gap_report_path:
        with open(gap_report_path, encoding="utf-8") as f:
            gap_report = f.read()
        print(f"[Pipeline] Loaded gap report: {gap_report_path}")
    else:
        print("[Pipeline] Stage 1: Gap debate...")
        gap_report = run_gap_debate_agent(
            focus=focus,
            top_n=top_n,
            max_debate_rounds=debate_rounds,
            verbose=verbose,
        )
        debate_path = os.path.join(config.OUTPUT_DIR, "gap_debate_report.md")
        save_report(gap_report, debate_path, focus=focus)
        print(f"[Pipeline] Gap report saved: {debate_path}")

    sections = parse_gap_sections(gap_report)
    if not sections:
        titles = parse_gap_titles(gap_report)
        sections = [(t, t) for t in titles[:top_n]]

    sections = sections[:top_n]
    print(f"[Pipeline] Stage 2: Feasibility assessment for {len(sections)} gap(s)...")

    client = PathologyDataClient()
    results: list[GapFeasibilityResult] = []
    for title, text in sections:
        print(f"  Assessing: {title[:60]}...")
        fr = assess_gap_feasibility(title, text, client=client)
        results.append(fr)
        print(
            f"    disease_id={fr.disease_id} score={fr.assessment.get('feasibility_score')} "
            f"status={fr.status}"
        )

    if not skip_ideas:
        print("[Pipeline] Stage 3: Hypothesis / proposal generation...")
        for fr in results:
            if fr.status in ("REJECTED_DATA_INSUFFICIENT", "REJECTED_NO_DISEASE_MAPPING", "RISKY"):
                print(f"  Skipping idea for '{fr.gap_title[:40]}' (status={fr.status})")
                continue
            feas_ctx = {
                "feasibility_assessment": fr.assessment,
                "disease_id": fr.disease_id,
                "hypothesis": fr.hypothesis.to_api_body() if fr.hypothesis else {},
            }
            gap_full = f"{fr.gap_title}\n\n{fr.gap_text}"
            if fr.evolution_log:
                gap_full += f"\n\nEvolution log:\n{fr.evolution_log}"
            fr.proposal = run_idea_agent(
                gap_text=gap_full,
                gap_data=feas_ctx,
                max_rounds=idea_rounds,
                verbose=verbose,
            )
            if not fr.proposal:
                print(f"  [warn] No proposal generated for '{fr.gap_title[:40]}' (LLM error or empty draft)")

    markdown = render_pipeline_report(
        gap_report=gap_report,
        results=results,
        focus=focus,
        stats=prereq["stats"],
    )
    return markdown, results


def render_pipeline_report(
    gap_report: str,
    results: list[GapFeasibilityResult],
    focus: str | None,
    stats: dict[str, Any],
) -> str:
    cross = tool_literature_data_cross_matrix(focus=focus)
    approved = [r for r in results if r.status == "APPROVED"]
    refined = [r for r in results if r.status == "REFINED"]
    rejected = [r for r in results if r.status.startswith("REJECTED") or r.status == "RISKY"]
    with_proposals = [r for r in results if r.proposal]

    lines = [
        "# Idea Pipeline Report — 研究空白 → 数据可行性核验 → 假说生成",
        "",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> Focus: {focus or 'all'}",
        f"> Data source: Fangxin LIS API ({config.PATHOLOGY_API_BASE_URL})",
        "",
        "## Executive Summary",
        "",
        f"- Gaps processed: **{len(results)}**",
        f"- APPROVED (score ≥ {config.FEASIBILITY_SCORE_APPROVE}): **{len(approved)}**",
        f"- REFINED (evolution applied): **{len(refined)}**",
        f"- Rejected / risky: **{len(rejected)}**",
        f"- Proposals generated: **{len(with_proposals)}**",
        "",
        "### Corpus Statistics",
        "",
        f"- Papers: {stats.get('papers', 0)}",
        f"- Extracted: {stats.get('extracted', 0)}",
        f"- Relations (fulltext): {stats.get('relations_fulltext', 0)}",
        "",
        "## Gap × Data Cross Matrix (top entries)",
        "",
        _format_cross_table(cross.get("data", [])[:15]),
        "",
        "## Feasibility Assessments",
        "",
    ]

    for i, fr in enumerate(results, 1):
        assess = fr.assessment
        lines.extend([
            f"### {i}. {fr.gap_title}",
            "",
            f"- **disease_id**: {fr.disease_id} (mapping confidence: {fr.map_confidence:.2f}, {fr.map_reason})",
            f"- **status**: {fr.status}",
            f"- **feasibility_score**: {assess.get('feasibility_score', 'N/A')}",
            f"- **available_cohort_size**: {assess.get('available_cohort_size', 'N/A')}",
            f"- **recommendation**: {assess.get('recommendation', 'N/A')}",
            f"- **note**: {assess.get('note', '')}",
            "",
        ])
        breakdown = assess.get("breakdown")
        if breakdown:
            lines.append("**Breakdown:**")
            lines.append("```json")
            import json
            lines.append(json.dumps(breakdown, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

    evo_entries = [r for r in results if r.evolution_log]
    if evo_entries:
        lines.extend(["## Evolution Log", ""])
        for fr in evo_entries:
            lines.append(f"### {fr.gap_title}")
            import json
            lines.append("```json")
            lines.append(json.dumps(fr.evolution_log, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

    if with_proposals:
        lines.extend(["## Research Proposals", ""])
        for fr in with_proposals:
            lines.extend([
                f"### Proposal: {fr.gap_title}",
                "",
                fr.proposal,
                "",
                "---",
                "",
            ])

    lines.extend([
        "## Source Gap Report (excerpt)",
        "",
        gap_report[:4000] + ("..." if len(gap_report) > 4000 else ""),
    ])
    return "\n".join(lines)


def _format_cross_table(rows: list[dict]) -> str:
    if not rows:
        return "_No cross-matrix data._"
    header = "| Method | Disease | Lit.Gap | Cohort | Impact | Priority |"
    sep = "| --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| {r.get('method', '')[:30]} | {r.get('disease', '')[:25]} | "
            f"{r.get('literature_gap', '')} | {r.get('mock_cohort_size', 0)} | "
            f"{r.get('impact_tier', '—')} ({r.get('avg_cite', 0)}) | "
            f"{r.get('cross_priority_score', 0)} |"
        )
    return "\n".join(lines)


def save_pipeline_report(content: str, path: str) -> None:
    os.makedirs(os.path.dirname(path) or config.OUTPUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[Pipeline] Report saved: {path}")
