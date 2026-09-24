"""Identifier-aware imports for literature found outside PubMed."""
from __future__ import annotations

import json
import re
from typing import Any

from db.schema import get_conn


def normalize_doi(value: str | None) -> str:
    return (value or "").strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def upsert_source_paper(data: dict[str, Any], *, source: str, external_id: str, group: str) -> tuple[int, bool]:
    """Return (paper_id, created). PMID stays NULL when the source has none.

    Matching is exact on source ID, PMID or DOI. Title similarity is deliberately
    not used to merge preprints with potentially different published versions.
    """
    source, external_id = _clean(source).lower(), _clean(external_id)
    if not source or not external_id:
        raise ValueError("source and external_id are required")
    title = _clean(data.get("title"))
    if not title:
        raise ValueError("title is required")
    pmid = _clean(data.get("pmid"))
    doi = normalize_doi(data.get("doi"))
    source_key = f"{source}:{external_id}"
    marker = f"{source}:{group}"
    with get_conn() as conn:
        row = conn.execute(
            """SELECT p.id, p.source_queries FROM paper_external_ids x
               JOIN papers p ON p.id=x.paper_id
               WHERE x.source=? AND x.external_id=?""",
            (source, external_id),
        ).fetchone()
        if row is None and pmid:
            row = conn.execute("SELECT id, source_queries FROM papers WHERE pmid=?", (pmid,)).fetchone()
        if row is None and doi:
            row = conn.execute(
                "SELECT id, source_queries FROM papers WHERE lower(doi)=?", (doi,)
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id, source_queries FROM papers WHERE source_key=?", (source_key,)
            ).fetchone()

        created = row is None
        if created:
            pub_date = _clean(data.get("pub_date"))
            year = data.get("year") or (int(pub_date[:4]) if pub_date[:4].isdigit() else None)
            conn.execute(
                """INSERT INTO papers
                   (pmid, source_key, doi, pmc_id, title, abstract, pub_date, year,
                    date_precision, journal_name, journal_abbr, issn, pub_types,
                    mesh_terms, keywords, source_queries, open_access, full_text_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    pmid or None, None if pmid else source_key, doi or None,
                    _clean(data.get("pmc_id")) or None, title,
                    _clean(data.get("abstract")), pub_date or None, year,
                    data.get("date_precision") or "unknown",
                    _clean(data.get("journal_name")), _clean(data.get("journal_abbr")),
                    _clean(data.get("issn")), json.dumps(data.get("pub_types") or []),
                    json.dumps(data.get("mesh_terms") or []),
                    json.dumps(data.get("keywords") or []), json.dumps([marker]),
                    int(bool(data.get("open_access"))),
                    "pending" if pmid else "unavailable",
                ),
            )
            paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            paper_id = row["id"]
            queries = set(json.loads(row["source_queries"] or "[]"))
            queries.add(marker)
            conn.execute(
                """UPDATE papers SET
                   pmid=COALESCE(NULLIF(pmid, ''), NULLIF(?, '')),
                   doi=COALESCE(NULLIF(doi, ''), NULLIF(?, '')),
                   pmc_id=COALESCE(NULLIF(pmc_id, ''), NULLIF(?, '')),
                   abstract=COALESCE(NULLIF(abstract, ''), NULLIF(?, '')),
                   journal_name=COALESCE(NULLIF(journal_name, ''), NULLIF(?, '')),
                   full_text_status=CASE
                     WHEN pmid IS NULL AND NULLIF(?, '') IS NOT NULL
                          AND full_text_status='unavailable' THEN 'pending'
                     ELSE full_text_status END,
                   source_queries=? WHERE id=?""",
                (pmid, doi, _clean(data.get("pmc_id")), _clean(data.get("abstract")),
                 _clean(data.get("journal_name")), pmid,
                 json.dumps(sorted(queries)), paper_id),
            )

        existing_id = conn.execute(
            "SELECT paper_id FROM paper_external_ids WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
        if existing_id is not None and existing_id["paper_id"] != paper_id:
            raise ValueError(f"conflicting {source} identifier: {external_id}")
        conn.execute(
            "INSERT OR IGNORE INTO paper_external_ids(paper_id, source, external_id) VALUES (?,?,?)",
            (paper_id, source, external_id),
        )
        journal_name = _clean(data.get("journal_name"))
        if journal_name:
            issn = _clean(data.get("issn"))
            journal = (conn.execute("SELECT id FROM journals WHERE issn=?", (issn,)).fetchone()
                       if issn else None)
            if journal is None:
                journal = conn.execute("SELECT id FROM journals WHERE name=?", (journal_name,)).fetchone()
            if journal is None:
                conn.execute("INSERT OR IGNORE INTO journals(name,abbr,issn) VALUES (?,?,?)",
                             (journal_name, _clean(data.get("journal_abbr")) or None, issn or None))
                journal = conn.execute("SELECT id FROM journals WHERE name=?", (journal_name,)).fetchone()
            if journal:
                conn.execute("UPDATE papers SET journal_id=? WHERE id=?", (journal["id"], paper_id))

        for order, author in enumerate(data.get("authors") or [], start=1):
            name = _clean(author.get("name"))
            if not name:
                continue
            affiliation = _clean(author.get("affiliation"))
            existing = conn.execute("SELECT id FROM authors WHERE name=? AND affiliation=?",
                                    (name, affiliation)).fetchone()
            if existing is None:
                conn.execute("INSERT INTO authors(name,affiliation,orcid) VALUES (?,?,?)",
                             (name, affiliation, _clean(author.get("orcid")) or None))
                author_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                author_id = existing["id"]
            conn.execute("INSERT OR IGNORE INTO paper_authors(paper_id,author_id,author_order) VALUES (?,?,?)",
                         (paper_id, author_id, order))
        return paper_id, created
