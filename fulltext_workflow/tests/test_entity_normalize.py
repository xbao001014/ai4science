"""Tests for Method/Limitation post-processing."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor.entity_normalize import (  # noqa: E402
    has_more_specific_disease,
    is_generic_disease,
    is_generic_method,
    is_low_value_method,
    is_organ_level_disease,
    is_radiology_modality,
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
    assert out[0].object.name == "breast cancer"


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
