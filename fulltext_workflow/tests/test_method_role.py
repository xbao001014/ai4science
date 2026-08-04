"""Unit tests for method role classification (backbone vs aggregator)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.method_role import (  # noqa: E402
    annotate_method_role,
    classify_method_role,
    resolve_method_role,
)


def test_backbone_aliases():
    assert classify_method_role("resnet-50") == "backbone"
    assert classify_method_role("ResNet50") == "backbone"
    assert classify_method_role("uni") == "backbone"
    assert classify_method_role("conch") == "backbone"
    assert classify_method_role("ctranspath") == "backbone"
    assert classify_method_role("vit") == "backbone"


def test_backbone_digit_glued_family_variants():
    assert classify_method_role("densenet121") == "backbone"
    assert classify_method_role("densenet201") == "backbone"
    assert classify_method_role("efficientnetb0") == "backbone"
    assert classify_method_role("vgg16") == "backbone"
    assert classify_method_role("mobilenetv2") == "backbone"


def test_aggregator_heuristics():
    assert classify_method_role("dual-attention mil") == "aggregator"
    assert classify_method_role("cross-attention fusion module") == "aggregator"
    assert classify_method_role("attention pooling mil head") == "aggregator"
    assert classify_method_role("bag-level aggregator") == "aggregator"
    assert classify_method_role("attention-based multiple instance learning") == "aggregator"
    assert classify_method_role("multiple instance learning") == "aggregator"


def test_aggregator_framework_aliases():
    assert classify_method_role("abmil") == "aggregator"
    assert classify_method_role("transmil") == "aggregator"
    assert classify_method_role("clam") == "aggregator"


def test_bare_attention_not_forced_aggregator():
    # Must NOT use bare "attention" as aggregator cue.
    # With alias `attention u-net` → backbone; without alias must still != aggregator.
    assert classify_method_role("attention u-net") == "backbone"


def test_unknown_frameworkish_names():
    assert classify_method_role("qupath") == "tool"


def test_classical_ml_aliases():
    assert classify_method_role("random forest") == "classical_ml"
    assert classify_method_role("support vector machine") == "classical_ml"
    assert classify_method_role("xgboost") == "classical_ml"
    assert classify_method_role("lightgbm") == "classical_ml"
    assert classify_method_role("logistic regression") == "classical_ml"
    assert classify_method_role("cox proportional hazards regression") == "classical_ml"


def test_tool_aliases():
    assert classify_method_role("qupath") == "tool"
    assert classify_method_role("seurat") == "tool"
    assert classify_method_role("gsva") == "tool"
    assert classify_method_role("vosviewer") == "tool"


def test_backbone_missings():
    assert classify_method_role("hover-net") == "backbone"
    assert classify_method_role("segformer") == "backbone"
    assert classify_method_role("dinov2") == "backbone"
    assert classify_method_role("cnn") == "backbone"
    assert classify_method_role("convolutional neural network") == "backbone"
    assert classify_method_role("xception") == "backbone"
    assert classify_method_role("prov-gigapath") == "backbone"


def test_resolve_rule_beats_hint():
    assert resolve_method_role("resnet-50", "tool") == "backbone"
    assert resolve_method_role("clam", "backbone") == "aggregator"


def test_resolve_hint_fills_unknown():
    assert resolve_method_role("totally-novel-widget-xyz", "classical_ml") == "classical_ml"
    assert resolve_method_role("totally-novel-widget-xyz", "nope") == "unknown"
    assert resolve_method_role("totally-novel-widget-xyz", None) == "unknown"


def test_annotate_prefers_role_by_name():
    rows = [{"name": "weird-method"}]
    annotate_method_role(rows, role_by_name={"weird-method": "tool"})
    assert rows[0]["method_role"] == "tool"


def test_aggregator_alias_beats_backbone_alias(monkeypatch):
    import analysis.method_role as mr

    monkeypatch.setattr(
        mr,
        "_BACKBONE_ALIASES",
        frozenset(set(mr._BACKBONE_ALIASES) | {"conflict-tool"}),
    )
    monkeypatch.setattr(
        mr,
        "_AGGREGATOR_ALIASES",
        frozenset(set(mr._AGGREGATOR_ALIASES) | {"conflict-tool"}),
    )
    assert classify_method_role("conflict-tool") == "aggregator"


def test_annotate_method_role_writes_field():
    rows = [{"name": "resnet-50"}, {"name": "dual-stream mil"}]
    out = annotate_method_role(rows)
    assert out is rows
    assert rows[0]["method_role"] == "backbone"
    assert rows[1]["method_role"] == "aggregator"


def test_classify_uses_canonical_before_role(monkeypatch):
    import analysis.method_role as mr

    monkeypatch.setattr(
        mr,
        "resolve_method_canonical",
        lambda name: "resnet-50" if name == "alias-rn50" else name,
    )
    assert classify_method_role("alias-rn50") == "backbone"
