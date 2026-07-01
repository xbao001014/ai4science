"""
idea_agent.py
Research Proposal Generation — Adversarial Multi-Agent Loop

Architecture
------------
  Round 1 … N:
    Generator Agent  →  queries KG tools  →  produces / revises draft proposal
    Critic Agent     →  queries KG tools to fact-check  →  structured feedback + score
    If score >= ACCEPT_SCORE  OR  round == max_rounds  →  finalise

Both agents share the full tool set:
  - 9 SQL / relational KG tools  (defined here)
  - 5 Graph traversal tools      (imported from graph_tools.py)

Event stream (yielded dicts):
  {"type": "start",        "gap_text": ...}
  {"type": "round_start",  "round": N, "max_rounds": M}
  {"type": "tool_call",    "role": "generator"|"critic", "name": ..., "args": {...}, "call_id": ...}
  {"type": "tool_result",  "role": ..., "name": ..., "result": {...}, "call_id": ...}
  {"type": "tool_error",   "role": ..., "name": ..., "error": ...,   "call_id": ...}
  {"type": "thinking",     "role": ..., "content": ...}
  {"type": "draft",        "round": N, "content": ...}
  {"type": "feedback",     "round": N, "content": ..., "score": float, "accept": bool,
                           "dimension_scores": {...}, "strengths": [...], "critical_issues": [...]}
  {"type": "final",        "content": ..., "rounds": N, "final_score": float}
  {"type": "error",        "content": ...}
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime
from typing import Any, Generator

from openai import OpenAI

import config
from utils.db import get_conn, init_db
from graph_tools import GRAPH_TOOLS, GRAPH_TOOL_SCHEMAS

# ─────────────────────────────────────────────────────────────────────────────
# LLM client
# ─────────────────────────────────────────────────────────────────────────────
_client = OpenAI(
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_API_BASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# KG SQL tools
# ─────────────────────────────────────────────────────────────────────────────

def _q(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def tool_related_papers(keyword: str) -> dict:
    rows = _q(f"""
        SELECT DISTINCT p.title, p.year, p.journal_name, p.citation_count,
               p.study_type, p.abstract
        FROM papers p
        JOIN relations r ON r.source_pmid = p.pmid
        JOIN entities e ON r.object_id = e.id
        WHERE LOWER(e.name) LIKE LOWER('%{keyword}%')
           OR LOWER(p.title) LIKE LOWER('%{keyword}%')
        ORDER BY p.citation_count DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Papers related to '{keyword}'", "count": len(rows), "data": rows}


