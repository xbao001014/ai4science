"""
idea_agent.py — Adversarial Multi-Agent Research Proposal Generation

Adapted for fulltext_workflow (pathomics/radiomics, evidence-aware KG).
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
               COUNT(DISTINCT r_ds.source_pmid) AS used_by_papers
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_ds ON r_ds.source_pmid = p.pmid
        JOIN entities e_ds ON r_ds.object_id = e_ds.id
        WHERE r_ds.relation = 'USES_DATASET' AND e_ds.type = 'Dataset'
          {pmid_fc}
        GROUP BY e_ds.id ORDER BY used_by_papers DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Datasets in '{keyword}' research", "count": len(rows), "data": rows}


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
        "2-4 core terms preferred (e.g. 'habitat imaging breast cancer'); "
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
        "description": "List datasets used in research matching the keyword.",
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
        "description": "Modality (CT/MRI/WSI etc.) coverage for the topic.",
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
【锚定研究空白 — 全程不可更换主题】
用户选定的研究空白如下（方案必须始终围绕此主题，禁止改题）：
{gap_text}

硬性规则：
- 所有工具查询的 keyword/focus 必须与本空白中的疾病/任务相关（不得改查鼻咽癌、肺癌等其他病种）。
- 方信可行性请用 disease_id={disease_id}（{disease_reason}）；乳腺/乳腺癌课题 organ_system 用 breast/mammary，禁止 gynecological。
- 方信数据不足时：在方案中标注「数据对接局限」，**不得**更换为 API 返回的其他病种（如 BYA、鼻咽癌 survival）凑可行性。
- 修订轮次仅改进同一空白下的方案深度，不得替换为全新课题。
"""

_CRITIC_ANCHOR_EXTRA = """\
- 评审不得建议更换为其他病种或全新课题；feasibility 失败应要求补充乳腺/原病种数据路径，而非改做鼻咽癌等。
- feasibility_assess 的 disease_id 应与空白病种一致（推荐 {disease_id}），勿随意使用无关 API 返回 ID。
"""


def _short_tool_focus(gap_text: str) -> str:
    """Shorter focus string for graph tools (disease phrase)."""
    text = gap_text.strip()
    lower = text.lower()
    for phrase in (
        "bilateral breast cancer",
        "multifocal breast cancer",
        "breast cancer",
        "breast",
        "乳腺癌",
        "乳腺",
    ):
        if phrase in lower or phrase in text:
            return "Breast Cancer" if "breast" in phrase else phrase
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


def _gap_disease_hint(gap_text: str) -> tuple[str, str]:
    disease_id, conf, reason = map_gap_to_disease(gap_text)
    if disease_id:
        return disease_id, f"{reason} (confidence {conf:.2f})"
    return "BRCA-IDC", "default for breast-related gaps; verify via D-01 if different"


def _gap_anchor_block(gap_text: str) -> str:
    disease_id, disease_reason = _gap_disease_hint(gap_text)
    return _GAP_ANCHOR_RULES.format(
        gap_text=gap_text.strip(),
        disease_id=disease_id,
        disease_reason=disease_reason,
    )


def _system_with_gap_anchor(base: str, gap_text: str, *, role: str) -> str:
    if not gap_text or not gap_text.strip():
        return base
    extra = _gap_anchor_block(gap_text)
    if role == "critic":
        disease_id, _ = _gap_disease_hint(gap_text)
        extra += _CRITIC_ANCHOR_EXTRA.format(disease_id=disease_id)
    return base + "\n\n" + extra


