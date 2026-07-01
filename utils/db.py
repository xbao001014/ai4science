"""
utils/db.py
SQLite database layer — schema initialization and CRUD helpers.

Tables:
  papers          — one row per unique paper (keyed by pmid or doi)
  journals        — one row per journal (keyed by issn or name)
  authors         — one row per author (keyed by name+affiliation hash)
  paper_authors   — M:N join table
  extractions     — LLM-extracted triples for each paper
  entities        — deduplicated entity registry
  relations       — triple store (subject_id, relation, object_id, source_pmid)
  citations       — paper → paper cite edges (from S2)
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Generator

from config import DB_PATH


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
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


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────
SCHEMA_SQL = """
-- ── Journals ──────────────────────────────────────────────────────────────
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

-- ── Papers ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS papers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pmid            TEXT UNIQUE,
    doi             TEXT,
    s2id            TEXT,
    title           TEXT NOT NULL,
    abstract        TEXT,
    pub_date        TEXT,              -- ISO date string YYYY-MM-DD
    year            INTEGER,
    journal_id      INTEGER REFERENCES journals(id),
    journal_name    TEXT,              -- raw name before journal lookup
    journal_abbr    TEXT,
    issn            TEXT,
    study_type      TEXT,              -- LLM-classified
    pub_types       TEXT,              -- JSON list from PubMed publication types
    mesh_terms      TEXT,              -- JSON list
    keywords        TEXT,              -- JSON list (author keywords)
    citation_count  INTEGER DEFAULT 0,
    open_access     INTEGER DEFAULT 0, -- 0/1 boolean
    source_queries  TEXT,              -- JSON list of query group names that returned this paper
    extraction_done INTEGER DEFAULT 0, -- 0/1 flag for LLM processing
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_papers_pmid  ON papers(pmid);
CREATE INDEX IF NOT EXISTS idx_papers_doi   ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_year  ON papers(year);
CREATE INDEX IF NOT EXISTS idx_papers_study ON papers(study_type);

-- ── Authors ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS authors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    affiliation TEXT,
    orcid       TEXT,
    UNIQUE(name, affiliation)
);

CREATE TABLE IF NOT EXISTS paper_authors (
    paper_id    INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    author_id   INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    author_order INTEGER,
    PRIMARY KEY (paper_id, author_id)
);

-- ── Entities (nodes other than Paper/Journal/Author) ──────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,         -- Disease/Method/Task/Tissue/Dataset/Metric
    cui         TEXT,                  -- UMLS CUI if available
    aliases     TEXT,                  -- JSON list of alternate names
    UNIQUE(name, type)
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

