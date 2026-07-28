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


def test_dataset_benchmark_mentions_releases():
    text = build_section_system("methods", "dataset_benchmark")
    assert "RELEASES_DATASET" in text


def test_reconcile_foundation_mentions_pretrain():
    text = build_reconcile_system("foundation_model")
    assert "PRETRAINS_ON" in text or "pretrain" in text.lower()
