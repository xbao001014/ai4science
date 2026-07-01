"""
gap_agent.py
病理AI研究空白挖掘 Agent

基于知识图谱数据 + LLM 推理，自动发现研究空白并推荐可执行研究方向。

运行方式:
    python gap_agent.py
    python gap_agent.py --focus "lung cancer"
    python gap_agent.py --focus "segmentation"
    python gap_agent.py --focus "foundation model"
    python gap_agent.py --focus "gastric cancer" --output report_gastric.md
    python gap_agent.py --top 8          # 推荐条数
    python gap_agent.py --verbose        # 打印 agent 推理过程
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime
from typing import Any

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
# ── KG 查询工具函数 ──────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _q(sql: str, params: tuple = ()) -> list[dict]:
    """Execute SQL and return list-of-dicts."""
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _focus_disease_filter(focus: str | None) -> str:
    """Return SQL snippet to filter by focus keyword in entity name."""
    if not focus:
        return ""
    return f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"


def tool_trend_overview(focus: str | None = None) -> dict:
    """
    年度发表量趋势：各 study_type 按年统计，可选按疾病或方法关键词过滤。
    返回整体研究趋势数据。
    """
    rows = _q("""
        SELECT year,
            SUM(CASE WHEN study_type='ai_algorithm'      THEN 1 ELSE 0 END) AS ai_algo,
            SUM(CASE WHEN study_type='clinical_study'    THEN 1 ELSE 0 END) AS clinical,
            SUM(CASE WHEN study_type='foundation_model'  THEN 1 ELSE 0 END) AS foundation,
            SUM(CASE WHEN study_type='multimodal'        THEN 1 ELSE 0 END) AS multimodal,
            SUM(CASE WHEN study_type='dataset_benchmark' THEN 1 ELSE 0 END) AS dataset,
            SUM(CASE WHEN study_type='review'            THEN 1 ELSE 0 END) AS review,
            COUNT(*) AS total
        FROM papers
        WHERE year BETWEEN 2018 AND 2025
        GROUP BY year ORDER BY year
    """)
    return {"description": "年度各类研究发表趋势", "data": rows}


def tool_hotspot_entities(focus: str | None = None) -> dict:
    """
    全局热点实体：按论文数 × 平均引用计算热度，可按关键词过滤。
    """
    focus_sql = _focus_disease_filter(focus)
    rows = _q(f"""
        SELECT e.name, e.type,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite,
               ROUND(COUNT(DISTINCT r.source_pmid) * AVG(p.citation_count), 0) AS heat_score
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE 1=1 {focus_sql}
        GROUP BY e.id
        HAVING paper_cnt >= 3
        ORDER BY heat_score DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "研究热点实体（热度=论文数×均引）", "data": rows}


def tool_disease_task_coverage(focus: str | None = None) -> dict:
    """
    疾病-任务覆盖度：有多少篇论文研究该疾病，但任务多样性低（研究视角单一）。
    task_variety 低 => 可能存在任务维度的研究空白。
    """
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e_d.name) LIKE LOWER('%{focus}%')"
    rows = _q(f"""
        SELECT e_d.name AS disease,
               COUNT(DISTINCT r_d.source_pmid) AS paper_cnt,
               COUNT(DISTINCT e_t.name) AS task_variety,
               GROUP_CONCAT(DISTINCT e_t.name) AS tasks
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id=e_d.id
        LEFT JOIN relations r_t ON r_d.source_pmid=r_t.source_pmid
            AND r_t.relation='PERFORMS_TASK'
        LEFT JOIN entities e_t ON r_t.object_id=e_t.id
        WHERE r_d.relation='TARGETS_DISEASE' AND e_d.type='Disease' {focus_sql}
        GROUP BY e_d.id
        HAVING paper_cnt >= 5
        ORDER BY task_variety ASC, paper_cnt DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "疾病-任务覆盖度（task_variety低=任务研究空白多）", "data": rows}


def tool_method_clinical_gap(focus: str | None = None) -> dict:
    """
    方法临床转化缺口：方法在算法论文中多，但临床研究少（clinical_ratio低）。
    这类方法是 '算法成熟但未临床验证' 的研究空白。
    """
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"
    rows = _q(f"""
        SELECT e.name AS method,
               SUM(CASE WHEN p.study_type='ai_algorithm'   THEN 1 ELSE 0 END) AS algo_cnt,
               SUM(CASE WHEN p.study_type='clinical_study' THEN 1 ELSE 0 END) AS clinical_cnt,
               COUNT(*) AS total_papers,
               ROUND(1.0 * SUM(CASE WHEN p.study_type='clinical_study' THEN 1 ELSE 0 END)
                         / COUNT(*), 3) AS clinical_ratio
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Method' AND r.relation='APPLIES_METHOD' {focus_sql}
        GROUP BY e.id
        HAVING algo_cnt >= 5 AND clinical_cnt <= 2
        ORDER BY algo_cnt DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "方法临床转化缺口（算法多、临床验证少）", "data": rows}


