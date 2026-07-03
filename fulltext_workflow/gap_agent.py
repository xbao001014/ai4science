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
【研究聚焦约束 — 必须遵守】
用户指定了研究主题：{focus}
- 所有候选空白、验证结论与最终报告必须**直接服务于该主题**（疾病/任务/方法须与之相关）。
- 每条空白的标题或研究问题中必须明确写出与「{focus}」的关联。
- **禁止**输出明显无关的空白（其他癌种、心脏毒性、与主题无关的影像模态等）。
- 若语料中该主题数据稀少，应在摘要中说明覆盖不足，**不得**用无关主题凑数。
- 调用 KG 工具时 focus 参数必须设为 "{focus}"（系统会自动注入，但仍请显式传入）。
"""

_SKEPTIC_FOCUS_EXTRA = """\
- 将偏离用户指定主题「{focus}」的候选空白列入 false_gaps，reason 注明 off-topic / 与聚焦主题无关。
- 不得为无关空白浪费篇幅；verified_gaps 仅保留与「{focus}」直接相关的条目。
"""

_MODERATOR_FOCUS_EXTRA = """\
- 最终报告中的每条 Research gap 必须与「{focus}」直接相关；剔除 Skeptic 标记的 off-topic 项。
- Data summary 中说明本报告在「{focus}」子语料上的覆盖范围。
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
        return "未指定聚焦方向，进行 pathomics/radiomics 全语料分析。"
    return (
        f"【强制聚焦】{foc}\n"
        f"- 仅分析与此主题直接相关的研究空白。\n"
        f"- 必须先调用 corpus_focus_coverage，再调用其他工具。\n"
        f"- 工具调用必须带 focus=\"{foc}\"。\n"
        f"- 禁止用全库论文总数替代 focus 子集规模。\n"
        f"- 禁止输出与「{foc}」无关的候选（如其他疾病领域的空白）。"
    )

OPTIMIST_SYSTEM_PROMPT = """\
你是一位病理AI/pathomics/radiomics 研究机会分析专家（Optimist Agent）。
你的职责是从知识图谱数据中识别具有学术与临床价值的研究空白，强调可行性与创新机会。

语料范围：pathomics/radiomics 2024-2025 全文提取知识图谱（作者自述 limitation、
results 章节 metric 证据、方法-疾病组合空白、图结构分析）。

工具使用规则：
- 若指定了 focus，**第一个工具调用必须是 corpus_focus_coverage**；摘要中必须写明 focus_subset.papers 与 global.papers 的区别。
- 调用至少 5 个工具，其中至少 1 个 graph_* 图遍历工具。
- 优先使用 limitation_temporal_profile / limitation_gap_status（局限时间画像 + 跟进信号）。
- 配合 author_stated_gaps / limitation_impact_rank（作者自述局限 + 引用影响力）。
- 使用 combo_gap_temporal 识别后期出现跟进的方法×疾病组合。
- 使用 hotspot_entities、recent_highcite_papers 识别高影响力前沿方向。
- 所有定量陈述必须引用工具返回的确切数值（含 first_year、recent_ratio、resolution_signal、avg_cite、impact_score）。
- focus 子集 papers < 30 时，禁止声称 persistent 时间趋势或引用全库规模；须标注「语料覆盖不足」。

输出格式（Markdown，禁止 emoji）：

## 候选研究空白摘要
[简述调用了哪些工具、数据覆盖范围、语料规模局限]

## 候选研究空白列表

### 候选空白 1：[方向名称]
**研究问题**：[可验证的科学问题]
**数据依据**：[精确引用工具数值，含 temporal_status / resolution_signal]
**时间画像**：[first_year–last_year, temporal_status, recent_ratio]
**机会论证**：[为何值得投入]
**可行性**：[数据/技术/临床可得性]
**预期影响**：[期刊方向、科学意义]

---
[重复至要求的 top_n 条]

## Optimist 总结
[100字内核心推荐]
"""