GENERATOR_SYSTEM_PROMPT = """\
你是一位 pathomics/radiomics 科研方案设计专家，擅长将影像组学/病理组学与深度学习结合，
设计具有临床价值、技术创新性和可执行性的研究方案。

你参与 Generator x Critic 迭代优化流程：
- 第一轮：根据研究空白生成完整初始方案（v1）。
- 后续轮次：根据 Critic 反馈修订方案。

工具使用规则：
- 调用 SQL 工具 + graph_* 图工具 + 方信可行性工具（至少 5 个工具，含 1 个 graph_*）。
- 优先使用 metrics_for_topic（含 evidence_quote）和 author_limitations_for_topic。
- 使用 pathology_disease_catalog / pathology_tasks_for_disease 确认方信 Mock 数据支撑。
- 最后一轮回复必须是**完整方案正文**（含全部章节），禁止只写「让我调用某工具」而不输出方案。
- 工具查询完成后，必须再发一条**不含 tool_calls** 的最终消息输出完整 Markdown。

输出完整 Markdown 方案，末尾添加：
REVISION_NOTE: <50字内说明本版本核心改动，第一版写"初始版本">

必须在方案末尾增加结构化数据对接段落：

## 九、方信数据对接参数
- **disease_id**: <如 GC-ADC>
- **task_type**: <如 survival_prediction>
- **required_labels**: [<标注字段列表>]
- **required_molecular_markers**: [<分子标记列表，无则写 none>]
- **required_annotations**: [<病理标注列表>]
- **min_followup_months**: <整数或 N/A>

方案结构：
## 一、研究背景与立项依据
## 二、研究目标（总体 + 3-4条具体目标）
## 三、研究内容（3个模块，各200字以上）
## 四、技术路线（含具体 AI 架构，非泛泛"深度学习"）
## 五、临床研究方案（设计、纳入排除、样本量、伦理）
## 六、创新点（临床选题 + AI 架构 + 转化应用）
## 七、预期成果与影响
## 八、研究计划（2-3年季度时间线）

禁止 emoji。
"""

CRITIC_SYSTEM_PROMPT = """\
你是一位严格的 pathomics/radiomics 同行评审专家（Critic Agent）。

评审原则：
- 调用 KG 工具核实方案中的数据声明（至少 2 个工具）。
- **必须**调用 feasibility_assess (V-01) 核验方案中的 disease_id / task_type / 标签需求。
- 若 feasibility_score < 0.5，technical_feasibility 不得高于 5 分，且 accept 必须为 false。
- 若 feasibility_score >= 0.8 且 available_cohort_size >= 500，可在评审中注明「方信数据可行」。
- 核查 evidence_quote 是否与声明一致；指出 extracted corpus 规模局限。
- 五维评分（各20分，总分100，换算10分制）：科学严谨性、技术可行性、临床价值、创新性、完整性。
- 7分以下需实质修改；8分以上可 accept。

输出严格 JSON（```json ... ```）：
{
  "overall_score": <float, 0-10>,
  "accept": <bool>,
  "feasibility_score": <float, 0-1, 来自 feasibility_assess>,
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

禁止 emoji。
"""

ACCEPT_SCORE = 8.0

