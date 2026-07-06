"""SQLite schema and CRUD for the full-text workflow sandbox."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Callable, Generator

import config

DB_PATH = config.DB_PATH


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS journals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    abbr            TEXT,
    issn            TEXT UNIQUE,
    impact_factor   REAL,
    if_year         INTEGER,
    quartile        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS papers (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    pmid                    TEXT UNIQUE,
    doi                     TEXT,
    pmc_id                  TEXT,
    s2id                    TEXT,
    title                   TEXT NOT NULL,
    abstract                TEXT,
    pub_date                TEXT,
    year                    INTEGER,
    journal_id              INTEGER REFERENCES journals(id),
    journal_name            TEXT,
    journal_abbr            TEXT,
    issn                    TEXT,
    study_type              TEXT,
    pub_types               TEXT,
    mesh_terms              TEXT,
    keywords                TEXT,
    source_queries          TEXT,
    citation_count          INTEGER DEFAULT 0,
    open_access             INTEGER DEFAULT 0,
    citation_source         TEXT,
    full_text_status        TEXT DEFAULT 'pending',
    full_text_fetched_at    TIMESTAMP,
    extraction_done         INTEGER DEFAULT 0,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_papers_pmid ON papers(pmid);
CREATE INDEX IF NOT EXISTS idx_papers_pmc ON papers(pmc_id);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_papers_ft ON papers(full_text_status);

CREATE TABLE IF NOT EXISTS authors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    affiliation TEXT,
    orcid       TEXT,
    UNIQUE(name, affiliation)
);

CREATE TABLE IF NOT EXISTS paper_authors (
    paper_id     INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    author_id    INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    author_order INTEGER,
    PRIMARY KEY (paper_id, author_id)
);

CREATE TABLE IF NOT EXISTS document_sections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    section_type    TEXT NOT NULL,
    title           TEXT,
    content         TEXT NOT NULL,
    order_idx       INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sections_paper ON document_sections(paper_id);
CREATE INDEX IF NOT EXISTS idx_sections_type ON document_sections(section_type);

CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    cui         TEXT,
    aliases     TEXT,
    UNIQUE(name, type)
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

CREATE TABLE IF NOT EXISTS relations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type            TEXT NOT NULL,
    subject_id              INTEGER NOT NULL,
    relation                TEXT NOT NULL,
    object_type             TEXT NOT NULL,
    object_id               INTEGER NOT NULL,
    metric_value            TEXT,
    source_pmid               TEXT,
    confidence              REAL DEFAULT 1.0,
    evidence_section        TEXT,
    evidence_quote          TEXT,
    extraction_granularity  TEXT DEFAULT 'abstract',
    polarity                TEXT DEFAULT 'asserted',
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_relations_subj ON relations(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_obj ON relations(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_relations_rel ON relations(relation);
CREATE INDEX IF NOT EXISTS idx_relations_gran ON relations(extraction_granularity);

CREATE TABLE IF NOT EXISTS pathology_landscape (
    disease_id      TEXT PRIMARY KEY,
    payload_json    TEXT NOT NULL,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feasibility_assessments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_title       TEXT,
    hypothesis_id   TEXT,
    hypothesis_json TEXT,
    feasibility_score REAL,
    status          TEXT,
    assessment_json TEXT,
    assessed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feas_gap ON feasibility_assessments(gap_title);

CREATE TABLE IF NOT EXISTS limitation_temporal (
    limitation_id       INTEGER PRIMARY KEY REFERENCES entities(id),
    limitation_name     TEXT NOT NULL,
    first_year          INTEGER,
    last_year           INTEGER,
    paper_cnt           INTEGER,
    asserted_cnt        INTEGER,
    hypothesized_cnt    INTEGER,
    early_cnt           INTEGER,
    recent_cnt          INTEGER,
    recent_ratio        REAL,
    temporal_status     TEXT,
    avg_cite            REAL,
    avg_cite_per_year   REAL,
    impact_tier         TEXT,
    computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lt_status ON limitation_temporal(temporal_status);
CREATE INDEX IF NOT EXISTS idx_lt_last_year ON limitation_temporal(last_year);

CREATE TABLE IF NOT EXISTS limitation_resolution_signals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    limitation_id       INTEGER NOT NULL REFERENCES entities(id),
    signal_type         TEXT NOT NULL,
    anchor_pmid         TEXT,
    followup_pmid       TEXT,
    anchor_year         INTEGER,
    followup_year       INTEGER,
    shared_entities     TEXT,
    confidence          REAL DEFAULT 0.5,
    computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lrs_limitation ON limitation_resolution_signals(limitation_id);
CREATE INDEX IF NOT EXISTS idx_lrs_signal ON limitation_resolution_signals(signal_type);

CREATE TABLE IF NOT EXISTS weekly_hotspot_runs (
    week_id             TEXT PRIMARY KEY,
    snapshot_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    window_days         INTEGER NOT NULL,
    prior_window_days   INTEGER NOT NULL,
    papers_ingested     INTEGER DEFAULT 0,
    report_path         TEXT
);

CREATE TABLE IF NOT EXISTS weekly_hotspot_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id             TEXT NOT NULL,
    board               TEXT NOT NULL,
    item_key            TEXT NOT NULL,
    entity_type         TEXT,
    rank_pos            INTEGER,
    recent_cnt          INTEGER,
    prior_cnt           INTEGER,
    velocity            REAL,
    emerging_score      REAL,
    avg_cite            REAL,
    avg_if              REAL,
    gap_phase           TEXT,
    top_pmids           TEXT,
    UNIQUE(week_id, board, item_key)
);
CREATE INDEX IF NOT EXISTS idx_whs_week_board ON weekly_hotspot_snapshots(week_id, board);
CREATE INDEX IF NOT EXISTS idx_whs_board_score ON weekly_hotspot_snapshots(board, emerging_score);
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_db(conn)
    print(f"[DB] Initialized database at {DB_PATH}")


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Add columns for citation/IF weighting on existing databases."""
    paper_cols = {r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()}
    journal_cols = {r[1] for r in conn.execute("PRAGMA table_info(journals)").fetchall()}

    for col, ddl in (
        ("s2id", "ALTER TABLE papers ADD COLUMN s2id TEXT"),
        ("citation_count", "ALTER TABLE papers ADD COLUMN citation_count INTEGER DEFAULT 0"),
        ("open_access", "ALTER TABLE papers ADD COLUMN open_access INTEGER DEFAULT 0"),
        ("citation_source", "ALTER TABLE papers ADD COLUMN citation_source TEXT"),
    ):
        if col not in paper_cols:
            conn.execute(ddl)

    for col, ddl in (
        ("impact_factor", "ALTER TABLE journals ADD COLUMN impact_factor REAL"),
        ("if_year", "ALTER TABLE journals ADD COLUMN if_year INTEGER"),
        ("quartile", "ALTER TABLE journals ADD COLUMN quartile TEXT"),
    ):
        if col not in journal_cols:
            conn.execute(ddl)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS limitation_temporal (
            limitation_id       INTEGER PRIMARY KEY REFERENCES entities(id),
            limitation_name     TEXT NOT NULL,
            first_year          INTEGER,
            last_year           INTEGER,
            paper_cnt           INTEGER,
            asserted_cnt        INTEGER,
            hypothesized_cnt    INTEGER,
            early_cnt           INTEGER,
            recent_cnt          INTEGER,
            recent_ratio        REAL,
            temporal_status     TEXT,
            avg_cite            REAL,
            avg_cite_per_year   REAL,
            impact_tier         TEXT,
            computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_lt_status ON limitation_temporal(temporal_status);
        CREATE INDEX IF NOT EXISTS idx_lt_last_year ON limitation_temporal(last_year);

        CREATE TABLE IF NOT EXISTS limitation_resolution_signals (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            limitation_id       INTEGER NOT NULL REFERENCES entities(id),
            signal_type         TEXT NOT NULL,
            anchor_pmid         TEXT,
            followup_pmid       TEXT,
            anchor_year         INTEGER,
            followup_year       INTEGER,
            shared_entities     TEXT,
            confidence          REAL DEFAULT 0.5,
            computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_lrs_limitation ON limitation_resolution_signals(limitation_id);
        CREATE INDEX IF NOT EXISTS idx_lrs_signal ON limitation_resolution_signals(signal_type);
        CREATE INDEX IF NOT EXISTS idx_rel_limitation ON relations(relation, object_id);
        CREATE INDEX IF NOT EXISTS idx_relations_pmid ON relations(source_pmid);
        CREATE INDEX IF NOT EXISTS idx_relations_rel_pmid ON relations(relation, source_pmid);
CREATE INDEX IF NOT EXISTS idx_relations_object_id ON relations(object_id);
        CREATE INDEX IF NOT EXISTS idx_relations_object_id ON relations(object_id);

        CREATE TABLE IF NOT EXISTS weekly_hotspot_runs (
            week_id             TEXT PRIMARY KEY,
            snapshot_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            window_days         INTEGER NOT NULL,
            prior_window_days   INTEGER NOT NULL,
            papers_ingested     INTEGER DEFAULT 0,
            report_path         TEXT
        );
        CREATE TABLE IF NOT EXISTS weekly_hotspot_snapshots (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            week_id             TEXT NOT NULL,
            board               TEXT NOT NULL,
            item_key            TEXT NOT NULL,
            entity_type         TEXT,
            rank_pos            INTEGER,
            recent_cnt          INTEGER,
            prior_cnt           INTEGER,
            velocity            REAL,
            emerging_score      REAL,
            avg_cite            REAL,
            avg_if              REAL,
            gap_phase           TEXT,
            top_pmids           TEXT,
            UNIQUE(week_id, board, item_key)
        );
        CREATE INDEX IF NOT EXISTS idx_whs_week_board ON weekly_hotspot_snapshots(week_id, board);
        CREATE INDEX IF NOT EXISTS idx_whs_board_score ON weekly_hotspot_snapshots(board, emerging_score);
    """)


def upsert_paper(data: dict[str, Any]) -> int:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, source_queries FROM papers WHERE pmid=? OR (doi IS NOT NULL AND doi=? AND doi != '')",
            (data.get("pmid"), data.get("doi")),
        ).fetchone()

        new_queries: list[str] = data.get("source_queries", [])
        if existing:
            old_queries = json.loads(existing["source_queries"] or "[]")
            merged = list(set(old_queries) | set(new_queries))
            conn.execute(
                """UPDATE papers SET
                   source_queries=?,
                   abstract=COALESCE(NULLIF(?, ''), abstract),
                   title=COALESCE(NULLIF(?, ''), title),
                   pmc_id=COALESCE(?, pmc_id)
                   WHERE id=?""",
                (
                    json.dumps(merged),
                    data.get("abstract", ""),
                    data.get("title", ""),
                    data.get("pmc_id"),
                    existing["id"],
                ),
            )
            return existing["id"]

        conn.execute(
            """INSERT INTO papers
               (pmid, doi, pmc_id, title, abstract, pub_date, year,
                journal_name, journal_abbr, issn, pub_types, mesh_terms,
                keywords, source_queries, full_text_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.get("pmid"),
                data.get("doi"),
                data.get("pmc_id"),
                data.get("title", ""),
                data.get("abstract", ""),
                data.get("pub_date"),
                data.get("year"),
                data.get("journal_name"),
                data.get("journal_abbr"),
                data.get("issn"),
                json.dumps(data.get("pub_types", [])),
                json.dumps(data.get("mesh_terms", [])),
                json.dumps(data.get("keywords", [])),
                json.dumps(new_queries),
                data.get("full_text_status", "pending"),
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def upsert_journal(name: str, abbr: str = "", issn: str = "") -> int:
    with get_conn() as conn:
        existing = None
        if issn:
            existing = conn.execute(
                "SELECT id FROM journals WHERE issn=?", (issn,)
            ).fetchone()
        if existing is None:
            existing = conn.execute(
                "SELECT id FROM journals WHERE name=?", (name,)
            ).fetchone()
        if existing:
            return existing["id"]
        conn.execute(
            "INSERT OR IGNORE INTO journals (name, abbr, issn) VALUES (?,?,?)",
            (name, abbr or None, issn or None),
        )
        row = conn.execute("SELECT id FROM journals WHERE name=?", (name,)).fetchone()
        return row["id"] if row else conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_all_journals() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM journals").fetchall()


def update_journal_if(
    journal_id: int,
    impact_factor: float,
    if_year: int,
    quartile: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE journals SET impact_factor=?, if_year=?, quartile=? WHERE id=?",
            (impact_factor, if_year, quartile, journal_id),
        )


def link_paper_journal(paper_id: int, journal_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE papers SET journal_id=? WHERE id=?", (journal_id, paper_id))


def upsert_author(name: str, affiliation: str = "", orcid: str = "") -> int:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM authors WHERE name=? AND affiliation=?", (name, affiliation)
        ).fetchone()
        if existing:
            return existing["id"]
        conn.execute(
            "INSERT INTO authors (name, affiliation, orcid) VALUES (?,?,?)",
            (name, affiliation, orcid),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def link_paper_author(paper_id: int, author_id: int, order: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO paper_authors (paper_id, author_id, author_order) VALUES (?,?,?)",
            (paper_id, author_id, order),
        )


def mark_fulltext_status(
    paper_id: int,
    status: str,
    pmc_id: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE papers SET
               full_text_status=?,
               pmc_id=COALESCE(?, pmc_id),
               full_text_fetched_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (status, pmc_id, paper_id),
        )


def delete_paper_sections(paper_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM document_sections WHERE paper_id=?", (paper_id,))


def insert_sections(paper_id: int, sections: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        for sec in sections:
            conn.execute(
                """INSERT INTO document_sections
                   (paper_id, section_type, title, content, order_idx)
                   VALUES (?,?,?,?,?)""",
                (
                    paper_id,
                    sec["section_type"],
                    sec.get("title", ""),
                    sec["content"],
                    sec.get("order_idx", 0),
                ),
            )


def get_papers_pending_fulltext() -> list[sqlite3.Row]:
    return get_papers_needing_fulltext()


def get_papers_needing_fulltext() -> list[sqlite3.Row]:
    """Papers awaiting tier-1 JATS fetch (status=pending)."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT id, pmid, doi, pmc_id FROM papers
               WHERE pmid IS NOT NULL AND full_text_status = 'pending'"""
        ).fetchall()


def get_papers_for_extraction(limit: int = 0) -> list[sqlite3.Row]:
    with get_conn() as conn:
        sql = """
            SELECT * FROM papers
            WHERE extraction_done=0
              AND abstract IS NOT NULL AND abstract != ''
            ORDER BY
              CASE
                WHEN LOWER(title) LIKE 'correction:%'
                  OR LOWER(title) LIKE 'corrigendum:%'
                  OR LOWER(title) LIKE 'erratum:%'
                  OR LOWER(title) LIKE 'comment on:%'
                  OR (LENGTH(abstract) < 80 AND LOWER(abstract) LIKE '%corrects the article%')
                THEN 2
                ELSE 0
              END,
              CASE full_text_status
                WHEN 'available' THEN 0
                WHEN 'pdf_available' THEN 1
                ELSE 2
              END,
              year DESC
        """
        if limit:
            sql += f" LIMIT {limit}"
        return conn.execute(sql).fetchall()


def get_unprocessed_papers(limit: int = 0) -> list[sqlite3.Row]:
    return get_papers_for_extraction(limit=limit)


def get_paper_sections(paper_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM document_sections
               WHERE paper_id=? ORDER BY order_idx""",
            (paper_id,),
        ).fetchall()


def mark_extraction_done(paper_id: int, study_type: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET extraction_done=1, study_type=? WHERE id=?",
            (study_type, paper_id),
        )


def upsert_entity(name: str, entity_type: str, cui: str = "") -> int:
    normalized = name.strip().lower()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM entities WHERE name=? AND type=?", (normalized, entity_type)
        ).fetchone()
        if existing:
            return existing["id"]
        conn.execute(
            "INSERT INTO entities (name, type, cui) VALUES (?,?,?)",
            (normalized, entity_type, cui or None),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_relation(
    subject_type: str,
    subject_id: int,
    relation: str,
    object_type: str,
    object_id: int,
    source_pmid: str = "",
    metric_value: str = "",
    confidence: float = 1.0,
    evidence_section: str = "",
    evidence_quote: str = "",
    extraction_granularity: str = "abstract",
    polarity: str = "asserted",
) -> None:
    with get_conn() as conn:
        existing = conn.execute(
            """SELECT id, extraction_granularity, evidence_quote FROM relations
               WHERE subject_type=? AND subject_id=? AND relation=?
                 AND object_type=? AND object_id=? AND source_pmid=?""",
            (subject_type, subject_id, relation, object_type, object_id, source_pmid),
        ).fetchone()
        if existing:
            gran = existing["extraction_granularity"]
            _rank = {"fulltext": 3, "mineru_pdf": 2, "abstract": 1}
            if _rank.get(gran, 0) > _rank.get(extraction_granularity, 0):
                return
            quote = existing["evidence_quote"] or ""
            if evidence_quote and evidence_quote not in quote:
                quote = f"{quote}; {evidence_quote}".strip("; ")
            conn.execute(
                """UPDATE relations SET
                   metric_value=COALESCE(NULLIF(?, ''), metric_value),
                   confidence=MAX(confidence, ?),
                   evidence_section=COALESCE(NULLIF(?, ''), evidence_section),
                   evidence_quote=?,
                   extraction_granularity=?,
                   polarity=?
                   WHERE id=?""",
                (
                    metric_value,
                    confidence,
                    evidence_section,
                    quote,
                    extraction_granularity,
                    polarity,
                    existing["id"],
                ),
            )
            return

        conn.execute(
            """INSERT INTO relations
               (subject_type, subject_id, relation, object_type, object_id,
                metric_value, source_pmid, confidence, evidence_section,
                evidence_quote, extraction_granularity, polarity)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                subject_type,
                subject_id,
                relation,
                object_type,
                object_id,
                metric_value or None,
                source_pmid or None,
                confidence,
                evidence_section or None,
                evidence_quote or None,
                extraction_granularity,
                polarity,
            ),
        )


def db_stats() -> dict[str, Any]:
    with get_conn() as conn:
        stats = {
            "papers": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
            "sections": conn.execute("SELECT COUNT(*) FROM document_sections").fetchone()[0],
            "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "relations": conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
            "fulltext_jats": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE full_text_status='available'"
            ).fetchone()[0],
            "fulltext_mineru_pdf": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE full_text_status='pdf_available'"
            ).fetchone()[0],
            "fulltext_unavailable": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE full_text_status='unavailable'"
            ).fetchone()[0],
            "extracted": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE extraction_done=1"
            ).fetchone()[0],
            "relations_fulltext": conn.execute(
                "SELECT COUNT(*) FROM relations WHERE extraction_granularity='fulltext'"
            ).fetchone()[0],
            "relations_mineru_pdf": conn.execute(
                "SELECT COUNT(*) FROM relations WHERE extraction_granularity='mineru_pdf'"
            ).fetchone()[0],
            "relations_abstract": conn.execute(
                "SELECT COUNT(*) FROM relations WHERE extraction_granularity='abstract'"
            ).fetchone()[0],
            "s2_enriched": conn.execute(
                """SELECT COUNT(*) FROM papers
                   WHERE citation_source IS NOT NULL
                     AND citation_source NOT IN ('', 'unavailable')"""
            ).fetchone()[0],
            "citations_openalex": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE citation_source='openalex'"
            ).fetchone()[0],
            "citations_semantic_scholar": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE citation_source='semantic_scholar'"
            ).fetchone()[0],
            "journals_with_if": conn.execute(
                "SELECT COUNT(*) FROM journals WHERE impact_factor IS NOT NULL"
            ).fetchone()[0],
        }
        stats["fulltext_available"] = stats["fulltext_jats"] + stats["fulltext_mineru_pdf"]
    return stats


