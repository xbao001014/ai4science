from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.method_family_supervised import (  # noqa: E402
    _fit_ridge,
    _apply_fixed_source_allowlist,
    _learn_lexicon,
    _match_lexicon,
    _metrics,
    _payload_training_labels,
    _score,
    _select_fixed_source_allowlist,
    _select_family_thresholds,
    _select_thresholds,
)


def test_balanced_ridge_separates_simple_embedding_classes():
    rows = [
        {"method_entity_id": 1, "label": "cnn"},
        {"method_entity_id": 2, "label": "cnn"},
        {"method_entity_id": 3, "label": "mil"},
        {"method_entity_id": 4, "label": "mil"},
    ]
    vectors = {
        1: np.array([1.0, 0.0]),
        2: np.array([0.9, 0.1]),
        3: np.array([0.0, 1.0]),
        4: np.array([0.1, 0.9]),
    }
    weights = _fit_ridge(rows, vectors, ["cnn", "mil"], 0.1)
    assert _score(np.array([1.0, 0.0]), weights, ["cnn", "mil"])["family_id"] == "cnn"
    assert _score(np.array([0.0, 1.0]), weights, ["cnn", "mil"])["family_id"] == "mil"


def test_threshold_selection_rejects_unknown_false_accepts():
    records = [
        {"label": "cnn", "predicted": "cnn", "paper_count": 2, "source": "model", "score": 0.9, "margin": 0.8},
        {"label": "mil", "predicted": "mil", "paper_count": 1, "source": "model", "score": 0.8, "margin": 0.7},
        {"label": "unknown", "predicted": "cnn", "paper_count": 1, "source": "model", "score": 0.4, "margin": 0.2},
    ]
    score_min, margin_min, metrics = _select_thresholds(records)
    assert score_min > 0.4 or margin_min > 0.2
    assert metrics["unknown_false_accepts"] == 0
    assert metrics["precision"] == 1.0


def test_metrics_counts_unknown_as_false_accept():
    metrics = _metrics(
        [
            {"label": "cnn", "predicted": "cnn", "paper_count": 3, "accepted": True},
            {"label": "unknown", "predicted": "cnn", "paper_count": 1, "accepted": True},
            {"label": "mil", "predicted": "cnn", "paper_count": 2, "accepted": False},
        ]
    )
    assert metrics["precision"] == 0.5
    assert metrics["unknown_false_accepts"] == 1


def test_lexicon_only_learns_exclusive_supported_phrases():
    rows = [
        {"method_name": f"resnet convolutional classifier {index}", "label": "cnn"}
        for index in range(5)
    ]
    rows.extend(
        {"method_name": f"cox survival regression {index}", "label": "classical_statistics"}
        for index in range(5)
    )
    rows.append({"method_name": "generic classifier", "label": "unknown"})
    lexicon = _learn_lexicon(rows, minimum_support=5)
    assert _match_lexicon("resnet convolutional classifier", lexicon) == "cnn"
    assert _match_lexicon("cox survival regression", lexicon) == "classical_statistics"
    assert _match_lexicon("generic classifier", lexicon) is None


def test_threshold_selection_enforces_paper_weighted_precision():
    records = [
        {"label": "cnn", "predicted": "cnn", "paper_count": 1, "source": "model", "score": 0.9, "margin": 0.8},
        {"label": "mil", "predicted": "mil", "paper_count": 1, "source": "model", "score": 0.8, "margin": 0.7},
        {"label": "mil", "predicted": "cnn", "paper_count": 100, "source": "model", "score": 0.7, "margin": 0.6},
    ]
    score_min, margin_min, metrics = _select_thresholds(records)
    assert score_min > 0.7 or margin_min > 0.6
    assert metrics["paper_weighted_precision"] == 1.0


def test_family_thresholds_do_not_block_safe_families():
    records = [
        {"label": "cnn", "predicted": "cnn", "paper_count": 1, "source": "model", "score": 0.8, "margin": 0.5},
        {"label": "cnn", "predicted": "cnn", "paper_count": 1, "source": "model", "score": 0.7, "margin": 0.4},
        {"label": "unknown", "predicted": "mil", "paper_count": 1, "source": "model", "score": 0.95, "margin": 0.9},
        {"label": "mil", "predicted": "mil", "paper_count": 1, "source": "model", "score": 0.6, "margin": 0.3},
    ]
    thresholds, metrics = _select_family_thresholds(records, ["cnn", "mil"])
    assert thresholds["cnn"]["score"] <= 0.7
    assert thresholds["mil"]["score"] > 0.95 or thresholds["mil"]["margin"] > 0.9
    assert metrics["accepted"] == 2
    assert metrics["unknown_false_accepts"] == 0


def test_fixed_source_revalidation_falls_back_when_precision_is_unsafe():
    records = [
        {
            "label": "transformer",
            "predicted": "transformer",
            "paper_count": 2,
            "source": "rule",
            "fixed_source_key": "strict_rule:transformer_named",
            "fallback_predicted": "transformer",
            "fallback_score": 0.8,
            "fallback_margin": 0.4,
        },
        {
            "label": "cnn",
            "predicted": "transformer",
            "paper_count": 1,
            "source": "rule",
            "fixed_source_key": "strict_rule:transformer_named",
            "fallback_predicted": "cnn",
            "fallback_score": 0.7,
            "fallback_margin": 0.3,
        },
    ]
    allowlist, report = _select_fixed_source_allowlist(records)
    assert allowlist == set()
    assert report["strict_rule:transformer_named"]["eligible"] is False
    calibrated = _apply_fixed_source_allowlist(records, allowlist)
    assert [row["predicted"] for row in calibrated] == ["transformer", "cnn"]
    assert all(row["source"] == "model" for row in calibrated)


def test_payload_training_labels_use_frozen_snapshot():
    model = {"parent_gold_set_id": "unused", "training_snapshot_sha256": "unused"}
    payload = {"training_labels": [[2, "mil"], [1, "cnn"]]}
    assert _payload_training_labels(model, payload) == {1: "cnn", 2: "mil"}


def test_family_thresholds_can_borrow_precision_from_safer_families():
    records = [
        {
            "label": "cnn",
            "predicted": "cnn",
            "paper_count": 1,
            "source": "model",
            "score": 0.8,
            "margin": 0.5,
        }
        for _ in range(20)
    ]
    records.extend(
        {
            "label": "transformer",
            "predicted": "transformer",
            "paper_count": 1,
            "source": "model",
            "score": 0.7,
            "margin": 0.4,
        }
        for _ in range(8)
    )
    records.append(
        {
            "label": "cnn",
            "predicted": "transformer",
            "paper_count": 1,
            "source": "model",
            "score": 0.9,
            "margin": 0.6,
        }
    )
    _, metrics = _select_family_thresholds(records, ["cnn", "transformer"])
    assert metrics["accepted"] == 29
    assert metrics["precision"] >= 0.95
    assert metrics["per_predicted_family"]["transformer"]["precision"] >= 0.85
