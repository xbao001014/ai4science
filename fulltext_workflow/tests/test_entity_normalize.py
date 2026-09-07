"""Tests for Method/Limitation post-processing."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor.entity_normalize import (  # noqa: E402
    has_more_specific_disease,
    is_foundation_llm_product,
    is_generic_disease,
    is_generic_method,
    is_generic_task,
    is_low_value_method,
    is_narrative_task,
    is_organ_level_disease,
    is_radiology_method,
    is_radiology_modality,
    is_reject_task,
    is_umbrella_ai_method,
    normalize_entity_name,
    postprocess_triples,
    repair_triple_relation,
    should_drop_disease,
)
from extractor.triple_models import Entity, Triple  # noqa: E402


def _method_triple(name: str, section: str = "methods") -> Triple:
    return Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="APPLIES_METHOD",
        object=Entity(name=name, type="Method"),
        evidence_quote="test",
    )


def _disease_triple(name: str) -> Triple:
    return Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="TARGETS_DISEASE",
        object=Entity(name=name, type="Disease"),
        evidence_quote="test",
    )


def _modality_triple(name: str) -> Triple:
    return Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="USES_MODALITY",
        object=Entity(name=name, type="Modality"),
        evidence_quote="test",
    )


def _related_methods(a: str, b: str) -> Triple:
    return Triple(
        subject=Entity(name=a, type="Method"),
        relation="RELATED_TO",
        object=Entity(name=b, type="Method"),
        evidence_quote="test",
    )


def test_normalize_limitation_aliases():
    assert normalize_entity_name("Limited Sample Size", "Limitation") == "small sample size"
    assert normalize_entity_name("retrospective study design", "Limitation") == "retrospective design"


def test_drop_generic_method_when_specific_present():
    triples = [
        _method_triple("deep learning"),
        _method_triple("resnet-50 transfer learning"),
    ]
    out = postprocess_triples(triples, "methods")
    names = [t.object.name for t in out if t.relation == "APPLIES_METHOD"]
    assert "deep learning" not in names
    assert "resnet-50 transfer learning" in names


def test_keep_generic_method_when_only_option():
    triples = [_method_triple("machine learning")]
    out = postprocess_triples(triples, "methods")
    assert len(out) == 1
    assert out[0].object.name == "machine learning"
    assert out[0].confidence == 0.5


def test_block_applies_method_in_discussion():
    triples = [_method_triple("u-net segmentation")]
    out = postprocess_triples(triples, "discussion")
    assert out == []


def test_is_generic_method():
    assert is_generic_method("Deep Learning")
    assert not is_generic_method("u-net")


def test_is_low_value_method():
    assert is_low_value_method("Early Stopping")
    assert is_low_value_method("data augmentation")
    assert is_low_value_method("adam optimizer")
    assert is_low_value_method("cosine learning rate schedule")
    assert not is_low_value_method("resnet-50")
    assert not is_low_value_method("hover-net")
    assert not is_low_value_method("dual-attention mil")


def test_is_radiology_method():
    assert is_radiology_method("pyradiomics")
    assert is_radiology_method("Radiomics Model")
    assert is_radiology_method("ai-assisted cbct")
    assert is_radiology_method("mri-mba toolkit")
    assert is_radiology_method("pet assisted reporting system (pars)")
    assert is_radiology_method("quantitative ultrasound")
    assert is_radiology_method("ai-enhanced endoscopy")
    assert is_radiology_method("high-resolution optical coherence tomography")
    assert is_radiology_method(
        "cpnet (ct and pathology mutual guidance fusion diagnostic network)"
    )
    assert is_radiology_method("radiomics")
    assert is_radiology_method("imaging")
    assert is_radiology_method("t1 sagittal model")
    assert is_radiology_method("t1 axial model")
    assert is_radiology_method("t2-weighted mri model")
    assert not is_radiology_method("hover-net")
    assert not is_radiology_method("clam")
    assert not is_radiology_method("dual-attention mil")
    assert not is_radiology_method("resnet-50")
    assert not is_radiology_method("densenet121")
    assert not is_radiology_method("axial attention mil")


def test_is_foundation_llm_product():
    assert is_foundation_llm_product("gpt-5")
    assert is_foundation_llm_product("GPT-4o")
    assert is_foundation_llm_product("chatgpt-4o")
    assert is_foundation_llm_product("ChatGPT")
    assert is_foundation_llm_product("claude 3.5 sonnet")
    assert is_foundation_llm_product("gemini 2.5 pro")
    assert is_foundation_llm_product("llama 3.1 70b")
    assert is_foundation_llm_product("deepseek-r1")
    assert is_foundation_llm_product("qwen2:72b")
    assert is_foundation_llm_product("openai-o1")
    assert is_foundation_llm_product("microsoft copilot")
    assert is_foundation_llm_product("grok 3")
    assert is_foundation_llm_product("mistral 7b")
    assert is_low_value_method("gpt-5")
    assert is_low_value_method("copilot")
    # Domain models that merely contain "gpt" / "llama" as a suffix/stem stay.
    assert not is_foundation_llm_product("histogpt")
    assert not is_foundation_llm_product("seggpt")
    assert not is_foundation_llm_product("cellama")
    assert not is_low_value_method("histogpt")
    assert not is_low_value_method("hover-net")


def test_is_umbrella_ai_method():
    assert is_umbrella_ai_method("deep learning model")
    assert is_umbrella_ai_method("Deep Learning Models")
    assert is_umbrella_ai_method("machine learning models")
    assert is_umbrella_ai_method("ai model")
    assert is_umbrella_ai_method("deep learning-based model")
    assert is_umbrella_ai_method("artificial neural network")
    assert is_umbrella_ai_method("deep neural network")
    assert is_umbrella_ai_method("multimodal machine learning model")
    assert is_low_value_method("deep learning model")
    assert not is_umbrella_ai_method("hover-net")
    assert not is_umbrella_ai_method("attention-based multiple instance learning")
    assert not is_umbrella_ai_method("resnet-50")
    assert not is_low_value_method("clam")


def test_postprocess_drops_umbrella_ai_methods():
    triples = [
        _method_triple("deep learning model"),
        _method_triple("ai model"),
        _method_triple("clam"),
    ]
    out = postprocess_triples(triples, "methods")
    names = [t.object.name for t in out if t.relation == "APPLIES_METHOD"]
    assert names == ["clam"]


def test_postprocess_drops_foundation_llm_products():
    triples = [
        _method_triple("gpt-5"),
        _method_triple("chatgpt-4o"),
        _method_triple("mistral 7b"),
        _method_triple("clam"),
    ]
    out = postprocess_triples(triples, "methods")
    names = [t.object.name for t in out if t.relation == "APPLIES_METHOD"]
    assert names == ["clam"]


def test_is_low_value_includes_radiology_methods():
    assert is_low_value_method("pyradiomics")
    assert is_low_value_method("radiomics model")
    assert not is_low_value_method("hover-net")


def test_postprocess_drops_radiology_methods():
    triples = [
        _method_triple("pyradiomics"),
        _method_triple("radiomics model"),
        _method_triple("ai-assisted cbct"),
        _method_triple("clam"),
    ]
    out = postprocess_triples(triples, "methods")
    names = [t.object.name for t in out if t.relation == "APPLIES_METHOD"]
    assert names == ["clam"]


def test_drop_low_value_methods_always():
    triples = [
        _method_triple("early stopping"),
        _method_triple("data augmentation"),
        _method_triple("clam multiple instance learning"),
    ]
    out = postprocess_triples(triples, "methods")
    names = [t.object.name for t in out if t.relation == "APPLIES_METHOD"]
    assert names == ["clam multiple instance learning"]


def test_drop_low_value_even_when_only_method():
    triples = [_method_triple("mixup")]
    out = postprocess_triples(triples, "methods")
    assert out == []


def test_drop_related_to_low_value_method():
    triples = [
        _related_methods("resnet-50", "early stopping"),
        _related_methods("clam", "transmil"),
    ]
    out = postprocess_triples(triples, "methods")
    assert len(out) == 1
    assert out[0].subject.name == "clam"
    assert out[0].object.name == "transmil"


def test_is_generic_and_organ_level_disease():
    assert is_generic_disease("Cancer")
    assert is_generic_disease("tumor")
    assert is_organ_level_disease("breast cancer")
    assert is_organ_level_disease("NSCLC")
    assert not is_organ_level_disease("her2-positive invasive ductal carcinoma")
    assert not is_organ_level_disease("lung adenocarcinoma")


def test_drop_generic_disease_always():
    triples = [_disease_triple("cancer"), _disease_triple("tumor")]
    out = postprocess_triples(triples, "abstract")
    assert out == []


def test_drop_organ_level_when_subtype_present():
    triples = [
        _disease_triple("breast cancer"),
        _disease_triple("her2-positive invasive ductal carcinoma"),
        _disease_triple("cancer"),
    ]
    out = postprocess_triples(triples, "abstract")
    names = [t.object.name for t in out]
    assert names == ["her2-positive invasive ductal carcinoma"]


def test_keep_organ_level_when_only_option():
    triples = [_disease_triple("Breast Cancer")]
    out = postprocess_triples(triples, "abstract")
    assert len(out) == 1
    assert out[0].object.name == "breast carcinoma"


def test_disease_normalization_preserves_qualified_subtypes():
    assert normalize_entity_name("Breast Cancer", "Disease") == "breast carcinoma"
    assert (
        normalize_entity_name("HER2-positive breast cancer", "Disease")
        == "her2-positive breast cancer"
    )


def test_method_normalization_uses_curated_canonical():
    assert normalize_entity_name("SVM", "Method") == "support vector machine"
    assert normalize_entity_name("Random Forest Classifier", "Method") == "random forest"


def test_has_more_specific_disease_substring():
    cohort = {"breast cancer", "her2-positive breast cancer"}
    assert has_more_specific_disease("breast cancer", cohort)
    assert should_drop_disease("breast cancer", cohort)
    assert not should_drop_disease("her2-positive breast cancer", cohort)


def test_is_radiology_modality():
    assert is_radiology_modality("MRI")
    assert is_radiology_modality("computed tomography")
    assert is_radiology_modality("PET-CT")
    assert is_radiology_modality("radiomics")
    assert not is_radiology_modality("wsi")
    assert not is_radiology_modality("ihc")
    assert not is_radiology_modality("cytology")


def test_drop_radiology_modality_and_normalize_pathology():
    triples = [
        _modality_triple("MRI"),
        _modality_triple("Whole Slide Image"),
        _modality_triple("Immunohistochemistry"),
        _modality_triple("CT"),
    ]
    out = postprocess_triples(triples, "methods")
    names = [t.object.name for t in out]
    assert names == ["wsi", "ihc"]


def test_repair_applies_method_with_task_object():
    t = Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="APPLIES_METHOD",
        object=Entity(name="hpv detection", type="Task"),
        evidence_quote="test",
    )
    fixed = repair_triple_relation(t)
    assert fixed is not None
    assert fixed.relation == "PERFORMS_TASK"
    assert fixed.object.type == "Task"


def test_repair_operates_on_modality_to_uses_modality():
    t = Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="OPERATES_ON",
        object=Entity(name="cytology", type="Modality"),
        evidence_quote="test",
    )
    fixed = repair_triple_relation(t)
    assert fixed is not None
    assert fixed.relation == "USES_MODALITY"


def test_postprocess_repairs_relation_mismatches():
    triples = [
        Triple(
            subject=Entity(name="paper", type="Disease"),
            relation="APPLIES_METHOD",
            object=Entity(name="cervical screening", type="Task"),
            evidence_quote="test",
        ),
        Triple(
            subject=Entity(name="paper", type="Disease"),
            relation="APPLIES_METHOD",
            object=Entity(name="clam", type="Method"),
            evidence_quote="test",
        ),
        Triple(
            subject=Entity(name="paper", type="Disease"),
            relation="OPERATES_ON",
            object=Entity(name="cytology", type="Modality"),
            evidence_quote="test",
        ),
    ]
    out = postprocess_triples(triples, "methods")
    by_rel = {(t.relation, t.object.type, t.object.name) for t in out}
    assert ("PERFORMS_TASK", "Task", "cervical screening") in by_rel
    assert ("APPLIES_METHOD", "Method", "clam") in by_rel
    assert ("USES_MODALITY", "Modality", "cytology") in by_rel


def test_related_to_requires_method_method():
    bad = Triple(
        subject=Entity(name="clam", type="Method"),
        relation="RELATED_TO",
        object=Entity(name="classification", type="Task"),
        evidence_quote="test",
    )
    assert repair_triple_relation(bad) is None
    out = postprocess_triples([bad], "methods")
    assert out == []


def _compares_triple(name: str) -> Triple:
    return Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="COMPARES_METHOD",
        object=Entity(name=name, type="Method"),
        evidence_quote="test",
    )


def test_compares_method_kept_in_methods_section():
    out = postprocess_triples([_compares_triple("clam")], "methods")
    assert len(out) == 1
    assert out[0].relation == "COMPARES_METHOD"
    assert out[0].object.name == "clam"


def test_compares_method_banned_in_introduction():
    out = postprocess_triples([_compares_triple("clam")], "introduction")
    assert out == []


def test_compares_method_drops_low_value():
    out = postprocess_triples([_compares_triple("early stopping")], "methods")
    assert out == []


def test_prefers_applies_over_compares_same_method():
    triples = [
        _method_triple("ssl-histonet"),
        _compares_triple("ssl-histonet"),
        _compares_triple("clam"),
    ]
    out = postprocess_triples(triples, "methods")
    by_rel = {(t.relation, t.object.name) for t in out}
    assert ("APPLIES_METHOD", "ssl-histonet") in by_rel
    assert ("COMPARES_METHOD", "clam") in by_rel
    assert ("COMPARES_METHOD", "ssl-histonet") not in by_rel


def test_postprocess_drops_pubmed_as_dataset():
    t = Triple(
        subject=Entity(name="paper", type="Method"),
        relation="USES_DATASET",
        object=Entity(name="PubMed", type="Dataset"),
        confidence=0.9,
        evidence_quote="searched PubMed",
    )
    out = postprocess_triples([t], "methods")
    assert all(
        not (x.relation == "USES_DATASET" and "pubmed" in x.object.name.lower())
        for x in out
    )


def _triple(
    relation: str,
    obj_type: str,
    name: str,
    *,
    quote: str = "test",
) -> Triple:
    return Triple(
        subject=Entity(name="paper", type="Disease"),
        relation=relation,
        object=Entity(name=name, type=obj_type),
        evidence_quote=quote,
    )


def test_postprocess_drops_all_datasets_for_review_study_type():
    t = Triple(
        subject=Entity(name="paper", type="Method"),
        relation="USES_DATASET",
        object=Entity(name="camelyon16", type="Dataset"),
        confidence=0.9,
        evidence_quote="reviewed Camelyon16 studies",
    )
    out = postprocess_triples([t], "methods", study_type="review")
    assert out == []
    kept = postprocess_triples([t], "methods", study_type="ai_algorithm")
    assert len(kept) == 1
    assert kept[0].object.name == "camelyon16"


def test_postprocess_policy_off_still_legacy_drops_review_datasets(monkeypatch):
    """STUDY_POLICY_ENABLED=False: skip matrix, but keep legacy review/meta dataset drop."""
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", False)
    t = Triple(
        subject=Entity(name="paper", type="Method"),
        relation="USES_DATASET",
        object=Entity(name="camelyon16", type="Dataset"),
        confidence=0.9,
        evidence_quote="reviewed Camelyon16 studies",
    )
    assert postprocess_triples([t], "methods", study_type="review") == []
    assert postprocess_triples([t], "methods", study_type="meta_analysis") == []
    kept = postprocess_triples([t], "methods", study_type="ai_algorithm")
    assert len(kept) == 1
    # Matrix remap must not run when flag is off.
    applies = Triple(
        subject=Entity(name="paper", type="Method"),
        relation="APPLIES_METHOD",
        object=Entity(name="clam", type="Method"),
        confidence=0.9,
        evidence_quote="survey of clam",
    )
    out = postprocess_triples([applies], "methods", study_type="review")
    assert len(out) == 1
    assert out[0].relation == "APPLIES_METHOD"


def test_postprocess_review_remaps_applies_method(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    t = _triple("APPLIES_METHOD", "Method", "clam", quote="survey of clam")
    out = postprocess_triples([t], "methods", study_type="review")
    assert len(out) == 1
    assert out[0].relation == "SURVEYS_METHOD"


def test_postprocess_ai_keeps_uses_dataset(monkeypatch):
    monkeypatch.setattr("config.STUDY_POLICY_ENABLED", True)
    t = _triple("USES_DATASET", "Dataset", "camelyon16", quote="trained on")
    out = postprocess_triples([t], "methods", study_type="ai_algorithm")
    assert any(x.relation == "USES_DATASET" for x in out)


def test_repair_does_not_invent_compares_method():
    # Wrong relation + Method object → remapped to APPLIES_METHOD, not COMPARES_METHOD
    t = Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="PERFORMS_TASK",
        object=Entity(name="clam", type="Method"),
        evidence_quote="test",
    )
    fixed = repair_triple_relation(t)
    assert fixed is not None
    assert fixed.relation == "APPLIES_METHOD"


def _task_triple(name: str) -> Triple:
    return Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="PERFORMS_TASK",
        object=Entity(name=name, type="Task"),
        evidence_quote="test",
    )


def test_task_synonym_prognosis():
    assert normalize_entity_name("prognostic prediction", "Task") == "prognosis prediction"
    assert normalize_entity_name("prognosis prediction", "Task") == "prognosis prediction"


def test_task_synonym_pathology_classification():
    assert (
        normalize_entity_name("pathological classification", "Task")
        == "pathology classification"
    )


def test_generic_task_detected():
    assert is_generic_task("classification")
    assert is_generic_task("Segmentation")
    assert not is_generic_task("tumor subtype classification")


def test_narrative_task_detected():
    assert is_narrative_task("workshop report on digital pathology imaging")
    assert is_narrative_task("improving diversity in study cohorts")
    assert not is_narrative_task("survival prediction")


def test_postprocess_drops_reject_tasks():
    kept = postprocess_triples(
        [
            _task_triple("classification"),
            _task_triple("tumor subtype classification"),
            _task_triple("workshop report on digital pathology"),
        ],
        "methods",
    )
    names = {t.object.name for t in kept if t.object.type == "Task"}
    assert "classification" not in names
    assert "workshop report on digital pathology" not in names
    assert "tumor subtype classification" in names


def test_postprocess_applies_task_synonym():
    kept = postprocess_triples([_task_triple("prognostic prediction")], "methods")
    assert kept[0].object.name == "prognosis prediction"
