"""
知识图谱查询示例
直接运行: python query_examples.py
"""
from utils.db import get_conn, init_db

init_db()

def run(title, sql, params=()):
    print(f"\n{'='*60}")
    print(f"【{title}】")
    print('='*60)
    with get_conn() as c:
        rows = c.execute(sql, params).fetchall()
    for r in rows:
        print(dict(r))

# ── 1. 最热门的方法（Method实体出现次数）──────────────────────────────────
run("最热门的AI方法 Top20", """
    SELECT e.name, e.type, COUNT(*) as paper_count
    FROM relations r
    JOIN entities e ON r.object_id = e.id
    WHERE e.type = 'Method' AND r.relation = 'APPLIES_METHOD'
    GROUP BY e.id
    ORDER BY paper_count DESC
    LIMIT 20
""")

# ── 2. 最热门的疾病 ────────────────────────────────────────────────────────
run("最热门的疾病/癌症 Top20", """
    SELECT e.name, COUNT(*) as paper_count
    FROM relations r
    JOIN entities e ON r.object_id = e.id
    WHERE e.type = 'Disease' AND r.relation = 'TARGETS_DISEASE'
    GROUP BY e.id
    ORDER BY paper_count DESC
    LIMIT 20
""")

# ── 3. 最热门的任务 ────────────────────────────────────────────────────────
run("最热门的计算任务 Top20", """
    SELECT e.name, COUNT(*) as paper_count
    FROM relations r
    JOIN entities e ON r.object_id = e.id
    WHERE e.type = 'Task' AND r.relation = 'PERFORMS_TASK'
    GROUP BY e.id
    ORDER BY paper_count DESC
    LIMIT 20
""")

# ── 4. 某方法被哪些文章用了（以attention为例）────────────────────────────────
run("用到 attention 相关方法的文章 Top10", """
    SELECT p.title, p.year, p.citation_count, e.name as method
    FROM relations r
    JOIN entities e ON r.object_id = e.id
    JOIN papers p ON r.source_pmid = p.pmid
    WHERE e.type = 'Method' AND lower(e.name) LIKE '%attention%'
      AND r.relation = 'APPLIES_METHOD'
    ORDER BY p.citation_count DESC
    LIMIT 10
""")

# ── 5. 某疾病相关的所有论文 ──────────────────────────────────────────────
run("结直肠癌 相关文章 Top10（按引用）", """
    SELECT p.title, p.year, p.citation_count, p.pmid
    FROM relations r
    JOIN entities e ON r.object_id = e.id
    JOIN papers p ON r.source_pmid = p.pmid
    WHERE e.type = 'Disease' AND lower(e.name) LIKE '%colorectal%'
    ORDER BY p.citation_count DESC
    LIMIT 10
""")

# ── 6. 每年发表量趋势 ────────────────────────────────────────────────────
run("每年发表量（按研究类型）", """
    SELECT year, study_type, COUNT(*) as count,
           ROUND(AVG(citation_count),1) as avg_citations
    FROM papers
    WHERE year >= 2015
    GROUP BY year, study_type
    ORDER BY year, study_type
""")

# ── 7. 高IF期刊中的文章 ──────────────────────────────────────────────────
run("发表在高IF期刊(IF>10)的文章 Top20", """
    SELECT p.title, p.year, j.name as journal,
           j.impact_factor, j.quartile, p.citation_count
    FROM papers p
    JOIN journals j ON p.journal_id = j.id
    WHERE j.impact_factor > 10
    ORDER BY j.impact_factor DESC, p.citation_count DESC
    LIMIT 20
""")

# ── 8. Foundation model 相关文章 ─────────────────────────────────────────
run("Foundation Model 文章按年份", """
    SELECT year, COUNT(*) as count
    FROM papers
    WHERE study_type = 'foundation_model'
    GROUP BY year
    ORDER BY year
""")

# ── 9. 最常一起出现的方法-任务组合 ──────────────────────────────────────
run("最常见的 Method → Task 组合 Top20", """
    WITH pm AS (
        SELECT r.source_pmid, e.name AS method
        FROM relations r JOIN entities e ON r.object_id=e.id
        WHERE r.relation='APPLIES_METHOD' AND e.type='Method'
    ),
    pt AS (
        SELECT r.source_pmid, e.name AS task
        FROM relations r JOIN entities e ON r.object_id=e.id
        WHERE r.relation='PERFORMS_TASK' AND e.type='Task'
    )
    SELECT pm.method, pt.task, COUNT(*) as co_count
    FROM pm JOIN pt ON pm.source_pmid=pt.source_pmid
    GROUP BY pm.method, pt.task
    ORDER BY co_count DESC
    LIMIT 20
""")

# ── 10. 某关键词全文搜索 ─────────────────────────────────────────────────
keyword = "survival prediction"
run(f"含关键词 '{keyword}' 的文章", """
    SELECT title, year, citation_count, study_type, pmid
    FROM papers
    WHERE abstract LIKE ?
    ORDER BY citation_count DESC
    LIMIT 10
""", (f"%{keyword}%",))

print("\n✅ 查询示例执行完毕")
print("提示: 修改上面的关键词/条件可以做任何自定义分析")
