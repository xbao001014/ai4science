"""Locate literal evidence spans; never repair a paraphrase by semantic guessing."""
from __future__ import annotations
import re
from extractor.evidence_support import annotate_evidence_support
from extractor.triple_models import Triple
from extractor.mention_context import local_context, method_expansion


def locate_quote(text: str, quote: str | None) -> tuple[int,int] | None:
    if not quote or not quote.strip(): return None
    parts=re.split(r'\s+',quote.strip())
    match=re.search(r'\s+'.join(re.escape(p) for p in parts),text)
    return (match.start(),match.end()) if match else None


def ground_triples(
    triples: list[Triple], source: str,
    *, abbreviation_map: dict[str, tuple[str, str]] | None = None,
) -> tuple[list[Triple],list[dict]]:
    """Require a contiguous source quote. Location is not semantic entailment."""
    accepted=[];rejected=[]
    for triple in triples:
        span=locate_quote(source,triple.evidence_quote)
        if span is None:
            rejected.append({'relation':triple.relation,'object':triple.object.name,
                             'reason':'evidence_quote_not_located'})
            continue
        start,end=span
        long_form, definition_quote = ('', '')
        if triple.object.type == 'Method':
            long_form, definition_quote = method_expansion(
                triple.object.name, abbreviation_map or {}
            )
        disease_long_form, disease_definition_quote = ('', '')
        if triple.object.type == 'Disease':
            disease_long_form, disease_definition_quote = method_expansion(
                triple.object.name, abbreviation_map or {}
            )
        located = triple.model_copy(update={
            'evidence_quote':source[start:end],
            'evidence_start':start,'evidence_end':end,'evidence_status':'located',
            'mention_context':local_context(source, start, end),
            'method_long_form':long_form or None,
            'method_definition_quote':definition_quote or None,
            'disease_long_form':disease_long_form or None,
            'disease_definition_quote':disease_definition_quote or None,
            'disease_qualifiers':[
                qualifier for qualifier in triple.disease_qualifiers
                if triple.object.type == 'Disease'
                and qualifier.phrase.casefold() in source[start:end].casefold()
                and qualifier.phrase.casefold() in triple.object.name.casefold()
                and qualifier.phrase.casefold() != triple.object.name.casefold()
            ],
        })
        accepted.append(annotate_evidence_support(located))
    return accepted,rejected