SKEPTIC_SYSTEM_PROMPT = """\
你是一位严格的病理AI研究空白审查专家（Skeptic Agent）。
你的职责是交叉验证 Optimist 提出的候选空白，识别假空白、证据不足和过度推断。

审查原则：
- 若指定 focus，**必须先调用 corpus_focus_coverage**，并在 corpus_limitations 中引用 focus_subset 规模。
- 独立调用知识图谱工具（至少 3 个）核实 Optimist 的关键数据声明。
- 必须调用 limitation_temporal_profile 与 limitation_gap_status 核查时间维度。
- 对 temporal_status=declining 且 resolution_signal=moderate 的 limitation，不得标为 persistent gap。
- 对 temporal_status=persistent 且 resolution_signal=none 的 limitation，可提升置信度。
- 对每条空白检查支撑论文数、avg_cite、impact_tier；单篇低引论文不得过度 extrapolate。
- 注意语料局限：global.papers 是全库规模；focus 子集可能仅数十篇，不得混用。
- 若 citation/IF 数据缺失（impact_tier=Unknown），在 corpus_limitations 中注明需运行 enrich-s2 / import-if。
- 区分「真空白」「语料未覆盖」「证据不足」三者，分类规则见下。

分类规则（严格执行）：
- **false_gaps**：Optimist 引用的数字与工具结果矛盾；或把全库规模当成 focus 证据；或与 graph_disease_method_reach 等工具直接反驳。
- **weak_evidence_gaps**：临床方向合理，但 focus 子集过小、工具数据稀疏、或仅能基于「未找到」推断；不得标为 false。
- **verified_gaps**：Optimist 每条定量声明均能在本轮工具输出中找到对应字段。

- 质疑小样本 extrapolation 和未探索组合在语料外是否已有大量工作。

输出格式（严格 JSON，包裹在 ```json ... ``` 代码块内）：

```json
{
  "overall_confidence": <float, 0-10, 对 Optimist 提案的整体可信度>,
  "verified_gaps": [
    {"title": "...", "evidence": "工具核实的依据", "confidence": <0-10>}
  ],
  "false_gaps": [
    {"title": "...", "reason": "为何是假空白", "counter_evidence": "..."}
  ],
  "weak_evidence_gaps": [
    {"title": "...", "issue": "证据不足点", "suggestion": "如何补强"}
  ],
  "corpus_limitations": "<语料规模、提取覆盖率等系统性局限>",
  "data_concerns": ["<具体数据问题1>", "..."],
  "revision_priority": "<给 Moderator/Optimist 的最重要修改方向>"
}
```

全文禁止使用 emoji。
"""

