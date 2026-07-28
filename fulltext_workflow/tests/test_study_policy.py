from extractor.triple_models import Triple


def test_new_relations_parse_on_triple():
    for rel, otype in (
        ("SURVEYS_METHOD", "Method"),
        ("COVERS_DISEASE", "Disease"),
        ("RELEASES_DATASET", "Dataset"),
        ("PRETRAINS_ON", "Dataset"),
    ):
        t = Triple.model_validate(
            {
                "subject": {"name": "paper", "type": "Method"},
                "relation": rel,
                "object": {"name": "x", "type": otype},
                "evidence_quote": "quoted",
            }
        )
        assert t.relation == rel