-- ── Relations / Triples ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type    TEXT NOT NULL,     -- 'Paper' | entity type
    subject_id      INTEGER NOT NULL,  -- FK into papers or entities
    relation        TEXT NOT NULL,     -- e.g. APPLIES_METHOD
    object_type     TEXT NOT NULL,
    object_id       INTEGER NOT NULL,
    metric_value    TEXT,              -- optional, e.g. "AUC=0.95"
    source_pmid     TEXT,
    confidence      REAL DEFAULT 1.0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_relations_subj ON relations(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_obj  ON relations(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_relations_rel  ON relations(relation);

-- ── Citations (Paper → Paper) ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS citations (
    citing_pmid     TEXT NOT NULL,
    cited_pmid      TEXT NOT NULL,
    PRIMARY KEY (citing_pmid, cited_pmid)
);
"""


def init_db() -> None:
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
    print(f"[DB] Initialized database at {DB_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# Paper helpers
# ─────────────────────────────────────────────────────────────────────────────

def upsert_paper(data: dict[str, Any]) -> int:
    """
    Insert or update a paper record. Returns the row id.
    Merges source_queries lists if paper already exists.
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, source_queries FROM papers WHERE pmid=? OR (doi IS NOT NULL AND doi=?)",
            (data.get("pmid"), data.get("doi")),
        ).fetchone()

        # Merge source_queries
        new_queries: list[str] = data.get("source_queries", [])
        if existing:
            old_queries = json.loads(existing["source_queries"] or "[]")
            merged = list(set(old_queries) | set(new_queries))
            conn.execute(
                "UPDATE papers SET source_queries=?, citation_count=COALESCE(?, citation_count),"
                " s2id=COALESCE(?, s2id), open_access=COALESCE(?, open_access) WHERE id=?",
                (
                    json.dumps(merged),
                    data.get("citation_count"),
                    data.get("s2id"),
                    data.get("open_access"),
                    existing["id"],
                ),
            )
            return existing["id"]

        conn.execute(
            """INSERT INTO papers
               (pmid, doi, s2id, title, abstract, pub_date, year,
                journal_name, journal_abbr, issn, pub_types, mesh_terms,
                keywords, citation_count, open_access, source_queries)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.get("pmid"),
                data.get("doi"),
                data.get("s2id"),
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
                data.get("citation_count", 0),
                int(data.get("open_access", False)),
                json.dumps(new_queries),
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_unprocessed_papers(limit: int = 0) -> list[sqlite3.Row]:
    """Return papers that haven't been through LLM extraction yet."""
    with get_conn() as conn:
        sql = "SELECT * FROM papers WHERE extraction_done=0 AND abstract IS NOT NULL AND abstract != ''"
        if limit:
            sql += f" LIMIT {limit}"
        return conn.execute(sql).fetchall()


def mark_extraction_done(paper_id: int, study_type: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET extraction_done=1, study_type=? WHERE id=?",
            (study_type, paper_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Author helpers
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Entity & Relation helpers
# ─────────────────────────────────────────────────────────────────────────────

def upsert_entity(name: str, entity_type: str, cui: str = "") -> int:
    """Insert entity if not exists; returns entity id."""
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
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO relations
               (subject_type, subject_id, relation, object_type, object_id,
                metric_value, source_pmid, confidence)
               VALUES (?,?,?,?,?,?,?,?)""",
            (subject_type, subject_id, relation, object_type, object_id,
             metric_value or None, source_pmid or None, confidence),
        )


def upsert_citation(citing_pmid: str, cited_pmid: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO citations (citing_pmid, cited_pmid) VALUES (?,?)",
            (citing_pmid, cited_pmid),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Journal helpers
# ─────────────────────────────────────────────────────────────────────────────

def upsert_journal(name: str, abbr: str = "", issn: str = "") -> int:
    with get_conn() as conn:
        # Try to find by ISSN first (normalized), then by name
        if issn:
            existing = conn.execute(
                "SELECT id FROM journals WHERE issn=? OR issn=?",
                (issn, issn.replace("-", "")),
            ).fetchone()
        else:
            existing = None
        if existing is None:
            existing = conn.execute("SELECT id FROM journals WHERE name=?", (name,)).fetchone()
        if existing:
            return existing["id"]
        # Use INSERT OR IGNORE to handle race/duplicate ISSN gracefully
        conn.execute(
            "INSERT OR IGNORE INTO journals (name, abbr, issn) VALUES (?,?,?)",
            (name, abbr or None, issn or None),
        )
        # Fetch the id (either newly inserted or pre-existing with same ISSN/name)
        if issn:
            row = conn.execute("SELECT id FROM journals WHERE issn=?", (issn,)).fetchone()
            if row:
                return row["id"]
        row = conn.execute("SELECT id FROM journals WHERE name=?", (name,)).fetchone()
        if row:
            return row["id"]
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def update_journal_if(journal_id: int, impact_factor: float, if_year: int, quartile: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE journals SET impact_factor=?, if_year=?, quartile=? WHERE id=?",
            (impact_factor, if_year, quartile, journal_id),
        )


def link_paper_journal(paper_id: int, journal_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE papers SET journal_id=? WHERE id=?", (journal_id, paper_id))


def get_all_journals() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM journals").fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────

def db_stats() -> dict[str, int]:
    with get_conn() as conn:
        tables = ["papers", "journals", "authors", "entities", "relations", "citations"]
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
