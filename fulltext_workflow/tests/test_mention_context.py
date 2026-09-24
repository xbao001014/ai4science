from extractor.evidence_grounding import ground_triples
from extractor.mention_context import abbreviation_definitions, local_context
from extractor.triple_models import Triple


def _method(name: str, quote: str) -> Triple:
    return Triple.model_validate({
        'subject': {'name': 'paper', 'type': 'Method'},
        'relation': 'APPLIES_METHOD',
        'object': {'name': name, 'type': 'Method'},
        'evidence_quote': quote,
    })


def test_method_expansion_is_paper_local_and_source_grounded():
    introduction = 'We define multiple instance learning (MIL) for slide aggregation.'
    methods = 'Our MIL system aggregates patches. It predicts slide labels.'
    definitions = abbreviation_definitions([introduction, methods])
    grounded, rejected = ground_triples(
        [_method('MIL', 'Our MIL system aggregates patches.')], methods,
        abbreviation_map=definitions,
    )
    assert not rejected
    assert grounded[0].method_long_form == 'multiple instance learning'
    assert grounded[0].method_definition_quote == 'multiple instance learning (MIL)'
    assert grounded[0].mention_context == 'Our MIL system aggregates patches.'
    other_paper, _ = ground_triples([_method('MIL', 'Our MIL system aggregates patches.')], methods)
    assert other_paper[0].method_long_form is None


def test_context_preserves_clause_without_adjacent_unrelated_sentence():
    source = 'The baseline used a CNN. Our CLAM model aggregates slide patches. Patients were enrolled later.'
    start = source.index('Our CLAM')
    end = start + len('Our CLAM model aggregates slide patches.')
    assert local_context(source, start, end) == 'Our CLAM model aggregates slide patches.'


def test_ambiguous_abbreviation_without_explicit_definition_remains_unknown():
    assert abbreviation_definitions(['MIL was used for whole-slide analysis.']) == {}
    assert abbreviation_definitions([
        'Multiple instance learning (MIL) was used.',
        'Multimodal image learning (MIL) was also discussed.',
    ]) == {}


def test_context_is_stored_per_relation_evidence(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db, insert_relation_evidence

    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'mention.db'))
    init_db()
    with get_conn() as conn:
        conn.execute("INSERT INTO entities(name,type) VALUES ('mil','Method')")
        conn.execute("""INSERT INTO relations(subject_type,subject_id,relation,
                     object_type,object_id,source_pmid,evidence_quote)
                     VALUES ('Paper',1,'APPLIES_METHOD','Method',1,'123',
                     'Our MIL model aggregates patches.')""")
        relation_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    evidence_id = insert_relation_evidence(
        relation_id, source_pmid='123', evidence_section='methods',
        evidence_quote='Our MIL model aggregates patches.',
        context_text='Our MIL model aggregates patches.',
        method_long_form='multiple instance learning',
        method_definition_quote='multiple instance learning (MIL)',
    )
    with get_conn() as conn:
        stored = conn.execute('SELECT * FROM relation_evidence WHERE id=?', (evidence_id,)).fetchone()
    assert stored['context_text'] == 'Our MIL model aggregates patches.'
    assert stored['method_long_form'] == 'multiple instance learning'
    assert stored['method_definition_quote'] == 'multiple instance learning (MIL)'
