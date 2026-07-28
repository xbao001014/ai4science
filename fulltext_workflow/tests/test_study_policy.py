from extractor.triple_models import Triple
from extractor import study_policy as sp


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


def _t(rel: str, otype: str, name: str = "x", quote: str | None = "q") -> Triple:
    return Triple.model_validate(
        {
            "subject": {"name": "paper", "type": "Method"},
            "relation": rel,
            "object": {"name": name, "type": otype},
            "evidence_quote": quote,
        }
    )


def test_review_drops_dataset_relations(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy(
        [_t("USES_DATASET", "Dataset"), _t("RELEASES_DATASET", "Dataset")],
        "review",
    )
    assert out == []


def test_review_remaps_applies_to_surveys(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy([_t("APPLIES_METHOD", "Method", "clam")], "review")
    assert len(out) == 1
    assert out[0].relation == "SURVEYS_METHOD"


def test_review_targets_without_quote_dropped(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy(
        [_t("TARGETS_DISEASE", "Disease", "lung adenocarcinoma", quote=None)],
        "review",
    )
    assert out == []


def test_review_targets_with_quote_becomes_covers(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy(
        [_t("TARGETS_DISEASE", "Disease", "lung adenocarcinoma", quote="covers NSCLC")],
        "review",
    )
    assert len(out) == 1
    assert out[0].relation == "COVERS_DISEASE"


def test_ai_algorithm_keeps_applies(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy([_t("APPLIES_METHOD", "Method", "clam")], "ai_algorithm")
    assert out[0].relation == "APPLIES_METHOD"


def test_other_denies_new_relations(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy([_t("SURVEYS_METHOD", "Method", "clam")], "other")
    assert out == []


def test_foundation_allows_pretrains_on(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    out = sp.apply_policy([_t("PRETRAINS_ON", "Dataset", "tcga")], "foundation_model")
    assert len(out) == 1
    assert out[0].relation == "PRETRAINS_ON"
