from utils.db import get_conn, init_db
init_db()

with get_conn() as c:

    print("\n=== 标题过短（<=10字符）===")
    rows = c.execute("""
        SELECT pmid, title, year, journal_name FROM papers
        WHERE length(trim(title)) <= 10 OR title IS NULL OR trim(title)=''
        ORDER BY year DESC LIMIT 30
    """).fetchall()
    print(f"  共 {len(rows)} 条")
    for r in rows: print(f"  [{r['year']}] pmid={r['pmid']} title={repr(r['title'])} journal={r['journal_name']}")

    print("\n=== 标题可疑（可能截断，以...或[结尾）===")
    rows = c.execute("""
        SELECT pmid, title, year FROM papers
        WHERE title LIKE '%...' OR title LIKE '%[' OR title LIKE '%-'
        LIMIT 20
    """).fetchall()
    print(f"  共 {len(rows)} 条（示例）")
    for r in rows: print(f"  [{r['year']}] {r['title'][:80]}")

    print("\n=== 没有期刊名的文章 ===")
    rows = c.execute("""
        SELECT COUNT(*) as cnt FROM papers
        WHERE (journal_name IS NULL OR trim(journal_name)='')
    """).fetchone()
    print(f"  无期刊名: {rows['cnt']} 篇")

    print("\n=== 没有期刊名的文章样例 ===")
    rows = c.execute("""
        SELECT pmid, title, year FROM papers
        WHERE (journal_name IS NULL OR trim(journal_name)='')
        ORDER BY year DESC LIMIT 10
    """).fetchall()
    for r in rows: print(f"  [{r['year']}] pmid={r['pmid']} {r['title'][:60]}")

    print("\n=== 影响因子匹配情况 ===")
    rows = c.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN j.impact_factor IS NOT NULL THEN 1 ELSE 0 END) as has_if,
            SUM(CASE WHEN j.impact_factor IS NULL AND p.journal_id IS NOT NULL THEN 1 ELSE 0 END) as journal_no_if,
            SUM(CASE WHEN p.journal_id IS NULL THEN 1 ELSE 0 END) as no_journal_link
        FROM papers p
        LEFT JOIN journals j ON p.journal_id = j.id
    """).fetchone()
    total = rows['total']
    print(f"  总论文数:          {total}")
    print(f"  有IF:              {rows['has_if']} ({rows['has_if']*100//total}%)")
    print(f"  有期刊但无IF:      {rows['journal_no_if']} ({rows['journal_no_if']*100//total}%)")
    print(f"  未关联期刊:        {rows['no_journal_link']} ({rows['no_journal_link']*100//total}%)")

    print("\n=== 无IF的期刊（出现文章最多的前30）===")
    rows = c.execute("""
        SELECT p.journal_name, COUNT(*) as cnt
        FROM papers p
        LEFT JOIN journals j ON p.journal_id = j.id
        WHERE j.impact_factor IS NULL AND p.journal_name IS NOT NULL AND trim(p.journal_name)!=''
        GROUP BY p.journal_name
        ORDER BY cnt DESC
        LIMIT 30
    """).fetchall()
    for r in rows: print(f"  {r['cnt']:4d}  {r['journal_name']}")

    print("\n=== abstract缺失情况 ===")
    rows = c.execute("""
        SELECT
            SUM(CASE WHEN abstract IS NULL OR trim(abstract)='' THEN 1 ELSE 0 END) as no_abstract,
            SUM(CASE WHEN length(trim(abstract)) < 50 THEN 1 ELSE 0 END) as short_abstract,
            COUNT(*) as total
        FROM papers
    """).fetchone()
    print(f"  无abstract:        {rows['no_abstract']}")
    print(f"  abstract<50字符:   {rows['short_abstract']}")

    print("\n=== extraction_done 状态 ===")
    rows = c.execute("""
        SELECT extraction_done, COUNT(*) as cnt FROM papers GROUP BY extraction_done
    """).fetchall()
    for r in rows: print(f"  extraction_done={r['extraction_done']}: {r['cnt']} 篇")

    print("\n=== 年份分布异常（年份为0或NULL或<2010或>2026）===")
    rows = c.execute("""
        SELECT year, COUNT(*) as cnt FROM papers
        WHERE year IS NULL OR year=0 OR year<2010 OR year>2026
        GROUP BY year ORDER BY year
    """).fetchall()
    for r in rows: print(f"  year={r['year']}: {r['cnt']} 篇")