def tool_methods_for_topic(keyword: str) -> dict:
    rows = _q(f"""
        SELECT e_m.name AS method,
               COUNT(DISTINCT r_m.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite,
               MIN(p.year) AS first_used,
               MAX(p.year) AS last_used
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_m ON r_m.source_pmid = p.pmid
        JOIN entities e_m ON r_m.object_id = e_m.id
        WHERE r_m.relation = 'APPLIES_METHOD' AND e_m.type = 'Method'
          AND (LOWER(e_d.name) LIKE LOWER('%{keyword}%')
               OR LOWER(p.title) LIKE LOWER('%{keyword}%'))
        GROUP BY e_m.id
        ORDER BY paper_cnt DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"AI methods used in '{keyword}' research", "count": len(rows), "data": rows}


def tool_datasets_for_topic(keyword: str) -> dict:
    rows = _q(f"""
        SELECT e_ds.name AS dataset,
               COUNT(DISTINCT r_ds.source_pmid) AS used_by_papers,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_ds ON r_ds.source_pmid = p.pmid
        JOIN entities e_ds ON r_ds.object_id = e_ds.id
        WHERE r_ds.relation = 'USES_DATASET' AND e_ds.type = 'Dataset'
          AND (LOWER(e_d.name) LIKE LOWER('%{keyword}%')
               OR LOWER(p.title) LIKE LOWER('%{keyword}%'))
        GROUP BY e_ds.id ORDER BY used_by_papers DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Datasets used in '{keyword}' research", "count": len(rows), "data": rows}


def tool_metrics_for_topic(keyword: str) -> dict:
    rows = _q(f"""
        SELECT e_mt.name AS metric, r_mt.metric_value,
               p.title, p.year, p.citation_count, p.journal_name
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_mt ON r_mt.source_pmid = p.pmid
        JOIN entities e_mt ON r_mt.object_id = e_mt.id
        WHERE r_mt.relation = 'ACHIEVES_METRIC' AND e_mt.type = 'Metric'
          AND (LOWER(e_d.name) LIKE LOWER('%{keyword}%')
               OR LOWER(p.title) LIKE LOWER('%{keyword}%'))
          AND r_mt.metric_value IS NOT NULL
        ORDER BY p.citation_count DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Performance metrics in '{keyword}' research", "count": len(rows), "data": rows}


def tool_tasks_for_topic(keyword: str) -> dict:
    rows = _q(f"""
        SELECT e_t.name AS task,
               COUNT(DISTINCT r_t.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id = e_d.id
        JOIN papers p ON r_d.source_pmid = p.pmid
        JOIN relations r_t ON r_t.source_pmid = p.pmid
        JOIN entities e_t ON r_t.object_id = e_t.id
        WHERE r_t.relation = 'PERFORMS_TASK' AND e_t.type = 'Task'
          AND (LOWER(e_d.name) LIKE LOWER('%{keyword}%')
               OR LOWER(p.title) LIKE LOWER('%{keyword}%'))
        GROUP BY e_t.id ORDER BY paper_cnt DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Computational tasks in '{keyword}' research", "count": len(rows), "data": rows}


def tool_clinical_studies_for_topic(keyword: str) -> dict:
    rows = _q(f"""
        SELECT DISTINCT p.title, p.year, p.journal_name, p.citation_count,
               p.abstract
        FROM papers p
        JOIN relations r ON r.source_pmid = p.pmid
        JOIN entities e ON r.object_id = e.id
        WHERE p.study_type = 'clinical_study'
          AND (LOWER(e.name) LIKE LOWER('%{keyword}%')
               OR LOWER(p.title) LIKE LOWER('%{keyword}%'))
        ORDER BY p.citation_count DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Clinical validation studies for '{keyword}'", "count": len(rows), "data": rows}


def tool_highcite_landmark_papers(keyword: str) -> dict:
    rows = _q(f"""
        SELECT DISTINCT p.title, p.year, p.journal_name,
               p.citation_count, p.study_type,
               p.abstract
        FROM papers p
        JOIN relations r ON r.source_pmid = p.pmid
        JOIN entities e ON r.object_id = e.id
        WHERE (LOWER(e.name) LIKE LOWER('%{keyword}%')
               OR LOWER(p.title) LIKE LOWER('%{keyword}%'))
          AND p.citation_count >= 50
        ORDER BY p.citation_count DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": f"Landmark papers (>=50 citations) for '{keyword}'", "count": len(rows), "data": rows}


def tool_foundation_model_methods(keyword: str = "") -> dict:
    rows = _q(f"""
        SELECT e.name AS method,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite,
               MIN(p.year) AS first_year
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        JOIN papers p ON r.source_pmid = p.pmid
        WHERE e.type = 'Method' AND r.relation = 'APPLIES_METHOD'
          AND p.study_type = 'foundation_model'
          {"AND LOWER(e.name) LIKE LOWER('%" + keyword + "%')" if keyword else ""}
        GROUP BY e.id HAVING paper_cnt >= 2
        ORDER BY avg_cite DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "Foundation/pretrained model methods in pathology AI", "count": len(rows), "data": rows}


def tool_emerging_tech_for_proposal(keyword: str = "") -> dict:
    rows = _q(f"""
        SELECT e.name AS method, MIN(p.year) AS first_year,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id = e.id
        JOIN papers p ON r.source_pmid = p.pmid
        WHERE e.type = 'Method' AND r.relation = 'APPLIES_METHOD'
          {"AND LOWER(e.name) LIKE LOWER('%" + keyword + "%')" if keyword else ""}
        GROUP BY e.id HAVING first_year >= 2023 AND paper_cnt >= 2
        ORDER BY avg_cite DESC LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "Emerging AI methods (2023+)", "count": len(rows), "data": rows}


# ─────────────────────────────────────────────────────────────────────────────
# Combined tool registry (SQL + Graph)
# ─────────────────────────────────────────────────────────────────────────────

_SQL_IDEA_TOOLS: dict[str, Any] = {
    "related_papers":             tool_related_papers,
    "methods_for_topic":          tool_methods_for_topic,
    "datasets_for_topic":         tool_datasets_for_topic,
    "metrics_for_topic":          tool_metrics_for_topic,
    "tasks_for_topic":            tool_tasks_for_topic,
    "clinical_studies_for_topic": tool_clinical_studies_for_topic,
    "highcite_landmark_papers":   tool_highcite_landmark_papers,
    "foundation_model_methods":   tool_foundation_model_methods,
    "emerging_tech_for_proposal": tool_emerging_tech_for_proposal,
}

IDEA_TOOLS: dict[str, Any] = {**_SQL_IDEA_TOOLS, **GRAPH_TOOLS}

_SQL_IDEA_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "related_papers",
        "description": "检索与研究空白相关的论文（标题、年份、期刊、引用数、摘要片段），了解已有工作全貌。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
    }},
    {"type": "function", "function": {
        "name": "methods_for_topic",
        "description": "列出该研究方向中已被使用的AI/算法方法，包括使用论文数和均引，用于了解当前技术现状并寻找技术创新点。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
    }},
    {"type": "function", "function": {
        "name": "datasets_for_topic",
        "description": "列出该研究方向已使用的数据集，评估数据可得性和benchmark缺口。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
    }},
    {"type": "function", "function": {
        "name": "metrics_for_topic",
        "description": "检索该方向已报告的性能指标及最优值，确定性能基线和提升空间。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
    }},
    {"type": "function", "function": {
        "name": "tasks_for_topic",
        "description": "列出该研究方向已执行的计算任务（分类/分割/预后预测等），识别任务覆盖空白。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
    }},
    {"type": "function", "function": {
        "name": "clinical_studies_for_topic",
        "description": "检索该方向已有的临床验证研究，了解临床转化现状，找出临床设计的创新空间。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
    }},
    {"type": "function", "function": {
        "name": "highcite_landmark_papers",
        "description": "获取该方向最高引的标志性论文（>=50引），这些是提案必须对比的代表性工作。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
    }},
    {"type": "function", "function": {
        "name": "foundation_model_methods",
        "description": "列出病理AI领域已使用的Foundation Model方法，为AI架构创新提供候选方案。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string", "description": "可选过滤"}}, "required": []}
    }},
    {"type": "function", "function": {
        "name": "emerging_tech_for_proposal",
        "description": "识别2023年后新兴AI方法，这些是可引入本研究的前沿技术创新点。",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string", "description": "可选过滤"}}, "required": []}
    }},
]

