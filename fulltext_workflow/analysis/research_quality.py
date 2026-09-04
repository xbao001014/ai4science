"""Citable evidence records and conservative research-review validation.

Checks provenance/structure only; semantic entailment remains a separately
evaluated model judgment. A valid reference is not proof of global novelty.
"""
from __future__ import annotations
import copy
from functools import wraps
import hashlib
import json
import re

RESEARCH_JUDGMENT_CONTRACT = """
Research judgment contract (overrides looser classification wording):
1. Return each ORIGINAL candidate in exactly ONE of verified_gaps, false_gaps,
   weak_evidence_gaps. Preserve candidate_id (or its original heading identifier).
   Do not emit a rewritten weaker candidate as a second entry. Put revisions in
   suggestion/revision_priority, not another classification bucket.
2. Classify the scientific gap, not merely its rhetoric. An unsupported universal
   claim, zero search hits, failed query, unrelated endpoint/disease or missing
   historical coverage -> weak_evidence_gaps. These do NOT establish that the
   underlying question is solved. Reserve false_gaps for a direct factual
   contradiction or a same-scope completed-study counterexample.
3. verified_gaps requires direct positive evidence of an unresolved scoped
   question; matching corpus counts alone is never enough. Preserve legitimate
   opportunities when supported, but never claim exhaustive worldwide novelty.
4. Check disease, task, cohort/protocol and time cut-off separately. Later papers
   cannot refute an as-of claim. A future-work suggestion is not a completed
   experiment; off-topic evidence neither supports nor directly refutes the gap.
   NEVER put a candidate in false_gaps merely because the supplied study is about
   another disease, endpoint, modality, or task. An explicit scope mismatch means
   weak_evidence_gaps unless a separate same-scope completed counterexample exists.
5. Cite exact IDs provided by evidence_id / _evidence_records. For each candidate
   include evidence_refs:[{"evidence_id":"ID from the current evidence",
   "quote":"one contiguous verbatim substring of that record's text",
   "stance":"supports_gap|refutes_gap|context"}]. Include candidate_id and a
   concise rationale. Do not invent an ID. Use context for limitations/errors.
   If no citable record exists, classify weak_evidence_gaps and state missing
   provenance. Available ID plus valid quote is NOT itself semantic proof.
"""


def _norm(text):return re.sub(r'\s+',' ',str(text or '')).strip()


def _explicit_scope_mismatch(text):
    """Detect records that explicitly describe themselves as off-scope.

    This is deliberately narrow: it prevents an unrelated paper from becoming a
    refutation, but does not attempt general semantic entailment.
    """
    value=_norm(text).lower()
    if re.search(r'\b(?:unrelated|off[- ]topic|different (?:disease|task|endpoint|cohort|modality))\b',value):
        return True
    return bool(
        re.search(r'\b(?:not|rather than)\b',value)
        and re.search(r'\b(?:segmentation|survival|classification|prediction|disease|endpoint|cohort|task)\b',value)
    )


def evidence_records(value, namespace='tool'):
    """Index tool row excerpts, not generated drafts. Stable IDs from content.

    Composite GROUP_CONCAT quotes cannot be attributed to a representative PMID,
    so only singular evidence_quote+source_pmid pairs count as source records.
    Aggregated text remains context and cannot independently verify a gap.
    """
    found={}
    def visit(item,depth=0):
        if depth>12:return
        if isinstance(item,dict):
            if isinstance(item.get('evidence_id'),str) and isinstance(item.get('text'),str):
                record=copy.deepcopy(item)
                record.setdefault('kind','source' if not item.get('error') else 'context')
                eid=record['evidence_id']
                if eid in found and found[eid]!=record:
                    found[eid]={'evidence_id':eid,'text':'','kind':'context','error':'conflicting_evidence_id'}
                else:found[eid]=record
            elif item.get('evidence_quote'):
                text=str(item['evidence_quote'])
                pmid=str(item.get('source_pmid') or '')
                record={'text':text,'source_pmid':pmid,'year':item.get('year'),
                        'kind':'source' if pmid else 'context'}
                digest=hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
                record['evidence_id']='EV-'+digest
                found[record['evidence_id']]=record
            for v in item.values():visit(v,depth+1)
        elif isinstance(item,list):
            for v in item:visit(v,depth+1)
    visit(value)
    return list(found.values())


