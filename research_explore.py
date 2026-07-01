"""
research_explore.py
病理AI领域研究热点 / 研究空白 / 研究趋势 探索脚本

运行方式:
    python research_explore.py
    python research_explore.py --section trends      # 只看趋势
    python research_explore.py --section hotspot     # 只看热点
    python research_explore.py --section gap         # 只看空白
    python research_explore.py --section emerging    # 只看新兴方向
    python research_explore.py --section collab      # 只看作者/团队协作
"""
from __future__ import annotations

import argparse
import sys
from utils.db import get_conn, init_db

init_db()

SEP  = "=" * 70
SEP2 = "-" * 70

def h1(title: str):
    print(f"\n{SEP}\n▶ {title}\n{SEP}")

def h2(title: str):
    print(f"\n  {SEP2}\n  ◆ {title}\n  {SEP2}")

def run(sql: str, params=(), indent=2) -> list[dict]:
    with get_conn() as c:
        rows = c.execute(sql, params).fetchall()
    pad = " " * indent
    for r in rows:
        d = dict(r)
        print(pad + "  ".join(f"{k}={v}" for k, v in d.items()))
    return [dict(r) for r in rows]

# ═════════════════════════════════════════════════════════════════════════════
# 1. 研究趋势分析
# ═════════════════════════════════════════════════════════════════════════════
def section_trends():
    h1("研究趋势分析 (Trends)")

    h2("1-1  各研究类型年度发表量（绝对值）")
    run("""
        SELECT year,
            SUM(CASE WHEN study_type='ai_algorithm'      THEN 1 ELSE 0 END) AS ai_algo,
            SUM(CASE WHEN study_type='clinical_study'    THEN 1 ELSE 0 END) AS clinical,
            SUM(CASE WHEN study_type='foundation_model'  THEN 1 ELSE 0 END) AS foundation,
            SUM(CASE WHEN study_type='multimodal'        THEN 1 ELSE 0 END) AS multimodal,
            SUM(CASE WHEN study_type='dataset_benchmark' THEN 1 ELSE 0 END) AS dataset,
            SUM(CASE WHEN study_type='review'            THEN 1 ELSE 0 END) AS review,
            COUNT(*) AS total
        FROM papers
        WHERE year BETWEEN 2017 AND 2025
        GROUP BY year ORDER BY year
    """)

    h2("1-2  近3年增长最快的方法（2022→2025 涨幅）")
    run("""
        WITH y22 AS (
            SELECT e.name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE e.type='Method' AND r.relation='APPLIES_METHOD' AND p.year=2022
            GROUP BY e.id
        ),
        y25 AS (
            SELECT e.name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE e.type='Method' AND r.relation='APPLIES_METHOD' AND p.year=2025
            GROUP BY e.id
        )
        SELECT y25.name,
               COALESCE(y22.cnt,0) AS cnt_2022,
               y25.cnt             AS cnt_2025,
               ROUND(1.0*y25.cnt / MAX(COALESCE(y22.cnt,0),1), 2) AS growth_ratio
        FROM y25 LEFT JOIN y22 ON y25.name=y22.name
        WHERE y25.cnt >= 5
        ORDER BY growth_ratio DESC
        LIMIT 20
    """)

    h2("1-3  近3年增长最快的疾病研究方向（2022→2025）")
    run("""
        WITH y22 AS (
            SELECT e.name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE' AND p.year=2022
            GROUP BY e.id
        ),
        y25 AS (
            SELECT e.name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE' AND p.year=2025
            GROUP BY e.id
        )
        SELECT y25.name,
               COALESCE(y22.cnt,0) AS cnt_2022,
               y25.cnt             AS cnt_2025,
               ROUND(1.0*y25.cnt / MAX(COALESCE(y22.cnt,0),1), 2) AS growth_ratio
        FROM y25 LEFT JOIN y22 ON y25.name=y22.name
        WHERE y25.cnt >= 4
        ORDER BY growth_ratio DESC
        LIMIT 20
    """)

    h2("1-4  近3年增长最快的任务（2022→2025）")
    run("""
        WITH y22 AS (
            SELECT e.name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE e.type='Task' AND r.relation='PERFORMS_TASK' AND p.year=2022
            GROUP BY e.id
        ),
        y25 AS (
            SELECT e.name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE e.type='Task' AND r.relation='PERFORMS_TASK' AND p.year=2025
            GROUP BY e.id
        )
        SELECT y25.name,
               COALESCE(y22.cnt,0) AS cnt_2022,
               y25.cnt             AS cnt_2025,
               ROUND(1.0*y25.cnt / MAX(COALESCE(y22.cnt,0),1), 2) AS growth_ratio
        FROM y25 LEFT JOIN y22 ON y25.name=y22.name
        WHERE y25.cnt >= 3
        ORDER BY growth_ratio DESC
        LIMIT 20
    """)

    h2("1-5  Foundation Model 专项趋势 —— 每年高引文章")
    run("""
        SELECT p.year, p.title, p.citation_count, j.name AS journal
        FROM papers p
        LEFT JOIN journals j ON p.journal_id=j.id
        WHERE p.study_type='foundation_model'
        ORDER BY p.year, p.citation_count DESC
    """)


