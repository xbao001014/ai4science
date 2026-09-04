"""Offline quality contracts: literal grounding, grading and research provenance."""
import copy
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'evals')]
from extractor.evidence_grounding import locate_quote,ground_triples
from extractor.triple_models import Triple
from analysis.research_quality import evidence_records,with_evidence_records,validate_review
from quality_cases import EXTRACTION,RESEARCH
from run_quality_eval import grade_extraction,grade_research


def triple(quote='We use CLAM.',name='clam'):
    return Triple.model_validate({'subject':{'name':'paper','type':'Method'},
        'relation':'APPLIES_METHOD','object':{'name':name,'type':'Method'},'evidence_quote':quote})


def review(ref='EV-A',quote='The question remains unresolved.',bucket='verified_gaps'):
    return {bucket:[{'candidate_id':'G01','title':'Scoped question','evidence_refs':[
        {'evidence_id':ref,'quote':quote,'stance':'supports_gap' if bucket=='verified_gaps' else 'context'}]}]}


EVIDENCE=[{'evidence_id':'EV-A','text':'The question remains unresolved.','year':2025}]


def test_quote_offsets_and_whitespace():
    source='Prefix. We\n use CLAM. Suffix.'
    got,_=ground_triples([triple()],source)
    assert len(got)==1 and source[got[0].evidence_start:got[0].evidence_end]==got[0].evidence_quote
    assert got[0].evidence_status=='located'


@pytest.mark.parametrize('quote',[None,'','We use ... CLAM.','We applied CLAM.','we use CLAM.'])
def test_unlocated_quote_is_not_repaired(quote):
    kept,rejected=ground_triples([triple(quote)],'We use CLAM.')
    assert not kept and rejected[0]['reason']=='evidence_quote_not_located'


def test_model_supplied_offsets_are_overwritten():
    t=triple().model_copy(update={'evidence_start':999,'evidence_end':1000,'evidence_status':'located'})
    kept,_=ground_triples([t],'We use CLAM.')
    assert kept[0].evidence_start==0


def test_grounding_does_not_claim_entailment():
    # Located but wrong relation/name must still fail the independent semantic grader.
    t=triple('We use CLAM.','invented')
    kept,_=ground_triples([t],'We use CLAM.')
    assert kept
    case={'relations':['APPLIES_METHOD'],'text':'We use CLAM.',
          'gold':[{'relation':'APPLIES_METHOD','aliases':['clam'],'value':None}]}
    grade=grade_extraction(case,[kept[0].model_dump()])
    assert grade['fp']==1 and grade['fn']==1


def test_empty_extraction_loses_positive_recall():
    assert grade_extraction(EXTRACTION[0],[])['fn']==2
    assert not grade_extraction(EXTRACTION[0],[])['pass']


def test_duplicate_extraction_cannot_inflate_tp():
    case={'relations':['APPLIES_METHOD'],'text':'We use CLAM.',
          'gold':[{'relation':'APPLIES_METHOD','aliases':['clam'],'value':None}]}
    t=triple().model_dump();grade=grade_extraction(case,[t,t])
    assert grade['tp']==grade['predicted']==1


def test_valid_review_retains_supported_opportunity():
    got=validate_review(review(),EVIDENCE,candidate_ids={'G01'},cutoff_year=2026)
    assert len(got['verified_gaps'])==1 and got['quality_audit']['status']=='provenance_checked'


@pytest.mark.parametrize('ref,quote',[('EV-FAKE','The question remains unresolved.'),('EV-A','Invented paraphrase.')])
def test_invalid_reference_downgrades(ref,quote):
    got=validate_review(review(ref,quote),EVIDENCE)
    assert not got['verified_gaps'] and got['weak_evidence_gaps']


def test_after_cutoff_cannot_support_gap():
    ev=[{**EVIDENCE[0],'year':2027}]
    got=validate_review(review(),ev,cutoff_year=2026)
    assert not got['verified_gaps']


def test_error_record_can_explain_abstention_only():
    ev=[{**EVIDENCE[0],'error':'lookup_failed'}]
    assert not validate_review(review(),ev)['verified_gaps']
    assert validate_review(review(bucket='weak_evidence_gaps'),ev)['quality_audit']['status']=='provenance_checked'