def with_evidence_records(tools):
    wrapped={}
    for name,fn in tools.items():
        def bind(function,tool_name):
            @wraps(function)
            def call(*args,**kwargs):
                result=function(*args,**kwargs)
                if isinstance(result,dict) and not result.get('error'):
                    records=evidence_records(result,tool_name)
                    if records:result={**result,'_evidence_records':records}
                return result
            return call
        wrapped[name]=bind(fn,name)
    return wrapped


def validate_review(review, evidence, *, candidate_ids=None, cutoff_year=None):
    """Downgrade missing/unlocatable provenance without inventing a decision."""
    result=copy.deepcopy(review) if isinstance(review,dict) else {}
    registry={r['evidence_id']:r for r in evidence_records(evidence)}
    buckets=('verified_gaps','false_gaps','weak_evidence_gaps')
    rows=[];issues=[];seen=set()
    for bucket in buckets:
        value=result.get(bucket,[])
        if not isinstance(value,list):issues.append('invalid_bucket:'+bucket);value=[]
        for original in value:
            if not isinstance(original,dict):issues.append('invalid_candidate');continue
            item=copy.deepcopy(original);cid=item.get('candidate_id');reasons=[]
            if not isinstance(cid,str):cid=None;item['candidate_id']=None
            if not isinstance(cid,str) or not cid.strip():reasons.append('missing_candidate_id')
            if candidate_ids is not None and cid not in candidate_ids:reasons.append('unknown_candidate_id')
            if cid in seen:reasons.append('duplicate_candidate_id')
            seen.add(cid if isinstance(cid,str) else None)
            refs=item.get('evidence_refs',[])
            if not isinstance(refs,list):refs=[]
            valid=[]
            for ref in refs:
                if not isinstance(ref,dict):reasons.append('invalid_reference');continue
                eid=ref.get('evidence_id')
                record=registry.get(eid) if isinstance(eid,str) else None
                quote=_norm(ref.get('quote'))
                if not record:reasons.append('unknown_evidence_id');continue
                if not quote or quote not in _norm(record.get('text')):
                    reasons.append('quote_not_located');continue
                if record.get('error'):
                    # Failure records explain abstention but cannot substantiate support/refutation.
                    if ref.get('stance')!='context':reasons.append('error_is_not_evidence');continue
                year=record.get('year')
                if cutoff_year is not None and isinstance(year,int) and year>cutoff_year and ref.get('stance')!='context':
                    reasons.append('after_cutoff');continue
                valid.append((ref,record))
            if not valid:reasons.append('missing_located_evidence')
            needed={'verified_gaps':'supports_gap','false_gaps':'refutes_gap'}.get(bucket)
            if needed and not any(ref.get('stance')==needed and record.get('kind')=='source' and not record.get('error') for ref,record in valid):
                reasons.append('missing_direct_source')
            if bucket=='false_gaps' and any(
                ref.get('stance')=='refutes_gap' and _explicit_scope_mismatch(record.get('text'))
                for ref,record in valid
            ):
                reasons.append('scope_mismatch_is_not_refutation')
            item['provenance_status']='located' if not reasons else 'needs_verification'
            item['provenance_issues']=sorted(set(reasons))
            if reasons:
                issues.extend(f'{cid or "unknown"}:{r}' for r in sorted(set(reasons)))
                item['original_classification']=bucket
                item['issue']='Unverified provenance: '+', '.join(sorted(set(reasons)))
                bucket_out='weak_evidence_gaps'
            else:bucket_out=bucket
            rows.append((bucket_out,item))
    # Any duplicate invalidates all copies, including an earlier positive entry.
    counts={}
    for _,item in rows:
        cid=item.get('candidate_id')
        if isinstance(cid,str):counts[cid]=counts.get(cid,0)+1
    for bucket in buckets:result[bucket]=[]
    for bucket,item in rows:
        if counts.get(item.get('candidate_id'),0)>1:
            bucket='weak_evidence_gaps';item['provenance_status']='needs_verification'
            item['provenance_issues']=sorted(set(item['provenance_issues']+['duplicate_candidate_id']))
        result[bucket].append(item)
    if candidate_ids:
        issues.extend('missing_candidate:'+c for c in sorted(set(candidate_ids)-seen))
    if not rows:issues.append('empty_review')
    result['quality_audit']={'status':'needs_verification' if issues else 'provenance_checked',
        'issues':sorted(set(issues)),'indexed_evidence_count':len(registry),
        'semantic_entailment':'not_deterministically_verified'}
    return result