IDEA_TOOL_SCHEMAS: list[dict] = _SQL_IDEA_TOOL_SCHEMAS + GRAPH_TOOL_SCHEMAS


# ─────────────────────────────────────────────────────────────────────────────
# System prompts
# ─────────────────────────────────────────────────────────────────────────────

GENERATOR_SYSTEM_PROMPT = """\
你是一位专业的病理AI科研方案设计专家，擅长将病理学临床需求与人工智能技术深度结合，
设计具有临床价值、技术创新性和可执行性的研究方案。

你参与一个迭代优化流程：
- 第一轮：根据研究空白生成完整初始方案（方案 v1）。
- 后续轮次：根据评审专家（Critic Agent）的反馈，修改和完善方案，生成更高质量的版本。

工具使用规则：
- 你可以调用所有知识图谱工具（SQL统计工具 + 图遍历工具）收集背景证据。
- SQL工具适合计数统计；图遍历工具（graph_*）适合发现拓扑结构上的空白（PageRank、
  结构洞、社区孤立、多跳可达性等），两类工具互补，鼓励结合使用。
- 每次生成方案前至少调用 5 个工具，修订时如果 Critic 指出数据支撑不足，
  须先调用相关工具补充证据，再输出修订版本。

创新点优先级（鼓励多维度创新）：
  1. AI技术架构创新（如 graph_entity_pagerank 发现的被忽视枢纽方法）
  2. 临床选题创新（如 graph_disease_method_reach 发现的潜在可迁移技术）
  3. 两者兼有（最优）

输出要求：
- 每次输出完整方案（不要简写或省略章节）。
- 方案末尾添加一行标记：
    REVISION_NOTE: <50字内说明本版本相对上一版本的核心改动，第一版写"初始版本">
- 全文禁止使用任何表情符号或特殊Unicode图标。
- 技术路线需具体到模型架构（不能只说"使用深度学习"）。

方案格式（严格遵守 Markdown 结构）：

## 一、研究背景与立项依据
[基于工具检索结果，阐述研究现状、临床需求、研究空白，精确引用工具返回数值。400-600字。]

## 二、研究目标
### 2.1 总体目标
[一句话核心目标]
### 2.2 具体目标
[3-4条具体可量化目标，含技术指标或临床终点]

## 三、研究内容
### 3.1 [内容模块1]
[详细描述。200字以上。]
### 3.2 [内容模块2]
[详细描述。200字以上。]
### 3.3 [内容模块3]
[详细描述。200字以上。]

## 四、技术路线
### 4.1 总体技术路线
[从数据采集到模型训练到临床验证的完整流程。]
### 4.2 AI模型架构设计
[具体架构（如：ViT多尺度特征提取 + Transformer跨模态融合 + 生存分析头），说明架构创新点。]
### 4.3 数据处理与预处理流程
[WSI切片策略、patch提取、数据增强、标注规范、质控流程。]
### 4.4 实验设计与评估方案
[数据集划分、对比基线（至少3个引用具体工作）、评估指标、统计检验方法。]

## 五、临床研究方案
### 5.1 研究设计类型
### 5.2 纳入与排除标准
### 5.3 样本量估算
[基于统计学原理估算，给出具体数字。]
### 5.4 数据采集规范
### 5.5 伦理与合规

## 六、创新点
### 6.1 临床选题创新
### 6.2 AI技术架构创新
[必须对比已有方法说明创新幅度。]
### 6.3 转化应用创新（如适用）

## 七、预期成果与影响
### 7.1 科学产出
[目标期刊（具体期刊名称和当前IF）、专利、数据集。]
### 7.2 临床价值

## 八、研究计划
[按季度时间线，总周期 2-3 年，含关键里程碑。]

---
REVISION_NOTE: <本版本核心改动说明>
"""