def test_duplicate_candidate_cannot_remain_verified():
    obj=review();obj['weak_evidence_gaps']=copy.deepcopy(obj['verified_gaps'])
    got=validate_review(obj,EVIDENCE)
    assert not got['verified_gaps'] and got['quality_audit']['status']=='needs_verification'


def test_review_input_not_mutated():
    obj=review();before=copy.deepcopy(obj);validate_review(obj,EVIDENCE)
    assert obj==before


def test_composite_quotes_not_attached_to_representative_pmid():
    records=evidence_records({'source_pmid':'123','quotes':'quote A, quote B'})
    assert not records


def test_source_quote_has_stable_identifier_and_signature():
    def query(keyword):return {'data':[{'source_pmid':'123','evidence_quote':'A limitation.'}]}
    wrapper=with_evidence_records({'query':query})['query']
    import inspect
    assert str(inspect.signature(wrapper))==str(inspect.signature(query))
    a=wrapper(keyword='x');b=wrapper(keyword='x')
    assert a['_evidence_records']==b['_evidence_records']
    assert a['_evidence_records'][0]['kind']=='source'


def test_unknown_and_missing_candidate_ids_are_visible():
    got=validate_review(review(),EVIDENCE,candidate_ids={'G02'})
    assert 'missing_candidate:G02' in got['quality_audit']['issues']


def test_malformed_ids_do_not_crash():
    obj=review();obj['verified_gaps'][0]['candidate_id']={}
    obj['verified_gaps'][0]['evidence_refs'][0]['evidence_id']=[]
    assert not validate_review(obj,EVIDENCE)['verified_gaps']


def test_mixed_buckets_invalid_under_frozen_classifier():
    assert grade_research(RESEARCH[0],{'verified_gaps':[{}],'false_gaps':[{}]})['predicted']=='invalid'


def test_explicit_scope_mismatch_cannot_be_a_refutation():
    evidence=[{'evidence_id':'EV-OFF','year':2025,
        'text':'The study evaluates nuclei segmentation in breast cancer WSI, not lung adenocarcinoma survival.'}]
    obj={'verified_gaps':[],'false_gaps':[{'candidate_id':'G01','title':'External survival validation',
        'evidence_refs':[{'evidence_id':'EV-OFF','quote':evidence[0]['text'],'stance':'refutes_gap'}]}],
        'weak_evidence_gaps':[]}
    got=validate_review(obj,evidence,candidate_ids={'G01'},cutoff_year=2026)
    assert not got['false_gaps'] and len(got['weak_evidence_gaps'])==1
    assert 'scope_mismatch_is_not_refutation' in got['weak_evidence_gaps'][0]['provenance_issues']


def test_empty_positive_gets_one_bounded_recall_check(monkeypatch):
    from extractor import section_extractor as se
    responses=iter([{'triples':[]},{'triples':[triple().model_dump()]}]);calls=[]
    def fake(system,user):calls.append(user);return next(responses)
    monkeypatch.setattr(se,'llm_call_structured',fake)
    audit={}
    got=se._extract_from_text('Study','methods','Methods','We use CLAM.',study_type='ai_algorithm',audit=audit)
    assert len(got)==1 and len(calls)==2 and audit['empty_recheck']


def test_genuine_negative_not_retried(monkeypatch):
    from extractor import section_extractor as se
    calls=[]
    def fake(*args):calls.append(1);return {'triples':[]}
    monkeypatch.setattr(se,'llm_call_structured',fake)
    assert se._extract_from_text('Thanks','other','Acknowledgments','We thank the staff.',study_type='other')==[]
    assert len(calls)==1


def test_failed_api_payload_not_semantically_retried(monkeypatch):
    from extractor import section_extractor as se
    calls=[]
    def fake(*args):calls.append(1);return {}
    monkeypatch.setattr(se,'llm_call_structured',fake)
    assert se._extract_from_text('Study','methods','Methods','We use CLAM.',study_type='ai_algorithm')==[]
    assert len(calls)==1


def test_extraction_entry_rejects_unlocated_evidence(monkeypatch):
    from extractor import section_extractor as se
    monkeypatch.setattr(se,'llm_call_structured',lambda *_:{'triples':[triple('We ... CLAM.').model_dump()]})
    audit={}
    assert se._extract_from_text('Study','methods','Methods','We use CLAM.',study_type='ai_algorithm',audit=audit)==[]
    assert audit['rejected'][0]['reason']=='evidence_quote_not_located'
