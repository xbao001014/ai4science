import json

from extractor import section_extractor


def test_section_prompt_only_includes_explicit_abbreviations_present_in_section(monkeypatch):
    seen = {}

    def fake_llm(system, user):
        seen['system'] = system
        seen['user'] = user
        return {'triples': []}

    monkeypatch.setattr(section_extractor, 'llm_call_structured', fake_llm)
    monkeypatch.setattr(section_extractor.config, 'EXTRACT_METHOD_CONTEXT_PROMPT', True)
    section_extractor._extract_from_text(
        'Title', 'methods', 'Methods', 'We use HIPT for classification.',
        study_type='ai_algorithm',
        abbreviation_map={
            'hipt': ('Hierarchical image pyramid transformer',
                     'Hierarchical image pyramid transformer (HIPT)'),
            'clam': ('Clustering-constrained attention multiple instance learning',
                     'Clustering-constrained attention multiple instance learning (CLAM)'),
        },
    )
    payload = json.loads(seen['user'].split('\n', 1)[1].split('\nExtract supported', 1)[0])
    assert payload['paper_abbreviations'] == [{
        'short': 'hipt',
        'long_form': 'Hierarchical image pyramid transformer',
        'definition_quote': 'Hierarchical image pyramid transformer (HIPT)',
    }]
    assert 'not relation evidence' in seen['user']


def test_method_context_prompt_is_off_by_default(monkeypatch):
    seen = {}

    def fake_llm(system, user):
        seen['system'] = system
        seen['user'] = user
        return {'triples': []}

    monkeypatch.setattr(section_extractor, 'llm_call_structured', fake_llm)
    monkeypatch.setattr(section_extractor.config, 'EXTRACT_METHOD_CONTEXT_PROMPT', False)
    section_extractor._extract_from_text(
        'Title', 'methods', 'Methods', 'We use HIPT for classification.',
        abbreviation_map={'hipt': ('Hierarchical image pyramid transformer',
                                   'Hierarchical image pyramid transformer (HIPT)')},
    )
    assert 'paper_abbreviations' not in seen['user']
    assert 'Method abbreviation context:' not in seen['system']
