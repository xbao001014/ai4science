"""Normalize optional method-role hints emitted by the extractor."""
from extractor.triple_models import Triple
from extractor.study_prompts.shared import SECTION_SHARED_CORE


def _section_extractor(monkeypatch):
    import config

    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-key")
    from extractor import section_extractor

    return section_extractor


def _triple(method_role_hint: str) -> Triple:
    return Triple.model_validate(
        {
            "subject": {"name": "paper", "type": "Method"},
            "relation": "APPLIES_METHOD",
            "object": {"name": "resnet-50", "type": "Method"},
            "method_role_hint": method_role_hint,
        }
    )


def test_method_role_hint_normalized():
    assert _triple("BackBone").method_role_hint == "backbone"


def test_method_role_hint_invalid_dropped():
    assert _triple("framework").method_role_hint is None


def test_prompt_defines_method_role_hint_policy():
    assert "method_role_hint" in SECTION_SHARED_CORE
    for role in ("backbone", "aggregator", "classical_ml", "tool", "unknown"):
        assert f"- {role}:" in SECTION_SHARED_CORE


def test_section_upsert_uses_method_role_hint(monkeypatch):
    section_extractor = _section_extractor(monkeypatch)

    upserts = []

    def fake_upsert(name, entity_type, **kwargs):
        upserts.append((name, entity_type, kwargs))
        return 1

    monkeypatch.setattr(section_extractor, "upsert_entity", fake_upsert)
    monkeypatch.setattr(section_extractor, "insert_relation", lambda **kwargs: 1)

    section_extractor._save_triple(
        _triple("aggregator"),
        paper_id=7,
        pmid="123",
        evidence_section="methods",
        granularity="section",
    )

    assert upserts == [
        ("resnet-50", "Method", {"access_class": None, "method_role": "aggregator"})
    ]


def test_related_to_object_upsert_uses_method_role_hint(monkeypatch):
    section_extractor = _section_extractor(monkeypatch)

    upserts = []

    def fake_upsert(name, entity_type, **kwargs):
        upserts.append((name, entity_type, kwargs))
        return len(upserts)

    monkeypatch.setattr(section_extractor, "upsert_entity", fake_upsert)
    monkeypatch.setattr(section_extractor, "insert_relation", lambda **kwargs: 1)
    triple = Triple.model_validate(
        {
            "subject": {"name": "clam", "type": "Method"},
            "relation": "RELATED_TO",
            "object": {"name": "attention pooling", "type": "Method"},
            "method_role_hint": "aggregator",
        }
    )

    section_extractor._save_triple(
        triple,
        paper_id=7,
        pmid="123",
        evidence_section="methods",
        granularity="section",
    )

    assert upserts == [
        ("clam", "Method", {}),
        ("attention pooling", "Method", {"method_role": "aggregator"}),
    ]
