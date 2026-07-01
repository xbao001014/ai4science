"""
手动补充 jcr.csv 中遗漏的高影响力期刊 IF
运行: python fix_missing_if.py
"""
from utils.db import get_conn, init_db
init_db()

# 手动补充的期刊 IF 数据（来源: JCR 2024）
# 第三批：有JIF但jcr.csv未收录的期刊
MANUAL_IF = [
    # (journal_name_substr, impact_factor, quartile)
    # ── 第一批：已执行（2025-06 首次补充）─────────────────────────────────
    ("Nature communications",               15.7, "Q1"),
    ("Journal of pathology informatics",     3.2, "Q2"),
    ("Diagnostics",                          3.6, "Q2"),
    ("Cancers",                              4.4, "Q2"),
    ("Frontiers in medicine",                3.1, "Q1"),
    ("Bioengineering",                       4.6, "Q2"),
    ("NPJ precision oncology",               7.9, "Q1"),
    ("Cureus",                               1.4, "Q3"),
    ("BMC cancer",                           4.0, "Q2"),
    ("Diagnostic pathology",                 4.0, "Q2"),
    ("Heliyon",                              4.0, "Q2"),
    ("Biomedicines",                         4.8, "Q2"),
    ("The Lancet. Digital health",          23.8, "Q1"),
    ("Frontiers in artificial intelligence", 2.9, "Q3"),
    ("Radiology",                           15.2, "Q1"),
    ("Frontiers in molecular biosciences",   3.9, "Q2"),
    ("Discover oncology",                    2.8, "Q3"),
    ("Scientific data",                      9.8, "Q1"),
    ("Journal of imaging informatics",       3.2, "Q2"),
    ("The journal of pathology. Clinical",   3.8, "Q2"),
    ("Journal of imaging",                   3.4, "Q3"),
    ("Frontiers in oncology",                2.6, "Q2"),
    # ── 第三类：有JIF但jcr.csv未收录 ──────────────────────────────────────
    # Frontiers 系列
    ("Frontiers in genetics",                4.1, "Q2"),
    ("Frontiers in pharmacology",            4.4, "Q2"),
    ("Frontiers in veterinary science",      2.6, "Q2"),
    ("Frontiers in digital health",          3.6, "Q2"),
    ("Frontiers in physiology",              3.2, "Q2"),
    ("Frontiers in bioinformatics",          2.8, "Q3"),
    ("Frontiers in public health",           3.0, "Q2"),
    ("Frontiers in neuroinformatics",        2.7, "Q3"),
    ("Frontiers in microbiology",            4.0, "Q2"),
    ("Frontiers in transplantation",         2.1, "Q3"),
    # European Urology 系列
    ("European urology oncology",           11.4, "Q1"),
    ("European urology focus",               5.2, "Q1"),
    # BMC 系列
    ("BMC medical informatics and decision", 3.3, "Q2"),
    ("BMC nephrology",                       3.0, "Q2"),
    ("BMC gastroenterology",                 3.0, "Q2"),
    ("BMC medical genomics",                 2.9, "Q3"),
    ("BMC neurology",                        2.8, "Q3"),
    ("BMC women",                            2.9, "Q3"),
    ("BMC rheumatology",                     3.4, "Q2"),
    ("BMC endocrine",                        2.9, "Q3"),
    ("BMC musculoskeletal",                  2.6, "Q3"),
    ("BMC research notes",                   1.9, "Q4"),
    ("BMC biology",                          4.4, "Q2"),
    # 高影响期刊
    ("Advanced science",                    14.3, "Q1"),
    ("Communications biology",               5.9, "Q1"),
    ("JCO precision oncology",               5.6, "Q1"),
    ("NEJM evidence",                        6.8, "Q1"),
    ("Neuro-oncology advances",              3.3, "Q2"),
    ("JHEP reports",                         9.1, "Q1"),
    ("Therapeutic advances in gastroenterology", 4.2, "Q2"),
    ("United European gastroenterology journal", 5.1, "Q2"),
    ("ESMO open",                            7.1, "Q1"),
    ("Cancer communications",               20.1, "Q1"),
    ("Journal of hematology & oncology",    28.5, "Q1"),
    ("JCO global oncology",                  4.0, "Q2"),
    ("JTO clinical and research reports",    3.6, "Q2"),
    ("JNCI cancer spectrum",                 3.9, "Q2"),
    ("Molecular cancer",                    27.7, "Q1"),
    ("The lancet. Gastroenterology",        35.7, "Q1"),
    ("Radiation oncology",                   3.6, "Q2"),
    ("Respiratory research",                 5.6, "Q1"),
    ("Journal of neuroinflammation",         9.3, "Q1"),
    ("Journal of extracellular vesicles",   16.0, "Q1"),
    ("Journal of experimental & clinical cancer", 7.9, "Q1"),
    ("Hepatology communications",            4.3, "Q2"),
    ("European heart journal. Digital health", 6.2, "Q1"),
    ("Annals of translational medicine",     3.6, "Q2"),
    ("Translational gastroenterology and hepatology", 3.8, "Q2"),
    ("Cell & bioscience",                    7.0, "Q1"),
    ("Life science alliance",                4.6, "Q2"),
    ("NAR genomics and bioinformatics",      4.4, "Q2"),
    ("Bioactive materials",                 18.0, "Q1"),
    ("Acta cytologica",                      2.1, "Q3"),
    ("npj imaging",                          4.5, "Q2"),
    ("Healthcare",                           2.0, "Q3"),
    ("Biomolecules",                         4.8, "Q2"),
    ("Cells",                                5.1, "Q2"),
    ("Biology",                              3.6, "Q2"),
    ("Life",                                 3.2, "Q2"),
    ("Pharmaceuticals",                      4.6, "Q2"),
    ("Pharmaceutics",                        5.4, "Q2"),
    ("Metabolites",                          3.4, "Q2"),
    ("Entropy",                              2.1, "Q3"),
    ("Molecules",                            4.2, "Q2"),
    ("Microbiology spectrum",                3.7, "Q2"),
    ("Sensors",                              3.7, "Q2"),
    ("Biomimetics",                          3.5, "Q2"),
    ("Children",                             2.1, "Q3"),
    ("Medical sciences",                     2.4, "Q3"),
    ("PLOS digital health",                  4.7, "Q2"),
    ("F1000Research",                        2.4, "Q3"),
    ("Brain sciences",                       2.7, "Q3"),
    ("Alzheimer",                            9.3, "Q1"),
    ("Molecular & cellular proteomics",      6.3, "Q1"),
    ("Oncotarget",                           3.5, "Q3"),
    ("Progress in biomedical engineering",   6.5, "Q1"),
    ("BMJ oncology",                         6.2, "Q1"),
    ("JAMIA open",                           3.5, "Q2"),
    ("JMIR medical informatics",             3.0, "Q2"),
    ("JMIR formative research",              2.0, "Q3"),
    ("IEEE open journal of engineering in medicine", 2.7, "Q3"),
    ("IEEE transactions on computational biology", 3.6, "Q2"),
    ("Mathematical biosciences and engineering", 2.6, "Q3"),
    ("Computational intelligence and neuroscience", 2.9, "Q3"),
    ("Biomedical engineering online",        3.0, "Q3"),
    ("Biological procedures online",         3.3, "Q3"),
    ("Neuroimage. Reports",                  2.5, "Q3"),
    ("Journal of clinical and translational science", 2.7, "Q3"),
    ("MedComm",                             10.7, "Q1"),
    # 中文期刊（补充主要几个）
    ("Zhonghua bing li xue za zhi",          0.9, "Q4"),
    ("Sichuan da xue xue bao. Yi xue ban",   1.2, "Q4"),
]

IF_YEAR = 2024
updated = 0

with get_conn() as c:
    for name_substr, if_val, quartile in MANUAL_IF:
        # Try LIKE match on journal name
        rows = c.execute(
            "SELECT id, name, impact_factor FROM journals WHERE name LIKE ? AND (impact_factor IS NULL OR impact_factor = 0)",
            (f"%{name_substr}%",)
        ).fetchall()
        for row in rows:
            c.execute(
                "UPDATE journals SET impact_factor=?, if_year=?, quartile=? WHERE id=?",
                (if_val, IF_YEAR, quartile, row["id"])
            )
            print(f"  ✅ Updated: {row['name'][:60]}  IF={if_val} {quartile}")
            updated += 1

print(f"\n共更新 {updated} 条期刊 IF 记录")

# 统计更新后的覆盖率
with get_conn() as c:
    row = c.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN j.impact_factor IS NOT NULL THEN 1 ELSE 0 END) as has_if
        FROM papers p LEFT JOIN journals j ON p.journal_id=j.id
    """).fetchone()
    pct = row["has_if"] * 100 // row["total"]
    print(f"更新后 IF 覆盖率: {row['has_if']}/{row['total']} ({pct}%)")