def validate_moderator_handoff(report: str, review: dict) -> dict:
    """Check candidate identity and prevent Reviewer-to-Moderator re-promotion.

    This validates workflow state, not scientific usefulness or novelty.
    """
    buckets = ("verified_gaps", "false_gaps", "weak_evidence_gaps")
    ids_by_bucket = {
        bucket: {
            str(item.get("candidate_id"))
            for item in review.get(bucket, [])
            if isinstance(item, dict) and item.get("candidate_id")
        }
        for bucket in buckets
    }
    reviewed = set().union(*ids_by_bucket.values())
    verified = ids_by_bucket["verified_gaps"]
    unverified = ids_by_bucket["false_gaps"] | ids_by_bucket["weak_evidence_gaps"]
    matches = list(re.finditer(r"(?im)^###\s+Research gap\s+(\d+)\s*:[^\n]*", report or ""))
    promoted: list[str] = []
    issues: list[str] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(report or "")
        block = (report or "")[match.start():end]
        found = re.search(r"(?im)^\*\*Candidate ID\*\*\s*:\s*(G\d{2,})\b", block)
        label = f"Research gap {match.group(1)}"
        if not found:
            issues.append(f"missing_candidate_id:{label}")
            continue
        cid = found.group(1)
        promoted.append(cid)
        if cid in unverified:
            issues.append(f"promoted_unverified_candidate:{cid}")
        elif cid not in reviewed:
            issues.append(f"unknown_candidate_id:{cid}")
    duplicates = sorted({cid for cid in promoted if promoted.count(cid) > 1})
    issues.extend(f"duplicate_promoted_candidate:{cid}" for cid in duplicates)
    return {
        "status": "needs_verification" if issues else "handoff_checked",
        "issues": sorted(set(issues)),
        "promoted_candidate_ids": promoted,
        "reviewed_candidate_ids": sorted(reviewed),
        "verified_candidate_ids": sorted(verified),
        "omitted_verified_candidate_ids": sorted(verified - set(promoted)),
        "check_scope": "candidate_identity_and_classification_only",
    }


def enforce_moderator_handoff(report: str, review: dict) -> tuple[str, dict]:
    """Remove final gap sections that were not verified by the Reviewer."""
    verified = {
        str(item.get("candidate_id"))
        for item in review.get("verified_gaps", [])
        if isinstance(item, dict) and item.get("candidate_id")
    }
    text = report or ""
    starts = list(re.finditer(r"(?im)^###\s+Research gap\s+\d+\s*:[^\n]*", text))
    removed: list[str] = []
    missing_id = 0
    pieces: list[str] = []
    cursor = 0
    for idx, match in enumerate(starts):
        following_gap = starts[idx + 1].start() if idx + 1 < len(starts) else len(text)
        following_h2 = re.search(r"(?m)^##\s+", text[match.end():following_gap])
        end = match.end() + following_h2.start() if following_h2 else following_gap
        pieces.append(text[cursor:match.start()])
        block = text[match.start():end]
        found = re.search(r"(?im)^\*\*Candidate ID\*\*\s*:\s*(G\d{2,})\b", block)
        cid = found.group(1) if found else None
        if cid in verified:
            pieces.append(block)
        else:
            if cid:
                removed.append(cid)
            else:
                missing_id += 1
        cursor = end
    pieces.append(text[cursor:])
    filtered = "".join(pieces)
    unverified = {
        str(item.get("candidate_id"))
        for bucket in ("false_gaps", "weak_evidence_gaps")
        for item in review.get(bucket, [])
        if isinstance(item, dict) and item.get("candidate_id")
    }
    filtered = re.sub(
        r"(?im)^\|[^\n]*\|\s*(G\d{2,})\s*\|[^\n]*$",
        lambda m: "" if m.group(1) in unverified else m.group(0),
        filtered,
    )
    if removed or missing_id:
        notice = (
            "> Automated handoff guard removed unverified final-gap sections: "
            + (", ".join(sorted(set(removed))) if removed else "none")
            + (f"; missing candidate ID sections: {missing_id}" if missing_id else "")
            + ".\n\n"
        )
        filtered = notice + filtered.lstrip()
    return filtered, {
        "removed_candidate_ids": sorted(set(removed)),
        "removed_missing_id_sections": missing_id,
        "verified_allowlist": sorted(verified),
    }