CRITIC_SYSTEM_PROMPT = """\
你是一位严格的病理AI研究领域同行评审专家。你的职责是对研究方案进行严谨的批判性评估，
帮助方案设计者识别不足并提升质量。

评审原则：
- 基于证据：你可以调用知识图谱工具（SQL工具 + 图遍历工具）核实方案中的数据声明。
  例如：方案声称"该疾病仅有3篇论文"，你可以用 related_papers 验证；
  方案声称"该方法从未用于此疾病"，你可以用 graph_disease_method_reach 检验。
- 专业深度：从科学性、技术可行性、临床价值、创新性、研究设计严谨性五个维度评审。
- 建设性：不仅指出问题，还要提出具体的修改建议。
- 严格打分：不要轻易给出高分，7分以下说明需要实质修改，8分以上方可接受。

评分维度（各20分，总分100，换算为10分制）：
  A. 科学严谨性（数据引用准确性、研究假设可检验性）
  B. 技术可行性（架构设计具体性、计算资源可行性、数据可得性）
  C. 临床价值（选题的临床意义、临床设计的规范性、样本量估算合理性）
  D. 创新性（与已有工作的区分度，基于KG工具验证的客观评估）
  E. 完整性（各章节是否具体充分，格式是否规范）

输出格式（严格JSON，包裹在 ```json ... ``` 代码块内）：

```json
{
  "overall_score": <float, 0-10>,
  "accept": <bool, true 表示方案已足够好可接受>,
  "dimension_scores": {
    "scientific_rigor": <float, 0-10>,
    "technical_feasibility": <float, 0-10>,
    "clinical_value": <float, 0-10>,
    "innovation": <float, 0-10>,
    "completeness": <float, 0-10>
  },
  "strengths": [<优点1>, <优点2>, ...],
  "critical_issues": [
    {
      "section": "<涉及章节>",
      "issue": "<具体问题描述>",
      "evidence": "<引用KG工具数据说明问题所在，或直接说明逻辑问题>",
      "suggestion": "<具体修改建议>"
    }
  ],
  "kg_verification": "<说明你调用了哪些工具核实了哪些声明，以及结论>",
  "revision_priority": "<最重要的1-2条修改方向，指导生成agent的下一轮修订>"
}
```

全文（包括JSON内容）禁止使用任何表情符号或特殊Unicode图标。
"""


# ─────────────────────────────────────────────────────────────────────────────
# Internal: single-agent tool-calling loop
# ─────────────────────────────────────────────────────────────────────────────

