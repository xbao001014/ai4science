"""Tests for Method/Limitation post-processing."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor.entity_normalize import (  # noqa: E402
    is_generic_method,
    normalize_entity_name,
    postprocess_triples,
)
from extractor.triple_models import Entity, Triple  # noqa: E402


def _method_triple(name: str, section: str = "methods") -> Triple:
    return Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="APPLIES_METHOD",
        object=Entity(name=name, type="Method"),
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
