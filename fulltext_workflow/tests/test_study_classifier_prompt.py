from extractor import study_classifier as sc


def test_classifier_system_has_scholar_lenses():
    text = sc._STUDY_TYPE_SYSTEM
    assert "benchmark" in text.lower() or "dataset construction" in text.lower()
    assert "pre-trained" in text.lower() or "foundation" in text.lower()
    assert "survey" in text.lower() or "narrative" in text.lower()