def landscape_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM pathology_landscape").fetchone()[0]


def clear_landscape() -> int:
    """Delete all cached pathology landscape rows. Returns rows removed."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM pathology_landscape")
        return cur.rowcount


def upsert_landscape(disease_id: str, payload: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pathology_landscape (disease_id, payload_json, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(disease_id) DO UPDATE SET
                 payload_json=excluded.payload_json,
                 updated_at=CURRENT_TIMESTAMP""",
            (disease_id, json.dumps(payload, ensure_ascii=False)),
        )


def get_all_landscape() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT disease_id, payload_json, updated_at FROM pathology_landscape"
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "disease_id": r["disease_id"],
            "payload": json.loads(r["payload_json"]),
            "updated_at": r["updated_at"],
        })
    return out


def save_feasibility_assessment(
    gap_title: str,
    hypothesis_id: str,
    hypothesis: dict[str, Any],
    score: float,
    status: str,
    assessment: dict[str, Any],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO feasibility_assessments
               (gap_title, hypothesis_id, hypothesis_json, feasibility_score,
                status, assessment_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                gap_title,
                hypothesis_id,
                json.dumps(hypothesis, ensure_ascii=False),
                score,
                status,
                json.dumps(assessment, ensure_ascii=False),
            ),
        )


def get_feasibility_assessments(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT gap_title, hypothesis_id, feasibility_score, status,
                      assessment_json, assessed_at
               FROM feasibility_assessments
               ORDER BY assessed_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def clear_limitation_lifecycle() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM limitation_resolution_signals")
        conn.execute("DELETE FROM limitation_temporal")


def upsert_limitation_temporal(
    rows: list[dict[str, Any]],
    *,
    chunk_size: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    if not rows:
        return 0
    chunk = chunk_size or config.GAP_LIFECYCLE_UPSERT_CHUNK
    sql = """INSERT INTO limitation_temporal
               (limitation_id, limitation_name, first_year, last_year, paper_cnt,
                asserted_cnt, hypothesized_cnt, early_cnt, recent_cnt, recent_ratio,
                temporal_status, avg_cite, avg_cite_per_year, impact_tier, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(limitation_id) DO UPDATE SET
                 limitation_name=excluded.limitation_name,
                 first_year=excluded.first_year,
                 last_year=excluded.last_year,
                 paper_cnt=excluded.paper_cnt,
                 asserted_cnt=excluded.asserted_cnt,
                 hypothesized_cnt=excluded.hypothesized_cnt,
                 early_cnt=excluded.early_cnt,
                 recent_cnt=excluded.recent_cnt,
                 recent_ratio=excluded.recent_ratio,
                 temporal_status=excluded.temporal_status,
                 avg_cite=excluded.avg_cite,
                 avg_cite_per_year=excluded.avg_cite_per_year,
                 impact_tier=excluded.impact_tier,
                 computed_at=CURRENT_TIMESTAMP"""

    def _tuple(r: dict[str, Any]) -> tuple:
        return (
            r["limitation_id"],
            r["limitation_name"],
            r.get("first_year"),
            r.get("last_year"),
            r.get("paper_cnt"),
            r.get("asserted_cnt"),
            r.get("hypothesized_cnt"),
            r.get("early_cnt"),
            r.get("recent_cnt"),
            r.get("recent_ratio"),
            r.get("temporal_status"),
            r.get("avg_cite"),
            r.get("avg_cite_per_year"),
            r.get("impact_tier"),
        )

    total = len(rows)
    with get_conn() as conn:
        for start in range(0, total, chunk):
            batch = rows[start : start + chunk]
            conn.executemany(sql, [_tuple(r) for r in batch])
            if on_progress:
                on_progress(min(start + len(batch), total), total)
    return total


def insert_limitation_resolution_signals(
    rows: list[dict[str, Any]],
    *,
    chunk_size: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    if not rows:
        return 0
    chunk = chunk_size or config.GAP_LIFECYCLE_UPSERT_CHUNK
    sql = """INSERT INTO limitation_resolution_signals
               (limitation_id, signal_type, anchor_pmid, followup_pmid,
                anchor_year, followup_year, shared_entities, confidence)
               VALUES (?,?,?,?,?,?,?,?)"""

    def _tuple(r: dict[str, Any]) -> tuple:
        return (
            r["limitation_id"],
            r["signal_type"],
            r.get("anchor_pmid"),
            r.get("followup_pmid"),
            r.get("anchor_year"),
            r.get("followup_year"),
            r.get("shared_entities"),
            r.get("confidence", 0.5),
        )

    total = len(rows)
    with get_conn() as conn:
        for start in range(0, total, chunk):
            batch = rows[start : start + chunk]
            conn.executemany(sql, [_tuple(r) for r in batch])
            if on_progress:
                on_progress(min(start + len(batch), total), total)
    return total


def get_limitation_temporal_rows(
    focus: str | None = None,
    temporal_status: str | None = None,
    temporal_statuses: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if focus:
        clauses.append("LOWER(limitation_name) LIKE LOWER(?)")
        params.append(f"%{focus}%")
    if temporal_statuses:
        placeholders = ",".join("?" * len(temporal_statuses))
        clauses.append(f"temporal_status IN ({placeholders})")
        params.extend(temporal_statuses)
    elif temporal_status:
        clauses.append("temporal_status = ?")
        params.append(temporal_status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    lim = f" LIMIT {int(limit)}" if limit else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT limitation_id, limitation_name, first_year, last_year,
                       paper_cnt, asserted_cnt, hypothesized_cnt, early_cnt,
                       recent_cnt, recent_ratio, temporal_status,
                       avg_cite, avg_cite_per_year, impact_tier, computed_at
                FROM limitation_temporal {where}
                ORDER BY paper_cnt DESC, recent_ratio DESC{lim}""",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def get_limitation_resolution_rows(
    limitation_id: int | None = None,
    signal_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if limitation_id is not None:
        clauses.append("limitation_id = ?")
        params.append(limitation_id)
    if signal_type:
        clauses.append("signal_type = ?")
        params.append(signal_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    lim = f" LIMIT {int(limit)}" if limit else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, limitation_id, signal_type, anchor_pmid, followup_pmid,
                       anchor_year, followup_year, shared_entities, confidence
                FROM limitation_resolution_signals {where}
                ORDER BY confidence DESC, followup_year DESC{lim}""",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def limitation_lifecycle_stats() -> dict[str, int]:
    with get_conn() as conn:
        return {
            "limitation_temporal": conn.execute(
                "SELECT COUNT(*) FROM limitation_temporal"
            ).fetchone()[0],
            "persistent": conn.execute(
                "SELECT COUNT(*) FROM limitation_temporal WHERE temporal_status='persistent'"
            ).fetchone()[0],
            "declining": conn.execute(
                "SELECT COUNT(*) FROM limitation_temporal WHERE temporal_status='declining'"
            ).fetchone()[0],
            "emerging": conn.execute(
                "SELECT COUNT(*) FROM limitation_temporal WHERE temporal_status='emerging'"
            ).fetchone()[0],
            "resolution_signals": conn.execute(
                "SELECT COUNT(*) FROM limitation_resolution_signals"
            ).fetchone()[0],
            "topic_followup_moderate": conn.execute(
                """SELECT COUNT(DISTINCT limitation_id)
                   FROM limitation_resolution_signals
                   WHERE signal_type='topic_followup' AND confidence >= 0.7"""
            ).fetchone()[0],
        }


def upsert_weekly_hotspot_run(
    week_id: str,
    *,
    window_days: int,
    prior_window_days: int,
    papers_ingested: int,
    report_path: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO weekly_hotspot_runs
               (week_id, window_days, prior_window_days, papers_ingested, report_path, snapshot_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(week_id) DO UPDATE SET
                 window_days=excluded.window_days,
                 prior_window_days=excluded.prior_window_days,
                 papers_ingested=excluded.papers_ingested,
                 report_path=excluded.report_path,
                 snapshot_at=CURRENT_TIMESTAMP""",
            (week_id, window_days, prior_window_days, papers_ingested, report_path),
        )


def replace_weekly_hotspot_snapshots(week_id: str, rows: list[dict[str, Any]]) -> int:
    """Replace all snapshot rows for a week. Returns rows written."""
    with get_conn() as conn:
        conn.execute("DELETE FROM weekly_hotspot_snapshots WHERE week_id=?", (week_id,))
        if not rows:
            return 0
        conn.executemany(
            """INSERT INTO weekly_hotspot_snapshots
               (week_id, board, item_key, entity_type, rank_pos,
                recent_cnt, prior_cnt, velocity, emerging_score,
                avg_cite, avg_if, gap_phase, top_pmids)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    week_id,
                    r["board"],
                    r["item_key"],
                    r.get("entity_type"),
                    r.get("rank_pos"),
                    r.get("recent_cnt"),
                    r.get("prior_cnt"),
                    r.get("velocity"),
                    r.get("emerging_score"),
                    r.get("avg_cite"),
                    r.get("avg_if"),
                    r.get("gap_phase"),
                    r.get("top_pmids"),
                )
                for r in rows
            ],
        )
        return len(rows)


def get_weekly_hotspot_snapshots(
    week_id: str,
    board: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["week_id = ?"]
    params: list[Any] = [week_id]
    if board:
        clauses.append("board = ?")
        params.append(board)
    where = " AND ".join(clauses)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT week_id, board, item_key, entity_type, rank_pos,
                       recent_cnt, prior_cnt, velocity, emerging_score,
                       avg_cite, avg_if, gap_phase, top_pmids
                FROM weekly_hotspot_snapshots
                WHERE {where}
                ORDER BY board, rank_pos ASC, emerging_score DESC""",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def list_weekly_hotspot_weeks(limit: int = 12) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT week_id FROM weekly_hotspot_runs
               ORDER BY snapshot_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [r["week_id"] for r in rows]


def weekly_hotspot_stats() -> dict[str, int]:
    with get_conn() as conn:
        return {
            "hotspot_runs": conn.execute(
                "SELECT COUNT(*) FROM weekly_hotspot_runs"
            ).fetchone()[0],
            "hotspot_snapshot_rows": conn.execute(
                "SELECT COUNT(*) FROM weekly_hotspot_snapshots"
            ).fetchone()[0],
        }