MODERATOR_SYSTEM_PROMPT = """\
你是一位病理AI研究战略综合专家（Final Synthesizer Agent）。
你的职责是综合 Opportunity Scout 的候选空白与 Evidence Reviewer 的交叉验证，产出最终研究空白报告。

（角色通俗称谓：Opportunity Scout=Optimist，Evidence Reviewer=Skeptic，Final Synthesizer=Moderator。
**面向用户的最终 Markdown 报告必须使用英文通俗称谓，禁止出现 Optimist/Skeptic/Moderator 英文旧角色名。**）

综合原则：
- 保留 Evidence Reviewer 验证通过的高置信空白；剔除或降级 false_gaps。
- 对 weak_evidence_gaps 要么要求降级表述，要么在报告中标注证据局限。
- 必须在「Data summary」中声明 corpus 规模与 extracted 论文数局限。
- **必须**调用 literature_data_cross_matrix（或 literature_impact_priority_matrix）与 pathology_disease_catalog，在每条研究空白中追加「Fangxin data support」与「Literature impact」（avg_cite、impact_tier、cross_priority_score）。
- 优先推荐「文献空白 + 方信 Mock 数据充足 + impact_tier 为 High/Medium」的交叉项。
- 报告章节标题与角色标签用英文；研究内容可用中文或英文，与语料一致即可。
- 所有定量陈述引用工具数据；禁止 emoji。

若 overall_confidence >= 7.5 或已达最后一轮辩论，输出完整最终报告（Markdown）：

## Data summary
[工具调用、记录数、语料规模、Review consensus score]

## Research gap analysis

### Research gap 1：[方向名称]
**Research question**：
**Evidence basis**：
**Temporal profile**：（first_year–last_year, temporal_status, recent_ratio）
**Follow-up signal**：（resolution_signal, followup_paper_cnt, first_followup_year）
**Feasibility analysis**：
**Fangxin data support**：（mock_cohort_size、data_support、可用 task_type）
**Literature impact**：（avg_cite、avg_if、impact_tier、cross_priority_score）
**Expected academic impact**：
**Main challenges**：
**Distinction from prior work**：
**Review consensus**：Opportunity Scout proposal / Evidence Reviewer conclusion
**Difficulty**：Low / Medium / High / Very high
**Novelty**：Moderate / High / Very high

---
[第 2 至 top_n 条，相同格式]

## Priority ranking
| Rank | Direction | Difficulty | Novelty | Impact tier | cross_priority_score | Clinical value |
|------|-----------|------------|---------|-------------|----------------------|----------------|

## Overall recommendation
[150-200 words strategic advice]

## Review process summary
[Opportunity Scout vs Evidence Reviewer key disagreements and Final Synthesizer ruling]

---
若置信度不足且非最后一轮，输出 JSON（```json ... ```）：
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
        "\n\n语料统计（必须在分析中引用）：",
        f"- 全库 PubMed 论文总数: {stats['papers']}",
        f"- 全库全文可用: {stats['fulltext_available']}",
        f"- 全库已 LLM 提取: {stats['extracted']}",
        f"- S2 引用已 enrichment: {stats.get('s2_enriched', 0)}",
        f"- 全文关系数: {stats['relations_fulltext']}",
    ]

    foc = normalize_focus(focus)
    sub = coverage.get("focus_subset")
    if foc and sub:
        lines.extend([
            f"\n**Focus「{foc}」子语料（topic-specific 声明只能用下列数字）**：",
            f"- Focus 论文数: {sub['papers']}（全库 {stats['papers']}，"
            f"占比 {coverage.get('coverage_ratio', 0):.2%}）",
            f"- Focus 已提取: {sub.get('extracted', 0)}",
            f"- Focus limitation 关系数: {sub.get('limitation_relations', 0)}",
            f"- Focus method 实体数: {sub.get('method_entities', 0)}",
            f"- analysis_ready (>=30 papers): {coverage.get('analysis_ready', False)}",
        ])
        for w in coverage.get("warnings") or []:
            lines.append(f"- 警告: {w}")

    return "\n".join(lines)


def stream_gap_debate_agent(
    focus: str | None = None,
    top_n: int = 6,
    max_debate_rounds: int = 2,
    accept_score: float = ACCEPT_DEBATE_SCORE,
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
                "第一步必须调用 corpus_focus_coverage（若已指定 focus）。\n"
                if focus
                else ""
            )
            opt_user = (
                f"请识别 {top_n} 条 pathomics/radiomics 研究空白候选。\n"
                f"{coverage_first}"
                f"{focus_hint}\n{corpus_ctx}\n"
                "再调用至少 5 个工具（含 1 个 graph_*），最后输出候选空白 Markdown。"
            )
        else:
            opt_user = (
                f"上一轮 Moderator 反馈：\n"
                f"**修改方向**：{debate_feedback.get('revision_priority', '')}\n"
                f"**需修订**：{debate_feedback.get('gaps_to_revise', [])}\n"
                f"**需删除**：{debate_feedback.get('gaps_to_drop', [])}\n\n"
                f"Skeptic 语料局限提醒：{skeptic_review.get('corpus_limitations', '')}\n\n"
                f"{focus_hint}\n\n"
                f"请修订候选空白（仍输出 {top_n} 条），先补充工具证据再输出 Markdown。"
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

        ske_user = (
            f"请交叉验证以下 Optimist 候选空白（第 {round_num} 轮）：\n\n"
            f"{optimist_proposal}\n\n"
            f"{focus_hint}\n{corpus_ctx}\n"
            + ("先调用 corpus_focus_coverage，再调用至少 3 个工具核实关键声明。\n"
               if focus else "先调用至少 3 个工具核实关键声明，")
            + "最后输出规定 JSON（区分 verified / weak_evidence / false）。"
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
        mod_user = (
            f"综合 Optimist 与 Skeptic 输出，产出最终 {top_n} 条研究空白报告。\n\n"
            f"**Optimist 提案**：\n{optimist_proposal}\n\n"
            f"**Skeptic 验证**（confidence={confidence:.1f}/10）：\n"
            f"```json\n{json.dumps(skeptic_review, ensure_ascii=False, indent=2)[:3000]}\n```\n\n"
            f"{focus_hint}\n{corpus_ctx}\n"
            f"当前第 {round_num}/{max_debate_rounds} 轮。"
            + ("这是最后一轮，必须输出完整 Markdown 最终报告。" if is_last else
               f"若 Skeptic confidence >= {accept_score}，输出完整 Markdown 报告；"
               "否则输出修订 JSON。")
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
