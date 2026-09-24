"""Freeze and compare entity extraction on 30 unchanged full-text papers.

The comparison is descriptive. Human review of changed rows is required before
claiming improved extraction quality.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def choose_papers(conn: sqlite3.Connection, size: int = 30) -> list[str]:
    rows = conn.execute("""
        SELECT p.pmid, COALESCE(NULLIF(p.study_type, ''), 'unknown') AS study_type,
               SUM(CASE WHEN s.section_type IN ('methods', 'results') THEN 1 ELSE 0 END) AS core_sections,
               SUM(CASE WHEN s.section_type IN
                   ('methods','results','discussion','limitations')
                   THEN LENGTH(s.content) ELSE 0 END) AS core_chars,
               (SELECT COUNT(*) FROM relations r WHERE r.source_pmid=p.pmid
                 AND COALESCE(r.status, 'active')='active') AS relation_count,
               (SELECT COUNT(*) FROM relations r JOIN entities e ON e.id=r.object_id
                 WHERE r.source_pmid=p.pmid AND e.type='Method'
                   AND LENGTH(e.name) BETWEEN 2 AND 12
                   AND e.name NOT LIKE '% %') AS short_methods
        FROM papers p JOIN document_sections s ON s.paper_id=p.id
        WHERE p.pmid IS NOT NULL AND p.full_text_status IN ('available', 'pdf_available')
        GROUP BY p.id HAVING core_sections>0 AND relation_count>0
                   AND core_chars BETWEEN 1000 AND 12000
        ORDER BY short_methods DESC, relation_count DESC, p.pmid
    """).fetchall()
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        groups[str(row['study_type'])].append(str(row['pmid']))
    selected: list[str] = []
    while len(selected) < size and any(groups.values()):
        for group in sorted(groups):
            if groups[group] and len(selected) < size:
                selected.append(groups[group].pop(0))
    if len(selected) != size:
        raise ValueError(f"Only {len(selected)} eligible full-text papers")
    return selected


def snapshot(conn: sqlite3.Connection, pmids: list[str]) -> dict:
    papers = []
    relations = []
    context_columns = {r[1] for r in conn.execute('PRAGMA table_info(relation_evidence)')}
    context_select = (
        "re.context_text, re.method_long_form, "
        if {'context_text', 'method_long_form'} <= context_columns else
        "NULL AS context_text, NULL AS method_long_form, "
    )
    for pmid in pmids:
        paper = conn.execute(
            'SELECT id, pmid, title, study_type, extraction_done FROM papers WHERE pmid=?',
            (pmid,),
        ).fetchone()
        sections = conn.execute(
            'SELECT section_type, content FROM document_sections WHERE paper_id=? ORDER BY order_idx, id',
            (paper['id'],),
        ).fetchall()
        source_hash = hashlib.sha256(json.dumps(
            [(s['section_type'], s['content']) for s in sections], ensure_ascii=False
        ).encode('utf-8')).hexdigest()
        papers.append({'pmid': pmid, 'title': paper['title'], 'study_type': paper['study_type'],
                       'extraction_done': int(paper['extraction_done'] or 0),
                       'section_count': len(sections), 'source_sha256': source_hash})
        query = f"""SELECT r.relation, e.type AS entity_type, e.name AS entity_name,
                    r.metric_value, r.evidence_section, r.evidence_quote,
                    {context_select}
                    re.evidence_quote AS located_quote
                    FROM relations r JOIN entities e ON e.id=r.object_id
                    LEFT JOIN relation_evidence re ON re.id=(
                        SELECT MIN(x.id) FROM relation_evidence x WHERE x.relation_id=r.id)
                    WHERE r.source_pmid=? AND COALESCE(r.status,'active')='active'
                    ORDER BY r.relation, e.type, e.name, r.metric_value, r.evidence_quote"""
        relations.extend({'pmid': pmid, **dict(row)} for row in conn.execute(query, (pmid,)))
    return {'papers': papers, 'relations': relations}


def freeze(db: Path, output: Path, pmid_file: Path | None = None) -> None:
    with connect(db) as conn:
        pmids = (
            [line.strip() for line in pmid_file.read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.startswith('#')]
            if pmid_file else choose_papers(conn)
        )
        if len(pmids) != 30 or len(set(pmids)) != 30:
            raise ValueError('The pilot requires 30 unique PMIDs')
        report = snapshot(conn, pmids)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Frozen {len(report['papers'])} papers, {len(report['relations'])} relations: {output}")


def compare(before: Path, after_db: Path, output: Path) -> None:
    baseline = json.loads(before.read_text(encoding='utf-8'))
    pmids = [p['pmid'] for p in baseline['papers']]
    with connect(after_db) as conn:
        current = snapshot(conn, pmids)
    incomplete = [p['pmid'] for p in current['papers'] if not p['extraction_done']]
    if incomplete:
        raise ValueError(f'Pilot extraction is incomplete for {len(incomplete)} papers')
    if [(p['pmid'], p['source_sha256']) for p in baseline['papers']] != [
        (p['pmid'], p['source_sha256']) for p in current['papers']
    ]:
        raise ValueError('The 30 paper source texts changed; comparison is invalid')
    def key(row: dict) -> tuple:
        return tuple(str(row.get(k) or '') for k in
                     ('pmid', 'relation', 'entity_type', 'entity_name', 'metric_value'))
    old = {key(row): row for row in baseline['relations']}
    new = {key(row): row for row in current['relations']}
    types = sorted({row['entity_type'] for row in baseline['relations'] + current['relations']})
    by_type = {
        entity_type: {
            'before': sum(r['entity_type'] == entity_type for r in baseline['relations']),
            'after': sum(r['entity_type'] == entity_type for r in current['relations']),
            'added': sum(item[2] == entity_type for item in new.keys() - old.keys()),
            'removed': sum(item[2] == entity_type for item in old.keys() - new.keys()),
        }
        for entity_type in types
    }
    output.mkdir(parents=True, exist_ok=True)
    columns = ['change', 'pmid', 'relation', 'entity_type', 'entity_name', 'metric_value',
               'before_quote', 'after_quote', 'after_context', 'after_method_long_form',
               'expert_correct_before', 'expert_correct_after', 'review_notes']
    review_rows = []
    for item in sorted(old.keys() | new.keys()):
        a, b = old.get(item), new.get(item)
        review_rows.append(dict(zip(columns[:6],
            ['retained' if a and b else 'removed' if a else 'added', *item]),
            before_quote=(a or {}).get('located_quote') or (a or {}).get('evidence_quote'),
            after_quote=(b or {}).get('located_quote') or (b or {}).get('evidence_quote'),
            after_context=(b or {}).get('context_text'),
            after_method_long_form=(b or {}).get('method_long_form'),
            expert_correct_before='', expert_correct_after='', review_notes=''))
    for filename, rows in (
        ('entity_diff.csv', review_rows),
        ('changes_only.csv', [r for r in review_rows if r['change'] != 'retained']),
        ('short_methods.csv', [r for r in review_rows if r['entity_type'] == 'Method'
            and len(r['entity_name']) <= 12 and ' ' not in r['entity_name']]),
    ):
        with (output / filename).open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    with (output / 'papers.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        paper_columns = ['pmid', 'title', 'study_type', 'before_relations',
                         'after_relations', 'added', 'removed', 'source_sha256']
        writer = csv.DictWriter(handle, fieldnames=paper_columns)
        writer.writeheader()
        for paper in baseline['papers']:
            pmid = paper['pmid']
            writer.writerow({
                'pmid': pmid, 'title': paper['title'], 'study_type': paper['study_type'],
                'before_relations': sum(r['pmid'] == pmid for r in baseline['relations']),
                'after_relations': sum(r['pmid'] == pmid for r in current['relations']),
                'added': sum(r['pmid'] == pmid and r['change'] == 'added' for r in review_rows),
                'removed': sum(r['pmid'] == pmid and r['change'] == 'removed' for r in review_rows),
                'source_sha256': paper['source_sha256'],
            })
    summary = {
        'papers': len(pmids), 'before_relations': len(baseline['relations']),
        'after_relations': len(current['relations']),
        'before_by_type': dict(sorted(Counter(r['entity_type'] for r in baseline['relations']).items())),
        'after_by_type': dict(sorted(Counter(r['entity_type'] for r in current['relations']).items())),
        'by_type_changes': by_type,
        'retained': len(old.keys() & new.keys()), 'removed': len(old.keys() - new.keys()),
        'added': len(new.keys() - old.keys()),
        'after_context_count': sum(bool(r.get('context_text')) for r in current['relations']),
        'after_method_long_form_count': sum(bool(r.get('method_long_form')) for r in current['relations']),
        'short_method_mentions_before': sum(
            r['entity_type'] == 'Method' and len(r['entity_name']) <= 12
            and ' ' not in r['entity_name'] for r in baseline['relations']
        ),
        'short_method_mentions_after_with_expansion': sum(
            r['entity_type'] == 'Method' and len(r['entity_name']) <= 12
            and ' ' not in r['entity_name'] and bool(r.get('method_long_form'))
            for r in current['relations']
        ),
        'quality_verdict': 'pending_expert_review',
    }
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('freeze'); p.add_argument('--db', type=Path, required=True); p.add_argument('--output', type=Path, required=True); p.add_argument('--pmids', type=Path)
    p = sub.add_parser('compare'); p.add_argument('--before', type=Path, required=True); p.add_argument('--after-db', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'freeze': freeze(args.db, args.output, args.pmids)
    else: compare(args.before, args.after_db, args.output)