# ═════════════════════════════════════════════════════════════════════════════
# 2. 研究热点分析
# ═════════════════════════════════════════════════════════════════════════════
def section_hotspot():
    h1("研究热点分析 (Hotspots)")

    h2("2-1  全局最高热度实体（出现论文数 × 平均引用）")
    run("""
        SELECT e.name, e.type,
               COUNT(DISTINCT r.source_pmid)              AS paper_cnt,
               ROUND(AVG(p.citation_count), 1)            AS avg_cite,
               ROUND(COUNT(DISTINCT r.source_pmid) * AVG(p.citation_count), 0) AS heat_score
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        GROUP BY e.id
        HAVING paper_cnt >= 5
        ORDER BY heat_score DESC
        LIMIT 30
    """)

    h2("2-2  近2年(2024-2025) 最热方法×任务组合")
    run("""
        WITH pm AS (
            SELECT r.source_pmid, e.name AS method
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE r.relation='APPLIES_METHOD' AND e.type='Method' AND p.year>=2024
        ),
        pt AS (
            SELECT r.source_pmid, e.name AS task
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE r.relation='PERFORMS_TASK' AND e.type='Task' AND p.year>=2024
        )
        SELECT pm.method, pt.task,
               COUNT(*) AS co_count,
               ROUND(AVG(p.citation_count),1) AS avg_cite
        FROM pm JOIN pt ON pm.source_pmid=pt.source_pmid
        JOIN papers p ON pm.source_pmid=p.pmid
        GROUP BY pm.method, pt.task
        HAVING co_count >= 3
        ORDER BY co_count DESC, avg_cite DESC
        LIMIT 25
    """)

    h2("2-3  近2年 最热疾病×方法组合")
    run("""
        WITH pd AS (
            SELECT r.source_pmid, e.name AS disease
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE r.relation='TARGETS_DISEASE' AND e.type='Disease' AND p.year>=2024
        ),
        pm AS (
            SELECT r.source_pmid, e.name AS method
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE r.relation='APPLIES_METHOD' AND e.type='Method' AND p.year>=2024
        )
        SELECT pd.disease, pm.method,
               COUNT(*) AS co_count,
               ROUND(AVG(p.citation_count),1) AS avg_cite
        FROM pd JOIN pm ON pd.source_pmid=pm.source_pmid
        JOIN papers p ON pd.source_pmid=p.pmid
        GROUP BY pd.disease, pm.method
        HAVING co_count >= 3
        ORDER BY co_count DESC
        LIMIT 25
    """)

    h2("2-4  最常被引用的数据集（权威 benchmark）")
    run("""
        SELECT e.name,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Dataset' AND r.relation='USES_DATASET'
        GROUP BY e.id
        ORDER BY paper_cnt DESC
        LIMIT 20
    """)

    h2("2-5  报告最高性能指标的论文（ACHIEVES_METRIC）")
    run("""
        SELECT p.title, p.year, r.metric_value, p.citation_count
        FROM relations r
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE r.relation='ACHIEVES_METRIC'
          AND r.metric_value LIKE '%AUC%'
          AND p.year >= 2023
        ORDER BY p.citation_count DESC
        LIMIT 15
    """)