def _run_tool_agent(
    messages: list[dict],
    tools: dict[str, Any],
    tool_schemas: list[dict],
    role: str,
    max_iters: int = 15,
    temperature: float = 0.4,
    max_tokens: int | None = None,
) -> Generator[dict, None, None]:
    """
    Internal generator: runs one agent (generator or critic) through its tool-calling loop.
    Yields typed events. The final assistant message is appended into `messages` in-place.
    """
    if max_tokens is None:
        max_tokens = config.LLM_MAX_TOKENS
    for _ in range(max_iters):
        response = _client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        # Emit any chain-of-thought alongside tool calls
        if msg.content and msg.tool_calls:
            yield {"type": "thinking", "role": role, "content": msg.content}

        finish = response.choices[0].finish_reason

        if not msg.tool_calls or finish == "stop":
            return  # caller reads final content from messages

        # Process tool calls
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            yield {
                "type": "tool_call",
                "role": role,
                "name": fn_name,
                "args": fn_args,
                "call_id": tc.id,
            }

            if fn_name in tools:
                try:
                    result = tools[fn_name](**fn_args)
                    result_str = json.dumps(result, ensure_ascii=False, indent=2)
                    if len(result_str) > 6000:
                        result_str = result_str[:6000] + "\n... [truncated]"
                    yield {
                        "type": "tool_result",
                        "role": role,
                        "name": fn_name,
                        "result": result,
                        "call_id": tc.id,
                    }
                except Exception as exc:
                    result_str = json.dumps({"error": str(exc)})
                    yield {
                        "type": "tool_error",
                        "role": role,
                        "name": fn_name,
                        "error": str(exc),
                        "call_id": tc.id,
                    }
            else:
                result_str = json.dumps({"error": f"Unknown tool: {fn_name}"})
                yield {
                    "type": "tool_error",
                    "role": role,
                    "name": fn_name,
                    "error": f"Unknown tool: {fn_name}",
                    "call_id": tc.id,
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })


def _last_assistant_content(messages: list[dict]) -> str:
    """Return the content of the last assistant message."""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            return m["content"]
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Helper: parse critic JSON feedback
# ─────────────────────────────────────────────────────────────────────────────

