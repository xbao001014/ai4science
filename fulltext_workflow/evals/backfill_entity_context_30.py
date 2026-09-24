"""Offline context enrichment of frozen entity relations in an isolated DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from extractor.evidence_grounding import locate_quote  # noqa: E402
from extractor.mention_context import (  # noqa: E402
    abbreviation_definitions, local_context, method_expansion,
)


def backfill(db: Path, baseline: Path) -> dict:
    if db.resolve() == Path(config.DB_PATH).resolve():
        raise ValueError('Refusing to backfill the production database')
    pmids = [p['pmid'] for p in json.loads(baseline.read_text(encoding='utf-8'))['papers']]
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    counts = {'papers': len(pmids), 'evidence_rows': 0, 'located_contexts': 0,
              'method_long_forms': 0, 'unlocated_quotes': 0}
    try:
        columns = {r[1] for r in conn.execute('PRAGMA table_info(relation_evidence)')}
        for column in ('context_text', 'method_long_form', 'method_definition_quote'):
            if column not in columns:
                conn.execute(f'ALTER TABLE relation_evidence ADD COLUMN {column} TEXT')
        for pmid in pmids:
            paper = conn.execute('SELECT id,abstract FROM papers WHERE pmid=?', (pmid,)).fetchone()
            sections = [dict(row) for row in conn.execute(
                'SELECT section_type,content FROM document_sections WHERE paper_id=? ORDER BY order_idx,id',
                (paper['id'],),
            )]
            if paper['abstract']:
                sections.append({'section_type': 'abstract', 'content': paper['abstract']})
            definitions = abbreviation_definitions(s['content'] or '' for s in sections)
            relations = conn.execute("""
                SELECT r.id, r.evidence_quote, r.evidence_section, e.type, e.name
                FROM relations r
                JOIN entities e ON e.id=r.object_id
                WHERE r.source_pmid=? AND COALESCE(r.status,'active')='active'
            """, (pmid,)).fetchall()
            for relation in relations:
                evidence = conn.execute(
                    'SELECT id,evidence_quote,evidence_section FROM relation_evidence WHERE relation_id=?',
                    (relation['id'],),
                ).fetchall()
                if evidence:
                    candidates = [(row['id'], row['evidence_quote'], row['evidence_section'])
                                  for row in evidence]
                else:
                    quote = str(relation['evidence_quote'] or '').strip()
                    candidates = [(None, quote, relation['evidence_section'])]
                    if '; ' in quote:
                        candidates.extend((None, part.strip(), relation['evidence_section'])
                                          for part in quote.split('; ') if part.strip())
                for candidate_index, (evidence_id, quote, evidence_section) in enumerate(candidates):
                    if not quote:
                        continue
                    ordered = sorted(sections,
                        key=lambda s: s['section_type'] != evidence_section)
                    match = next(((s, span) for s in ordered
                        if (span := locate_quote(s['content'] or '', quote)) is not None), None)
                    if match is None:
                        counts['unlocated_quotes'] += 1
                        continue
                    section, (start, end) = match
                    context = local_context(section['content'], start, end)
                    long_form, definition_quote = (
                        method_expansion(relation['name'], definitions)
                        if relation['type'] == 'Method' else ('', '')
                    )
                    if evidence_id is None:
                        digest = hashlib.sha256(quote.encode('utf-8')).hexdigest()
                        conn.execute("""INSERT OR IGNORE INTO relation_evidence
                            (relation_id,source_pmid,evidence_section,evidence_quote,
                             evidence_start,evidence_end,evidence_status,support_status,
                             extraction_granularity,extraction_pass,evidence_sha256)
                            VALUES (?,?,?,?,?,?,'located','unchecked','fulltext',
                                    'context_backfill',?)""",
                            (relation['id'], pmid, section['section_type'], quote,
                             start, end, digest),
                        )
                        row = conn.execute("""SELECT id FROM relation_evidence
                            WHERE relation_id=? AND evidence_sha256=?
                            AND evidence_start=? AND evidence_end=?""",
                            (relation['id'], digest, start, end),
                        ).fetchone()
                        evidence_id = row['id'] if row else None
                    if evidence_id is None:
                        continue
                    conn.execute("""UPDATE relation_evidence SET context_text=?,
                        method_long_form=?, method_definition_quote=? WHERE id=?""",
                        (context or None, long_form or None, definition_quote or None,
                         evidence_id),
                    )
                    counts['evidence_rows'] += 1
                    counts['located_contexts'] += bool(context)
                    counts['method_long_forms'] += bool(long_form)
                    if evidence or (candidate_index == 0 and len(candidates) > 1):
                        break
        conn.commit()
    finally:
        conn.close()
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--before', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(backfill(args.db, args.before), ensure_ascii=False))
