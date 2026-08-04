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
)


def test_backbone_aliases():
    assert classify_method_role("resnet-50") == "backbone"
    assert classify_method_role("ResNet50") == "backbone"
    assert classify_method_role("uni") == "backbone"
    assert classify_method_role("conch") == "backbone"
    assert classify_method_role("ctranspath") == "backbone"
    assert classify_method_role("vit") == "backbone"


def test_aggregator_heuristics():
    assert classify_method_role("dual-attention mil") == "aggregator"
    assert classify_method_role("cross-attention fusion module") == "aggregator"
    assert classify_method_role("attention pooling mil head") == "aggregator"
    assert classify_method_role("bag-level aggregator") == "aggregator"


def test_bare_attention_not_forced_aggregator():
    # Must NOT use bare "attention" as aggregator cue.
    # With alias `attention u-net` → backbone; without alias must still != aggregator.
    assert classify_method_role("attention u-net") == "backbone"


def test_unknown_frameworkish_names():
    assert classify_method_role("clam") == "unknown"
    assert classify_method_role("transmil") == "unknown"
    assert classify_method_role("qupath") == "unknown"


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
