from utils.db import get_conn, init_db
init_db()
with get_conn() as c:
    existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    print("Existing indexes:", existing)
    indexes = [
        ("idx_relations_source_pmid",  "CREATE INDEX IF NOT EXISTS idx_relations_source_pmid  ON relations(source_pmid)"),
        ("idx_relations_relation",      "CREATE INDEX IF NOT EXISTS idx_relations_relation     ON relations(relation)"),
        ("idx_relations_object_id",     "CREATE INDEX IF NOT EXISTS idx_relations_object_id    ON relations(object_id)"),
        ("idx_entities_type",           "CREATE INDEX IF NOT EXISTS idx_entities_type          ON entities(type)"),
        ("idx_papers_year",             "CREATE INDEX IF NOT EXISTS idx_papers_year            ON papers(year)"),
        ("idx_papers_study_type",       "CREATE INDEX IF NOT EXISTS idx_papers_study_type      ON papers(study_type)"),
        ("idx_papers_pmid",             "CREATE INDEX IF NOT EXISTS idx_papers_pmid            ON papers(pmid)"),
        ("idx_paper_authors_author_id", "CREATE INDEX IF NOT EXISTS idx_paper_authors_author_id ON paper_authors(author_id)"),
        ("idx_paper_authors_paper_id",  "CREATE INDEX IF NOT EXISTS idx_paper_authors_paper_id  ON paper_authors(paper_id)"),
        ("idx_citations_cited_pmid",    "CREATE INDEX IF NOT EXISTS idx_citations_cited_pmid   ON citations(cited_pmid)"),
        ("idx_citations_citing_pmid",   "CREATE INDEX IF NOT EXISTS idx_citations_citing_pmid  ON citations(citing_pmid)"),
    ]
    for name, sql in indexes:
        c.execute(sql)
        print(f"  created: {name}")
    c.execute("ANALYZE")
    print("Done.")