def tool_dataset_scarcity(focus: str | None = None) -> dict:
    """
    数据集稀缺的高频任务：任务论文多但公开数据集少，是 benchmark 构建机会。
    """
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e_t.name) LIKE LOWER('%{focus}%')"
    rows = _q(f"""
        SELECT e_t.name AS task,
               COUNT(DISTINCT r_t.source_pmid) AS paper_cnt,
               COUNT(DISTINCT e_d.name) AS dataset_variety,
               GROUP_CONCAT(DISTINCT e_d.name) AS datasets
        FROM relations r_t
        JOIN entities e_t ON r_t.object_id=e_t.id
        LEFT JOIN relations r_d ON r_t.source_pmid=r_d.source_pmid
            AND r_d.relation='USES_DATASET'
        LEFT JOIN entities e_d ON r_d.object_id=e_d.id AND e_d.type='Dataset'
        WHERE r_t.relation='PERFORMS_TASK' AND e_t.type='Task' {focus_sql}
        GROUP BY e_t.id
        HAVING paper_cnt >= 5 AND (dataset_variety IS NULL OR dataset_variety <= 2)
        ORDER BY paper_cnt DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "数据集稀缺的高频任务（benchmark构建机会）", "data": rows}


def tool_underexplored_disease(focus: str | None = None) -> dict:
    """
    高引但低论文量的疾病：有标志性论文但整体研究少，值得深入研究。
    """
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"
    rows = _q(f"""
        SELECT e.name AS disease,
               COUNT(DISTINCT r.source_pmid) AS total_papers,
               MAX(p.citation_count) AS max_citation,
               ROUND(AVG(p.citation_count), 1) AS avg_citation
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE' {focus_sql}
        GROUP BY e.id
        HAVING total_papers BETWEEN 2 AND 15
           AND max_citation >= 80
        ORDER BY max_citation DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "高引但低论文量的疾病（潜力方向）", "data": rows}