def _parse_critic_json(text: str) -> dict:
    import re
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except Exception:
        return {
            "overall_score": 5.0,
            "accept": False,
            "dimension_scores": {},
            "strengths": [],
            "critical_issues": [],
            "kg_verification": "JSON解析失败",
            "revision_priority": text[:500],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main adversarial loop
# ─────────────────────────────────────────────────────────────────────────────

ACCEPT_SCORE = 8.0


def stream_idea_agent(
    gap_text: str,
    gap_data: dict | None = None,
    max_rounds: int = 3,
    accept_score: float = ACCEPT_SCORE,
) -> Generator[dict, None, None]:
    """
    Adversarial multi-agent proposal generation loop.
    Yields typed event dicts (see module docstring).
    """
    yield {"type": "start", "gap_text": gap_text, "max_rounds": max_rounds}

    gap_context = ""
    if gap_data:
        gap_context = (
            "\n\n知识图谱分析提供的原始统计支撑数据：\n"
            f"```json\n{json.dumps(gap_data, ensure_ascii=False, indent=2)[:2000]}\n```"
        )

    current_draft: str = ""
    last_feedback: dict = {}
    final_score: float = 0.0
    completed_rounds: int = 0

    for round_num in range(1, max_rounds + 1):
        yield {"type": "round_start", "round": round_num, "max_rounds": max_rounds}

        # ── Generator turn ────────────────────────────────────────────────
        if round_num == 1:
            gen_user = (
                f"请针对以下研究空白方向，生成一份完整的病理AI研究方案（v1）：\n\n"
                f"**研究空白描述**：\n{gap_text}\n"
                f"{gap_context}\n\n"
                "请先通过工具查询相关论文、方法、数据集、图结构特征等背景信息（至少调用5个工具，"
                "包含至少1个图遍历工具 graph_*），再生成完整方案。"
            )
        else:
            issues_text = "\n".join(
                f"  [{item.get('section','')}] {item.get('issue','')}  "
                f"→  建议：{item.get('suggestion','')}"
                for item in last_feedback.get("critical_issues", [])
            )
            gen_user = (
                f"以下是你上一版方案（v{round_num - 1}）收到的同行评审反馈：\n\n"
                f"**综合评分**：{last_feedback.get('overall_score', 0):.1f}/10\n\n"
                f"**核心修改方向**：{last_feedback.get('revision_priority', '')}\n\n"
                f"**具体问题列表**：\n{issues_text}\n\n"
                f"**评审专家KG核实情况**：{last_feedback.get('kg_verification', '')}\n\n"
                f"请根据以上反馈生成修订方案（v{round_num}）。"
                "如有必要先调用工具补充数据证据，再输出完整方案（不得省略任何章节）。"
            )

        gen_messages: list[dict] = [
            {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
            {"role": "user",   "content": gen_user},
        ]

        yield from _run_tool_agent(
            messages=gen_messages,
            tools=IDEA_TOOLS,
            tool_schemas=IDEA_TOOL_SCHEMAS,
            role="generator",
            max_iters=20,
            temperature=0.45,
            max_tokens=config.LLM_MAX_TOKENS,
        )

        current_draft = _last_assistant_content(gen_messages)
        yield {"type": "draft", "round": round_num, "content": current_draft}

        # ── Critic turn ───────────────────────────────────────────────────
        critic_user = (
            f"请对以下病理AI研究方案（v{round_num}）进行严格同行评审。\n\n"
            f"**原始研究空白**：\n{gap_text}\n\n"
            f"**待评审方案**：\n\n{current_draft}\n\n"
            "请先使用知识图谱工具核实方案中的关键数据声明（至少调用2个工具），"
            "再输出规定格式的 JSON 评审意见。"
        )

        critic_messages: list[dict] = [
            {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
            {"role": "user",   "content": critic_user},
        ]

        yield from _run_tool_agent(
            messages=critic_messages,
            tools=IDEA_TOOLS,
            tool_schemas=IDEA_TOOL_SCHEMAS,
            role="critic",
            max_iters=12,
            temperature=0.3,
            max_tokens=config.LLM_MAX_TOKENS,
        )

        critic_text = _last_assistant_content(critic_messages)
        last_feedback = _parse_critic_json(critic_text)
        final_score = float(last_feedback.get("overall_score", 0.0))
        accept = bool(last_feedback.get("accept", False)) or final_score >= accept_score
        completed_rounds = round_num

        yield {
            "type": "feedback",
            "round": round_num,
            "content": critic_text,
            "score": final_score,
            "accept": accept,
            "dimension_scores":  last_feedback.get("dimension_scores", {}),
            "strengths":         last_feedback.get("strengths", []),
            "critical_issues":   last_feedback.get("critical_issues", []),
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


# ─────────────────────────────────────────────────────────────────────────────
# Synchronous CLI wrapper
# ─────────────────────────────────────────────────────────────────────────────

def run_idea_agent(
    gap_text: str,
    gap_data: dict | None = None,
    max_rounds: int = 3,
    verbose: bool = False,
) -> str:
    print(f"\n{'='*60}")
    print("Research Proposal — Adversarial Multi-Agent Loop")
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
            dims = event.get("dimension_scores", {})
            print(f"\n  [critic] score={event['score']:.1f}/10  accept={event['accept']}")
            if dims:
                print(f"           rigor={dims.get('scientific_rigor','?')} "
                      f"tech={dims.get('technical_feasibility','?')} "
                      f"clinical={dims.get('clinical_value','?')} "
                      f"innovation={dims.get('innovation','?')} "
                      f"completeness={dims.get('completeness','?')}")
            if event.get("revision_priority"):
                print(f"  [priority] {event['revision_priority'][:120]}")
        elif etype == "final":
            proposal = event["content"]
            print(f"\nFinalised after {event['rounds']} round(s), "
                  f"score {event['final_score']:.1f}/10\n")
        elif etype == "error":
            print(f"\n[warning] {event['content']}")
    return proposal


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Adversarial Research Proposal Agent")
    parser.add_argument("--gap",  "-g", default=None)
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
    print(proposal)
    print("=" * 60)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            header = textwrap.dedent(f"""\
                # 病理AI研究方案（对抗式多智能体生成）

                > 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
                > 研究空白：{gap_text[:100]}
                > 生成工具：idea_agent.py（Generator x Critic 迭代优化）

                ---

            """)
            f.write(header + proposal)
        print(f"\nProposal saved: {args.output}")
