"""Unit tests for method maturity classification."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.method_maturity import (  # noqa: E402
    classify_method_maturity,
    context_novelty_bonus,
    is_established_blacklist,
    maturity_penalty,
    nascent_bonus,
)


def test_blacklist_llm_and_svm():
    assert is_established_blacklist("large language model")
    assert is_established_blacklist("Large Language Models")
    assert is_established_blacklist("llm")
    assert is_established_blacklist("support vector machine")
    assert is_established_blacklist("svm")
    assert is_established_blacklist("deep learning")  # via generic umbrellas


def test_blacklist_no_naive_substring():
    assert not is_established_blacklist("cram-enhanced lightweight dual-branch cnn")
    assert not is_established_blacklist("pathology-specific vision transformer")


def test_classify_tiers_by_count():
    assert classify_method_maturity("niche-tool-x", 1, established_min=10) == "nascent"
    assert classify_method_maturity("niche-tool-x", 5, established_min=10) == "emerging"
    assert classify_method_maturity("niche-tool-x", 12, established_min=10) == "established"


def test_blacklist_beats_low_count():
    assert classify_method_maturity("large language model", 2, established_min=10) == "established"


def test_score_helpers():
    assert context_novelty_bonus(0) == 1.5
    assert context_novelty_bonus(2) == 0.5
    assert context_novelty_bonus(0, first_in_recent_window=True) == 2.0
    assert maturity_penalty("established") == 2.0
    assert maturity_penalty("nascent") == 0.0
    assert nascent_bonus("nascent") == 0.5
    assert nascent_bonus("emerging") == 0.0