# ═════════════════════════════════════════════════════════════════════════════
# 3. 研究空白分析
# ═════════════════════════════════════════════════════════════════════════════
def section_gap():
    h1("研究空白分析 (Research Gaps)")

    h2("3-1  高引用但近年关注下降的疾病（热点退潮？）")
    run("""
        WITH early AS (
            SELECT e.name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE'
              AND p.year BETWEEN 2019 AND 2021
            GROUP BY e.id
        ),
        recent AS (
            SELECT e.name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r JOIN entities e ON r.object_id=e.id
            JOIN papers p ON r.source_pmid=p.pmid
            WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE'
              AND p.year BETWEEN 2023 AND 2025
            GROUP BY e.id
        )
        SELECT early.name,
               early.cnt AS cnt_2019_21,
               COALESCE(recent.cnt,0) AS cnt_2023_25,
               ROUND(1.0*COALESCE(recent.cnt,0)/early.cnt, 2) AS ratio
        FROM early LEFT JOIN recent ON early.name=recent.name
        WHERE early.cnt >= 10
        ORDER BY ratio ASC
        LIMIT 20
    """)

    h2("3-2  疾病研究覆盖的稀疏任务（有病名但任务不丰富）")
    run("""
        SELECT e_d.name AS disease,
               COUNT(DISTINCT r_d.source_pmid) AS paper_cnt,
               COUNT(DISTINCT e_t.name) AS task_variety
        FROM relations r_d
        JOIN entities e_d ON r_d.object_id=e_d.id
        LEFT JOIN relations r_t ON r_d.source_pmid=r_t.source_pmid
            AND r_t.relation='PERFORMS_TASK'
        LEFT JOIN entities e_t ON r_t.object_id=e_t.id
        WHERE r_d.relation='TARGETS_DISEASE' AND e_d.type='Disease'
        GROUP BY e_d.id
        HAVING paper_cnt >= 15 AND task_variety <= 3
        ORDER BY paper_cnt DESC
        LIMIT 20
    """)

    h2("3-3  热门任务但数据集稀缺（缺少公开 benchmark）")
    run("""
        SELECT e_t.name AS task,
               COUNT(DISTINCT r_t.source_pmid) AS paper_cnt,
               COUNT(DISTINCT e_d.name) AS dataset_variety
        FROM relations r_t
        JOIN entities e_t ON r_t.object_id=e_t.id
        LEFT JOIN relations r_d ON r_t.source_pmid=r_d.source_pmid
            AND r_d.relation='USES_DATASET'
        LEFT JOIN entities e_d ON r_d.object_id=e_d.id AND e_d.type='Dataset'
        WHERE r_t.relation='PERFORMS_TASK' AND e_t.type='Task'
        GROUP BY e_t.id
        HAVING paper_cnt >= 10 AND (dataset_variety IS NULL OR dataset_variety <= 1)
        ORDER BY paper_cnt DESC
        LIMIT 20
    """)

    h2("3-4  被高引论文研究但整体论文数少的疾病（值得跟进）")
    run("""
        SELECT e.name AS disease,
               COUNT(DISTINCT r.source_pmid) AS total_papers,
               MAX(p.citation_count) AS max_citation,
               ROUND(AVG(p.citation_count), 1) AS avg_citation
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE'
        GROUP BY e.id
        HAVING total_papers BETWEEN 3 AND 12
           AND max_citation >= 100
        ORDER BY max_citation DESC
        LIMIT 25
    """)

    h2("3-5  方法已成熟但临床转化少（ai_algorithm多、clinical_study少）")
    run("""
        SELECT e.name AS method,
               SUM(CASE WHEN p.study_type='ai_algorithm'   THEN 1 ELSE 0 END) AS algo_cnt,
               SUM(CASE WHEN p.study_type='clinical_study' THEN 1 ELSE 0 END) AS clinical_cnt,
               ROUND(1.0 * SUM(CASE WHEN p.study_type='clinical_study' THEN 1 ELSE 0 END)
                         / COUNT(*), 3) AS clinical_ratio
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Method' AND r.relation='APPLIES_METHOD'
        GROUP BY e.id
        HAVING algo_cnt >= 8 AND clinical_cnt <= 1
        ORDER BY algo_cnt DESC
        LIMIT 20
    """)

    h2("3-6  有论文但无高IF发表的研究方向（影响力待提升）")
    run("""
        SELECT e.name AS entity, e.type,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               MAX(j.impact_factor) AS max_if,
               ROUND(AVG(j.impact_factor), 2) AS avg_if
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        LEFT JOIN journals j ON p.journal_id=j.id
        WHERE e.type IN ('Disease','Task')
        GROUP BY e.id
        HAVING paper_cnt >= 10 AND (max_if IS NULL OR max_if < 5)
        ORDER BY paper_cnt DESC
        LIMIT 20
    """)


