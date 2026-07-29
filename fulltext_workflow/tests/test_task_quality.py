"""Tests for Task quality tiers."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.task_quality import audit_task_names, classify_task_quality  # noqa: E402


def test_reject_generic_and_narrative():
    assert classify_task_quality("classification") == "reject"
    assert classify_task_quality("workshop report on digital pathology") == "reject"


def test_weak_single_token_non_generic():
    # single token not in generic blacklist → weak (too coarse to bridge)
    assert classify_task_quality("quantification") == "weak"


def test_ok_specific_phrase():
    assert classify_task_quality("tumor subtype classification") == "ok"
    assert classify_task_quality("survival prediction") == "ok"
    assert classify_task_quality("prognosis prediction") == "ok"


def test_audit_counts():
    out = audit_task_names(
        [
            "classification",
            "tumor subtype classification",
            "quantification",
            "prognostic prediction",  # normalizes then ok
        ]
    )
    assert out["counts"]["reject"] >= 1
    assert out["counts"]["ok"] >= 2
    assert out["counts"]["weak"] >= 1