def tool_emerging_methods(focus: str | None = None) -> dict:
    """
    新兴方法（2023年后首次出现，但已积累>=3篇）及其应用的疾病/任务分布。
    """
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"
    rows = _q(f"""
        SELECT e.name AS method,
               MIN(p.year) AS first_year,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Method' AND r.relation='APPLIES_METHOD' {focus_sql}
        GROUP BY e.id
        HAVING first_year >= 2023 AND paper_cnt >= 3
        ORDER BY avg_cite DESC, paper_cnt DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "2023年后新兴方法（增长潜力大）", "data": rows}


def tool_method_disease_combo_gap(focus: str | None = None) -> dict:
    """
    热门方法 × 热门疾病的组合覆盖矩阵：
    找出哪些 (method, disease) 组合几乎没有论文（潜在空白）。
    """
    # Top methods
    top_methods = _q("""
        SELECT e.name
        FROM relations r JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Method' AND r.relation='APPLIES_METHOD'
        GROUP BY e.id ORDER BY COUNT(*) DESC LIMIT {config.TOOL_TOP_N}
    """)
    method_names = [r["name"] for r in top_methods]

    # Top diseases
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"
    top_diseases = _q(f"""
        SELECT e.name
        FROM relations r JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE' {focus_sql}
        GROUP BY e.id ORDER BY COUNT(*) DESC LIMIT {config.TOOL_TOP_N}
    """)
    disease_names = [r["name"] for r in top_diseases]

    if not method_names or not disease_names:
        return {"description": "方法-疾病组合矩阵", "data": []}

    # Actual combinations present
    rows = _q("""
        WITH pm AS (
            SELECT r.source_pmid, e.name AS method
            FROM relations r JOIN entities e ON r.object_id=e.id
            WHERE e.type='Method' AND r.relation='APPLIES_METHOD'
        ),
        pd AS (
            SELECT r.source_pmid, e.name AS disease
            FROM relations r JOIN entities e ON r.object_id=e.id
            WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE'
        )
        SELECT pm.method, pd.disease, COUNT(*) AS cnt
        FROM pm JOIN pd ON pm.source_pmid=pd.source_pmid
        GROUP BY pm.method, pd.disease
        ORDER BY cnt DESC
    """)

    # Build gap matrix: combos with 0 or very few papers
    existing = {(r["method"], r["disease"]): r["cnt"] for r in rows}
    gaps = []
    for m in method_names:
        for d in disease_names:
            cnt = existing.get((m, d), 0)
            if cnt == 0:
                gaps.append({"method": m, "disease": d, "paper_cnt": 0, "gap": "未探索"})
            elif cnt <= 2:
                gaps.append({"method": m, "disease": d, "paper_cnt": cnt, "gap": "极少研究"})

    return {
        "description": "热门方法×热门疾病的组合空白矩阵",
        "top_methods": method_names,
        "top_diseases": disease_names,
        "gaps": gaps[:40],
    }


def tool_foundation_model_gaps(focus: str | None = None) -> dict:
    """
    Foundation Model 的疾病应用分布：哪些疾病还没有 foundation model 研究。
    """
    fm_diseases = _q("""
        SELECT e.name AS disease, COUNT(DISTINCT r.source_pmid) AS fm_papers
        FROM relations r JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE'
          AND p.study_type='foundation_model'
        GROUP BY e.id
        ORDER BY fm_papers DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    fm_disease_set = {r["disease"] for r in fm_diseases}

    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"
    all_diseases = _q(f"""
        SELECT e.name AS disease, COUNT(DISTINCT r.source_pmid) AS total_papers
        FROM relations r JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE' {focus_sql}
        GROUP BY e.id
        HAVING total_papers >= 8
        ORDER BY total_papers DESC
        LIMIT {config.TOOL_TOP_N}
    """)

    no_fm = [r for r in all_diseases if r["disease"] not in fm_disease_set]
    return {
        "description": "有足量论文但尚无Foundation Model研究的疾病",
        "diseases_with_fm": fm_diseases,
        "diseases_without_fm": no_fm,
    }


def tool_multimodal_gaps(focus: str | None = None) -> dict:
    """
    多模态研究空白：哪些疾病/任务已有大量单模态论文，但多模态论文很少。
    """
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"
    rows = _q(f"""
        SELECT e.name AS entity, e.type,
               SUM(CASE WHEN p.study_type != 'multimodal' THEN 1 ELSE 0 END) AS unimodal_cnt,
               SUM(CASE WHEN p.study_type = 'multimodal'  THEN 1 ELSE 0 END) AS multimodal_cnt,
               ROUND(1.0 * SUM(CASE WHEN p.study_type='multimodal' THEN 1 ELSE 0 END)
                         / COUNT(*), 3) AS multimodal_ratio
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type IN ('Disease','Task') {focus_sql}
        GROUP BY e.id
        HAVING unimodal_cnt >= 10 AND multimodal_cnt <= 2
        ORDER BY unimodal_cnt DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "单模态论文多但多模态研究少的实体（多模态研究机会）", "data": rows}


def tool_recent_highcite_papers(focus: str | None = None) -> dict:
    """
    近2年高引论文（per-year引用高），用于了解当前研究前沿。
    """
    focus_sql = ""
    if focus:
        focus_sql = f"""
        AND p.pmid IN (
            SELECT DISTINCT r.source_pmid FROM relations r
            JOIN entities e ON r.object_id=e.id
            WHERE LOWER(e.name) LIKE LOWER('%{focus}%')
        )"""
    rows = _q(f"""
        SELECT p.title, p.year, p.study_type, p.citation_count,
               p.journal_name,
               ROUND(1.0*p.citation_count / MAX(2026-p.year, 1), 1) AS cite_per_year
        FROM papers p
        WHERE p.year BETWEEN 2023 AND 2025
          AND p.citation_count >= 30 {focus_sql}
        ORDER BY cite_per_year DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "近2年高引论文（代表研究前沿）", "data": rows}


def tool_method_cooccurrence(focus: str | None = None) -> dict:
    """
    方法协同出现网络（同一篇论文中同时使用的方法对，2023-2025年）。
    反映当前主流技术组合，帮助识别尚未被组合的方法。
    """
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(a.method) LIKE LOWER('%{focus}%')"
    rows = _q(f"""
        WITH pm AS (
            SELECT r.source_pmid, e.id AS eid, e.name AS method
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE r.relation='APPLIES_METHOD' AND e.type='Method'
              AND p.year >= 2023
        )
        SELECT a.method AS method_a, b.method AS method_b,
               COUNT(*) AS co_occurrence
        FROM pm a JOIN pm b ON a.source_pmid=b.source_pmid AND a.eid < b.eid
        WHERE 1=1 {focus_sql}
        GROUP BY a.eid, b.eid
        HAVING co_occurrence >= 3
        ORDER BY co_occurrence DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "方法协同出现网络（当前主流技术组合）", "data": rows}


def tool_low_impact_direction(focus: str | None = None) -> dict:
    """
    论文数多但期刊影响力低的研究方向：说明该方向缺少高质量研究，
    是发表高影响力论文的机会。
    """
    focus_sql = ""
    if focus:
        focus_sql = f" AND LOWER(e.name) LIKE LOWER('%{focus}%')"
    rows = _q(f"""
        SELECT e.name AS entity, e.type,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               MAX(j.impact_factor) AS max_if,
               ROUND(AVG(j.impact_factor), 2) AS avg_if
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        LEFT JOIN journals j ON p.journal_id=j.id
        WHERE e.type IN ('Disease','Task') {focus_sql}
        GROUP BY e.id
        HAVING paper_cnt >= 8 AND (max_if IS NULL OR max_if < 6)
        ORDER BY paper_cnt DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {"description": "论文多但影响力低的方向（高IF发表机会）", "data": rows}


# ─────────────────────────────────────────────────────────────────────────────
# ── Tool registry ────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

# SQL-based tools
_SQL_TOOLS: dict[str, Any] = {
    "trend_overview":           tool_trend_overview,
    "hotspot_entities":         tool_hotspot_entities,
    "disease_task_coverage":    tool_disease_task_coverage,
    "method_clinical_gap":      tool_method_clinical_gap,
    "dataset_scarcity":         tool_dataset_scarcity,
    "underexplored_disease":    tool_underexplored_disease,
    "emerging_methods":         tool_emerging_methods,
    "method_disease_combo_gap": tool_method_disease_combo_gap,
    "foundation_model_gaps":    tool_foundation_model_gaps,
    "multimodal_gaps":          tool_multimodal_gaps,
    "recent_highcite_papers":   tool_recent_highcite_papers,
    "method_cooccurrence":      tool_method_cooccurrence,
    "low_impact_direction":     tool_low_impact_direction,
}

# Merged tool registry: SQL tools + Graph traversal tools
TOOLS: dict[str, Any] = {**_SQL_TOOLS, **GRAPH_TOOLS}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "trend_overview",
            "description": "获取年度各类研究（算法/临床/基础模型/多模态）发表趋势，了解整体研究热度变化。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选关键词，按疾病或方法过滤（如 'lung cancer'，可为空）"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hotspot_entities",
            "description": "获取全局研究热点实体列表（按论文数×平均引用的热度分），可用关键词过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "disease_task_coverage",
            "description": "分析各疾病的任务覆盖多样性。task_variety低说明该疾病有研究但缺乏任务多样性（如仅有分类无分割/预后等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选疾病关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "method_clinical_gap",
            "description": "找出算法论文多但临床验证研究少的方法，这类方法是'算法成熟但缺临床验证'的研究空白。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选方法关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "dataset_scarcity",
            "description": "找出论文多但公开数据集少的任务，这是benchmark数据集构建的研究机会。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选任务关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "underexplored_disease",
            "description": "找出有高引标志性论文但整体研究量少的疾病，说明该方向有价值但待深入探索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选疾病关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "emerging_methods",
            "description": "找出2023年后首次出现且已有≥3篇论文的新兴方法，这些是技术前沿方向。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选方法关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "method_disease_combo_gap",
            "description": "计算热门方法×热门疾病的组合矩阵，找出哪些组合几乎无论文（未探索的方法-疾病组合）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选疾病关键词过滤（限制疾病轴范围）"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "foundation_model_gaps",
            "description": "分析Foundation Model的疾病应用分布，找出有足量论文但尚无FM研究的疾病（FM应用空白）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选疾病关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "multimodal_gaps",
            "description": "找出单模态论文多但多模态研究少的疾病/任务，这是引入多模态方法的研究机会。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recent_highcite_papers",
            "description": "获取近2年（2023-2025）高引论文，了解当前研究前沿和已有工作的内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选关键词过滤（疾病/方法/任务名称）"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "method_cooccurrence",
            "description": "分析2023-2025年方法的协同出现网络，了解主流技术组合，辅助识别尚未组合的方法对。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选方法关键词过滤"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "low_impact_direction",
            "description": "找出论文数多但期刊IF低的研究方向，这些方向缺少高质量研究，是发高影响力文章的机会。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "可选关键词过滤"}
                },
                "required": []
            }
        }
    },
    # ── 图遍历工具 Schema（由 graph_tools.py 提供）────────────────────────
    *GRAPH_TOOL_SCHEMAS,
]


