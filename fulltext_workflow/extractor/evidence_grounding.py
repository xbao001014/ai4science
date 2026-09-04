"""Locate literal evidence spans; never repair a paraphrase by semantic guessing."""
from __future__ import annotations
import re
from extractor.evidence_support import annotate_evidence_support
from extractor.triple_models import Triple


def locate_quote(text: str, quote: str | None) -> tuple[int,int] | None:
    if not quote or not quote.strip(): return None
    parts=re.split(r'\s+',quote.strip())
    match=re.search(r'\s+'.join(re.escape(p) for p in parts),text)
    return (match.start(),match.end()) if match else None


def ground_triples(triples: list[Triple], source: str) -> tuple[list[Triple],list[dict]]:
    """Require a contiguous source quote. Location is not semantic entailment."""
    accepted=[];rejected=[]
    for triple in triples:
        span=locate_quote(source,triple.evidence_quote)
        if span is None:
            rejected.append({'relation':triple.relation,'object':triple.object.name,
                             'reason':'evidence_quote_not_located'})
            continue
        start,end=span
        located = triple.model_copy(update={'evidence_quote':source[start:end],
             'evidence_start':start,'evidence_end':end,'evidence_status':'located'})
        accepted.append(annotate_evidence_support(located))
    return accepted,rejected
