from extractor.study_prompts import PACKS, build_section_system, build_reconcile_system


def test_all_eight_packs_present():
    for st in (
        "ai_algorithm",
        "clinical_study",
        "review",
        "meta_analysis",
        "dataset_benchmark",
        "foundation_model",
        "multimodal",
        "other",
    ):
        assert st in PACKS
        assert PACKS[st].section_lens.strip()
        assert PACKS[st].reconcile_lens.strip()


def test_review_section_system_mentions_survey_not_applies():
    text = build_section_system("methods", "review")
    assert "SURVEYS_METHOD" in text
    assert "review" in text.lower()
    # Section focus must not override pack into APPLIES_METHOD
    focus = text.split("Section focus:", 1)[1]
    assert "SURVEYS_METHOD" in focus
    assert "APPLIES_METHOD only" not in focus
    assert "Do NOT emit APPLIES_METHOD" in focus


def test_review_abstract_prefers_survey_relations():
    text = build_section_system("abstract", "meta_analysis")
    focus = text.split("Section focus:", 1)[1]
    assert "COVERS_DISEASE" in focus
    assert "SURVEYS_METHOD" in focus
    assert "APPLIES_METHOD; baselines" not in focus


def test_dataset_benchmark_mentions_releases():
    text = build_section_system("methods", "dataset_benchmark")
    assert "RELEASES_DATASET" in text


def test_foundation_pack_forbids_releases_dataset():
    pack = PACKS["foundation_model"]
    combined = pack.section_lens + pack.reconcile_lens
    assert "PRETRAINS_ON" in combined
    assert "Do NOT emit RELEASES_DATASET" in combined or "No RELEASES_DATASET" in combined


def test_reconcile_foundation_mentions_pretrain():
    text = build_reconcile_system("foundation_model")
    assert "PRETRAINS_ON" in text or "pretrain" in text.lower()


def test_reconcile_core_mentions_recommendations():
    from extractor.study_prompts.shared import RECONCILE_SHARED_CORE

    assert '"recommendations"' in RECONCILE_SHARED_CORE
    assert "action_type" in RECONCILE_SHARED_CORE
    assert "author_stated" in RECONCILE_SHARED_CORE
    assert "synthesized" in RECONCILE_SHARED_CORE