# ─────────────────────────────────────────────────────────────────────────────
# ── Agent loop ───────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
你是一位病理AI领域的系统性研究分析助理，专注于基于知识图谱数据的研究空白识别与研究方向推荐。

分析目标：
1. 系统调用多个知识图谱查询工具（至少8个不同工具），全面收集病理AI研究现状数据。
   - SQL统计工具（13个）：聚合计数、均值、分组统计等关系型分析
   - 图遍历工具（5个）：基于NetworkX知识图谱拓扑结构的分析，能发现SQL无法识别的结构性空白
     * graph_entity_pagerank：实体影响力（PageRank vs 论文数）— 发现被忽视的图结构枢纽实体
     * graph_structural_holes：介数中心性 — 发现连接多个研究社群但自身研究少的桥梁方向
     * graph_community_gaps：Louvain社区检测 — 识别孤立研究簇，跨社区研究是创新机会
     * graph_disease_method_reach：多跳可达性 — 2跳可达但未直连的方法=潜在可迁移技术
     * graph_citation_pagerank：引用网络PageRank — hidden_gem论文（被重要论文引用但自身引用少）
2. 综合SQL统计结果与图遍历结果，从多维度识别研究空白：技术覆盖空白、临床转化缺口、
   方法-疾病组合未探索区域、图结构孤立方向、跨社区桥梁缺口等。
