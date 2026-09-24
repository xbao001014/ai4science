"""Fill paper-local annotations for legacy and Pass-2 evidence rows."""
from __future__ import annotations

import re

from db.schema import get_conn, insert_relation_evidence, upsert_entity_mention
from extractor.evidence_grounding import locate_quote
from extractor.mention_context import abbreviation_definitions, local_context, method_expansion


def backfill_paper_mentions(source_pmid: str) -> int:
    """Add missing grounded mentions; never infer a corpus concept match."""
    with get_conn() as conn:
        source_sections = [dict(row) for row in conn.execute(
            """SELECT s.section_type, s.content FROM document_sections s
               JOIN papers p ON p.id=s.paper_id
               WHERE COALESCE(p.source_key,p.pmid)=? ORDER BY s.order_idx,s.id""",
            (source_pmid,),
        )]
        paper = conn.execute(
            "SELECT abstract FROM papers WHERE COALESCE(source_key,pmid)=?",
            (source_pmid,),
        ).fetchone()
        if paper and paper["abstract"]:
            source_sections.append({"section_type": "abstract", "content": paper["abstract"]})
        legacy = [dict(row) for row in conn.execute(
            """SELECT r.id AS relation_id, e.id AS entity_id,
                      e.type AS entity_type, e.name AS entity_name,
                      r.evidence_quote, r.evidence_section,
                      r.extraction_granularity, r.extraction_pass
               FROM relations r JOIN entities e ON e.id=r.object_id
               WHERE r.source_pmid=? AND COALESCE(r.status,'active')='active'
                 AND e.type IN ('Method','Disease')
                 AND NOT EXISTS (SELECT 1 FROM relation_evidence re WHERE re.relation_id=r.id)
                 AND NULLIF(trim(r.evidence_quote),'') IS NOT NULL""",
            (source_pmid,),
        )]
    # Recover old relation-level quotes only when they can be located verbatim.
    for row in legacy:
        quote = str(row["evidence_quote"] or "")
        for section in source_sections:
            content = str(section["content"] or "")
            span = locate_quote(content, quote)
            if span is None:
                continue
            insert_relation_evidence(
                row["relation_id"], source_pmid=source_pmid,
                evidence_section=section["section_type"],
                evidence_quote=content[span[0]:span[1]],
                context_text=local_context(content, *span),
                evidence_start=span[0], evidence_end=span[1],
                evidence_status="located",
                extraction_granularity=row["extraction_granularity"] or "abstract",
                extraction_pass=row["extraction_pass"] or "section",
            )
            break
    with get_conn() as conn:
        rows = [dict(row) for row in conn.execute(
            """SELECT re.id AS evidence_id, r.id AS relation_id, e.id AS entity_id,
                      e.type AS entity_type, e.name AS entity_name,
                      re.evidence_quote
               FROM relations r
               JOIN entities e ON e.id=r.object_id
               JOIN relation_evidence re ON re.relation_id=r.id
               LEFT JOIN entity_mentions m ON m.relation_evidence_id=re.id
               WHERE r.source_pmid=? AND COALESCE(r.status,'active')='active'
                 AND e.type IN ('Method','Disease') AND m.id IS NULL""",
            (source_pmid,),
        )]
    definitions = abbreviation_definitions(str(s["content"] or "") for s in source_sections)
    for row in rows:
        surface = row["entity_name"]
        quote = row["evidence_quote"] or ""
        # Legacy entities may already have collapsed an acronym to a canonical
        # name. Recover only a short form literally present in this evidence.
        for short, (full, _) in definitions.items():
            if full.casefold() != surface.casefold():
                continue
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(short) + r"(?![A-Za-z0-9])", quote, re.I):
                surface = short
                break
        long_form, definition_quote = method_expansion(surface, definitions)
        upsert_entity_mention(
            row["evidence_id"], row["relation_id"],
            source_pmid=source_pmid, entity_type=row["entity_type"],
            surface_name=surface, entity_id=row["entity_id"],
            explicit_long_form=long_form, definition_quote=definition_quote,
            annotation_version="mention/v1-backfill",
        )
    return len(rows)


def enrich_explicit_long_forms(source_pmid: str) -> int:
    """Add newly recognized explicit same-paper definitions to existing mentions."""
    with get_conn() as conn:
        sections = [str(row[0] or "") for row in conn.execute(
            """SELECT s.content FROM document_sections s JOIN papers p ON p.id=s.paper_id
               WHERE COALESCE(p.source_key,p.pmid)=? ORDER BY s.order_idx,s.id""",
            (source_pmid,),
        )]
        rows = [dict(row) for row in conn.execute(
            """SELECT m.id, m.surface_name, re.evidence_quote
               FROM entity_mentions m
               JOIN relation_evidence re ON re.id=m.relation_evidence_id
               WHERE m.source_pmid=? AND m.explicit_long_form IS NULL""",
            (source_pmid,),
        )]
    definitions = abbreviation_definitions(sections)
    updated = 0
    for row in rows:
        surface = row["surface_name"]
        long_form, definition_quote = method_expansion(surface, definitions)
        if not long_form:
            for short, (full, printed) in definitions.items():
                if full.casefold() == surface.casefold() and re.search(
                    r"(?<![A-Za-z0-9])" + re.escape(short) + r"(?![A-Za-z0-9])",
                    row["evidence_quote"] or "", re.I,
                ):
                    surface, long_form, definition_quote = short, full, printed
                    break
        if not long_form:
            continue
        with get_conn() as conn:
            conn.execute(
                """UPDATE entity_mentions SET surface_name=?, explicit_long_form=?,
                   definition_quote=? WHERE id=? AND explicit_long_form IS NULL""",
                (surface, long_form, definition_quote, row["id"]),
            )
        updated += 1
    return updated