# ═════════════════════════════════════════════════════════════════════════════
# 4. 新兴方向识别
# ═════════════════════════════════════════════════════════════════════════════
def section_emerging():
    h1("新兴方向识别 (Emerging Topics)")

    h2("4-1  首次出现于2023年及以后、且已有>=3篇论文的新方法")
    run("""
        SELECT e.name, e.type,
               MIN(p.year) AS first_year,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Method' AND r.relation='APPLIES_METHOD'
        GROUP BY e.id
        HAVING first_year >= 2023 AND paper_cnt >= 3
        ORDER BY avg_cite DESC, paper_cnt DESC
        LIMIT 25
    """)

    h2("4-2  首次出现于2023年及以后的新任务")
    run("""
        SELECT e.name,
               MIN(p.year) AS first_year,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Task' AND r.relation='PERFORMS_TASK'
        GROUP BY e.id
        HAVING first_year >= 2023 AND paper_cnt >= 3
        ORDER BY avg_cite DESC, paper_cnt DESC
        LIMIT 25
    """)

    h2("4-3  2024-2025 Multimodal 研究中的方法组合")
    run("""
        SELECT e.name AS method,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Method' AND r.relation='APPLIES_METHOD'
          AND p.study_type='multimodal' AND p.year >= 2024
        GROUP BY e.id
        ORDER BY paper_cnt DESC
        LIMIT 20
    """)

    h2("4-4  引用量增速快的2023-2024年论文（潜力文章）")
    run("""
        SELECT title, year, study_type, citation_count,
               journal_name,
               ROUND(1.0*citation_count/(2026-year+1), 1) AS cite_per_year
        FROM papers
        WHERE year BETWEEN 2023 AND 2024
          AND citation_count >= 50
        ORDER BY cite_per_year DESC
        LIMIT 25
    """)

    h2("4-5  近2年新出现的数据集")
    run("""
        SELECT e.name,
               MIN(p.year) AS first_year,
               COUNT(DISTINCT r.source_pmid) AS used_by_papers
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Dataset' AND r.relation='USES_DATASET'
        GROUP BY e.id
        HAVING first_year >= 2023
        ORDER BY used_by_papers DESC
        LIMIT 20
    """)

    h2("4-6  Foundation Model 在各疾病的应用分布")
    run("""
        SELECT e.name AS disease,
               COUNT(DISTINCT r.source_pmid) AS paper_cnt
        FROM relations r
        JOIN entities e ON r.object_id=e.id
        JOIN papers p ON r.source_pmid=p.pmid
        WHERE e.type='Disease' AND r.relation='TARGETS_DISEASE'
          AND p.study_type='foundation_model'
        GROUP BY e.id
        ORDER BY paper_cnt DESC
        LIMIT 20
    """)