3. 输出 {top_n} 条经过严格数据支撑的可执行研究方向推荐。

{focus_hint}

输出格式要求（严格遵守，全文不得出现任何表情符号）：

## 数据摘要

[说明调用了哪些工具、检索了多少条记录、数据覆盖时间范围]

## 研究空白分析

### 研究空白 1：[方向名称]

**研究问题**：[具体的科学问题或可验证的研究假设]

**数据依据**：[精确引用工具返回的数字，如"该疾病共X篇论文，其中仅Y篇为临床验证研究，临床转化比例为Z%"]

**可行性分析**：[阐明当前技术成熟度、公开数据集可得性、计算资源需求等支撑条件]

**预期学术影响**：[建议投稿期刊方向（含IF区间）、科学意义、引用潜力预估]

**主要挑战**：[列举技术难点、数据获取障碍、临床合作需求等]

**与已有工作的区别**：[引用具体现有论文标题或方法名，阐明本方向的核心创新点]

**难度评级**：低 / 中 / 高 / 极高

**新颖性评级**：一般 / 较高 / 高

---

[按相同格式输出第 2 至第 {top_n} 条研究空白]

## 优先级排序

| 排名 | 研究方向 | 难度 | 新颖性 | 预期影响力 | 临床转化价值 |
|------|---------|------|-------|----------|------------|
[表格数据行]