_FINALIZE_PROPOSAL_INSTRUCTION = """\
你已完成（或应当已完成）知识图谱工具查询。请**立即**输出完整 Markdown 研究方案：
- 必须包含九个章节（一至八 + 方信数据对接参数）及末尾 REVISION_NOTE 行
- 不要调用任何工具；不要只写计划或「让我检查…」
- 基于上文工具返回的数据撰写，缺数据处注明语料局限
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
        f"请输出方案 v{round_num}。"
    )
    finalized = finalize_assistant_content(gen_messages, instruction=instruction).strip()
    return (finalized or text), bool(finalized)


def stream_idea_agent(
    gap_text: str,
    gap_data: dict | None = None,
    max_rounds: int = 3,
    accept_score: float = ACCEPT_SCORE,
) -> Generator[dict, None, None]:
    yield {"type": "start", "gap_text": gap_text, "max_rounds": max_rounds}

    gap_context = ""
    disease_id, disease_reason = _gap_disease_hint(gap_text)
    gap_context = (
        f"\n\n方信病种映射建议：disease_id={disease_id} ({disease_reason})"
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

    for round_num in range(1, max_rounds + 1):
        yield {"type": "round_start", "round": round_num, "max_rounds": max_rounds}

        if round_num == 1:
            gen_user = (
                f"请针对以下 pathomics/radiomics 研究空白，生成完整研究方案（v1）：\n\n"
                f"{anchor_block}\n\n"
                f"**研究空白**：\n{gap_text}\n{gap_context}\n\n"
                "先调用至少 5 个工具（含 1 个 graph_*），再输出完整方案。"
            )
        else:
            issues_text = "\n".join(
                f"  [{item.get('section', '')}] {item.get('issue', '')}  "
                f"→ 建议：{item.get('suggestion', '')}"
                for item in last_feedback.get("critical_issues", [])
            )
            gen_user = (
                f"{anchor_block}\n\n"
                f"**锚定研究空白（不可改题）**：\n{gap_text}\n\n"
                f"评审反馈（v{round_num - 1}）：\n"
                f"**评分**：{last_feedback.get('overall_score', 0):.1f}/10\n"
                f"**修改方向**：{last_feedback.get('revision_priority', '')}\n"
                f"**问题列表**：\n{issues_text}\n"
                f"**KG核实**：{last_feedback.get('kg_verification', '')}\n\n"
                f"请在同一研究空白下生成修订方案（v{round_num}），不得更换疾病或课题；"
                "必要时先补充工具证据。"
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
            yield {
                "type": "final",
                "content": "",
                "rounds": completed_rounds,
                "final_score": final_score,
                "aborted": True,
            }
            return
        yield {"type": "draft", "round": round_num, "content": current_draft}

        if agent_failed:
            break

        critic_user = (
            f"{anchor_block}\n\n"
            f"请评审以下研究方案（v{round_num}）：\n\n"
            f"**原始空白（评审不得偏离）**：\n{gap_text}\n\n"
            f"**方案**：\n{current_draft}\n\n"
            f"方信 feasibility 请优先使用 disease_id={disease_id}。\n"
            "先调用 feasibility_assess 核验方信数据可行性，再调用至少 1 个 KG 工具核实关键声明，"
            "最后输出 JSON 评审。"
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
        feas_score = float(last_feedback.get("feasibility_score") or 1.0)
        accept = bool(last_feedback.get("accept", False)) or final_score >= accept_score
        if feas_score < config.FEASIBILITY_SCORE_MARGINAL:
            accept = False
        completed_rounds = round_num

        yield {
            "type": "feedback",
            "round": round_num,
            "content": critic_text,
            "score": final_score,
            "accept": accept,
            "dimension_scores": last_feedback.get("dimension_scores", {}),
            "strengths": last_feedback.get("strengths", []),
            "critical_issues": last_feedback.get("critical_issues", []),
            "revision_priority": last_feedback.get("revision_priority", ""),
        }

        if accept or round_num == max_rounds:
            break

    yield {
        "type": "final",
        "content": current_draft,
        "rounds": completed_rounds,
        "final_score": final_score,
    }


def run_idea_agent(
    gap_text: str,
    gap_data: dict | None = None,
    max_rounds: int = 3,
    verbose: bool = False,
) -> str:
    print(f"\n{'='*60}")
    print("Research Proposal — Generator x Critic")
    print(f"  Gap: {gap_text[:80]}...")
    print(f"  Max rounds: {max_rounds}")
    print(f"{'='*60}\n")

    proposal = ""
    for event in stream_idea_agent(gap_text=gap_text, gap_data=gap_data, max_rounds=max_rounds):
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
        elif etype == "final":
            proposal = event["content"]
            print(f"\nFinalised after {event['rounds']} round(s), score {event['final_score']:.1f}/10\n")
        elif etype == "error":
            print(f"\n[warning] {event['content']}")
    return proposal


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

    proposal = run_idea_agent(gap_text=gap_text, max_rounds=args.rounds, verbose=args.verbose)

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