# ═════════════════════════════════════════════════════════════════════════════
# 5. 高影响力文章与团队分析
# ═════════════════════════════════════════════════════════════════════════════
def section_collab():
    h1("高影响力文章与研究团队 (Impact & Collaboration)")

    h2("5-1  各研究方向的里程碑文章（最高引用）")
    run("""
        SELECT study_type,
               title, year, citation_count, journal_name
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY study_type ORDER BY citation_count DESC) AS rn
            FROM papers
            WHERE study_type IS NOT NULL
        )
        WHERE rn <= 3
        ORDER BY study_type, citation_count DESC
    """)

    h2("5-2  高产作者 Top20（论文数）")
    run("""
        SELECT a.name, a.affiliation,
               COUNT(*) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite,
               MAX(p.citation_count) AS max_cite
        FROM paper_authors pa
        JOIN authors a ON pa.author_id=a.id
        JOIN papers p ON pa.paper_id=p.id
        GROUP BY a.id
        ORDER BY paper_cnt DESC
        LIMIT 20
    """)

    h2("5-3  高影响力作者 Top20（平均引用，>=5篇）")
    run("""
        SELECT a.name, a.affiliation,
               COUNT(*) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite,
               MAX(p.citation_count) AS max_cite
        FROM paper_authors pa
        JOIN authors a ON pa.author_id=a.id
        JOIN papers p ON pa.paper_id=p.id
        GROUP BY a.id
        HAVING paper_cnt >= 5
        ORDER BY avg_cite DESC
        LIMIT 20
    """)

    h2("5-4  最活跃期刊（论文数 + 平均IF）")
    run("""
        SELECT j.name, j.impact_factor, j.quartile,
               COUNT(p.id) AS paper_cnt,
               ROUND(AVG(p.citation_count), 1) AS avg_cite
        FROM papers p
        JOIN journals j ON p.journal_id=j.id
        WHERE j.impact_factor IS NOT NULL
        GROUP BY j.id
        HAVING paper_cnt >= 10
        ORDER BY paper_cnt DESC
        LIMIT 20
    """)

    h2("5-5  高引文章的引用链（被哪些论文引用最多）")
    run("""
        SELECT p_cited.title AS cited_paper,
               p_cited.year,
               p_cited.citation_count,
               COUNT(c.citing_pmid) AS cited_by_in_corpus
        FROM citations c
        JOIN papers p_cited ON c.cited_pmid=p_cited.pmid
        GROUP BY c.cited_pmid
        ORDER BY cited_by_in_corpus DESC
        LIMIT 20
    """)

    h2("5-6  方法协同使用网络（同一篇论文中同时出现的方法对，近3年）")
    run("""
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
        GROUP BY a.eid, b.eid
        HAVING co_occurrence >= 4
        ORDER BY co_occurrence DESC
        LIMIT 20
    """)


# ═════════════════════════════════════════════════════════════════════════════
# 主程序
# ═════════════════════════════════════════════════════════════════════════════
SECTIONS = {
    "trends":   section_trends,
    "hotspot":  section_hotspot,
    "gap":      section_gap,
    "emerging": section_emerging,
    "collab":   section_collab,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", choices=list(SECTIONS.keys()) + ["all"],
                        default="all", help="Which section to run")
    args = parser.parse_args()

    if args.section == "all":
        for fn in SECTIONS.values():
            fn()
    else:
        SECTIONS[args.section]()

    print(f"\n✅  Done. 可用 --section {list(SECTIONS.keys())} 单独运行某部分")