## 综合建议

[150至200字的综合性战略建议，说明优先投入方向及理由]

执行规则：
- 所有定量陈述必须直接引用工具返回的确切数值，不得使用"较多""较少"等模糊表述。
- 全文禁止使用任何表情符号或特殊Unicode图标。
- 每条研究空白必须至少引用两个独立工具的数据作为支撑。
- 研究方向描述需具体到可支撑基金申请书写作的精度。
- 如有focus方向，相关工具调用时须传入该关键词作为focus参数。
"""


def stream_agent(
    focus: str | None = None,
    top_n: int = 6,
    max_iterations: int = 25,
):
    """
    Generator that streams agent execution events as dicts.

    Event types yielded:
      {"type": "start",       "focus": ..., "top_n": ...}
      {"type": "tool_call",   "name": ..., "args": {...}, "call_id": ...}
      {"type": "tool_result", "name": ..., "result": {...}, "call_id": ...}
      {"type": "tool_error",  "name": ..., "error": ...,   "call_id": ...}
      {"type": "thinking",    "content": ...}
      {"type": "final",       "content": ...}
      {"type": "error",       "content": ...}
    """
    focus_hint = (
        f"分析聚焦方向：{focus}。请优先关注与此方向相关的研究空白，工具调用时须传入该关键词作为focus参数。"
        if focus
        else "未指定细分方向，请进行病理AI全领域综合分析。"
    )

    system_msg = SYSTEM_PROMPT.format(top_n=top_n, focus_hint=focus_hint)
    user_msg = (
        (f"请针对「{focus}」方向，" if focus else "请针对病理AI全领域，")
        + f"系统分析知识图谱，识别主要研究空白，推荐 {top_n} 条可执行的研究方向。"
        + "请先调用至少6个工具收集充分数据，再给出最终报告。"
    )

    messages: list[dict] = [
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": user_msg},
    ]

    yield {"type": "start", "focus": focus, "top_n": top_n}

    for _iteration in range(max_iterations):
        response = _client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=config.LLM_MAX_TOKENS,
        )

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        # LLM produced text alongside tool calls (reasoning trace)
        if msg.content and msg.tool_calls:
            yield {"type": "thinking", "content": msg.content}

        # No tool calls → final answer
        if not msg.tool_calls or response.choices[0].finish_reason == "stop":
            yield {"type": "final", "content": msg.content or ""}
            return

        # Process each tool call
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            focus_arg = fn_args.get("focus") or focus

            yield {
                "type": "tool_call",
                "name": fn_name,
                "args": {"focus": focus_arg},
                "call_id": tc.id,
            }

            if fn_name in TOOLS:
                try:
                    result = TOOLS[fn_name](focus=focus_arg)
                    result_str = json.dumps(result, ensure_ascii=False, indent=2)
                    if len(result_str) > 8000:
                        result_str = result_str[:8000] + "\n... [truncated]"
                    yield {
                        "type": "tool_result",
                        "name": fn_name,
                        "result": result,
                        "call_id": tc.id,
                    }
                except Exception as exc:
                    result_str = json.dumps({"error": str(exc)}, ensure_ascii=False)
                    yield {
                        "type": "tool_error",
                        "name": fn_name,
                        "error": str(exc),
                        "call_id": tc.id,
                    }
            else:
                result_str = json.dumps({"error": f"Unknown tool: {fn_name}"})
                yield {
                    "type": "tool_error",
                    "name": fn_name,
                    "error": f"Unknown tool: {fn_name}",
                    "call_id": tc.id,
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

    yield {"type": "error", "content": "Maximum iterations reached without a final response."}


def run_agent(
    focus: str | None = None,
    top_n: int = 6,
    verbose: bool = False,
    max_iterations: int = 25,
) -> str:
    """
    Synchronous wrapper around stream_agent.
    Prints progress to stdout and returns the final report string.
    """
    print(f"\n{'='*60}")
    print(f"Research Gap Analysis Agent")
    print(f"  Domain          : {focus or 'all pathology AI'}")
    print(f"  Recommendations : {top_n}")
    print(f"{'='*60}\n")

    final_content = ""
    for event in stream_agent(focus=focus, top_n=top_n, max_iterations=max_iterations):
        etype = event["type"]
        if etype == "tool_call":
            focus_arg = event.get("args", {}).get("focus")
            print(f"  [tool] {event['name']}(focus={focus_arg!r})")
        elif etype == "tool_error":
            print(f"  [error] {event['name']}: {event['error']}")
        elif etype == "thinking" and verbose:
            print(f"  [reasoning] {event['content'][:150]}...")
        elif etype == "final":
            final_content = event["content"]
            print("\nAnalysis complete. Report generated.\n")
        elif etype == "error":
            print(f"\n[warning] {event['content']}")

    return final_content


# ─────────────────────────────────────────────────────────────────────────────
# ── Output helpers ────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def save_report(content: str, path: str) -> None:
    header = textwrap.dedent(f"""\
        # 病理AI研究空白分析报告

        > 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
        > 数据来源：病理AI科研知识图谱
        > 生成工具：gap_agent.py

        ---

    """)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + content)
    print(f"\nReport saved: {path}")


# ─────────────────────────────────────────────────────────────────────────────
# ── CLI ───────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="病理AI研究空白挖掘 Agent — 基于知识图谱的研究方向推荐"
    )
    parser.add_argument(
        "--focus", "-f",
        default=None,
        help="细分研究方向关键词（如 'lung cancer', 'segmentation', 'foundation model'）"
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=6,
        help="推荐研究方向条数（默认6）"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="保存 Markdown 报告的文件路径（如 output/gap_report.md）"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="打印详细的 agent 推理过程"
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="列出所有可用的 KG 查询工具"
    )
    args = parser.parse_args()

    if args.list_tools:
        print("\nAvailable KG query tools:\n")
        for name, fn in TOOLS.items():
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            print(f"  {name:30s}  {doc}")
        sys.exit(0)

    init_db()

    report = run_agent(
        focus=args.focus,
        top_n=args.top,
        verbose=args.verbose,
    )

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    if args.output:
        save_report(report, args.output)
    else:
        # Auto-save to output directory
        focus_slug = (args.focus or "full").replace(" ", "_").replace("/", "-")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        default_path = f"output/gap_report_{focus_slug}_{timestamp}.md"
        save_report(report, default_path)
