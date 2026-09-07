"""Tests for method synonym soft mapping."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.method_synonyms import (  # noqa: E402
    method_skeleton,
    near_duplicate_method_candidates,
    run_method_cluster_audit,
    resolve_method_canonical,
    resolve_method_entity_canonical,
)


def test_resolve_llm_alias():
    assert resolve_method_canonical("LLM") == "large language model"
    assert resolve_method_canonical("large language model") == "large language model"


def test_resolve_parenthetical_svm():
    assert resolve_method_canonical("support vector machine (svm)") == "support vector machine"


def test_parenthetical_only_collapses_matching_concepts():
    assert resolve_method_canonical("unet++ (resnet-50)") == "unet++ (resnet-50)"
    assert resolve_method_canonical("clam (resnet)") == "clam (resnet)"


def test_curated_synonym_maps(monkeypatch):
    import analysis.method_synonyms as ms

    monkeypatch.setitem(
        ms._METHOD_SYNONYMS,
        "drugreflector framework",
        "drugreflector",
    )
    assert resolve_method_canonical("DrugReflector Framework") == "drugreflector"


def test_auto_does_not_absorb_long_phrase_into_deep_learning():
    name = "data fusion deep learning framework"
    assert resolve_method_canonical(name) == "data fusion deep learning framework"


def test_persistent_mapping_preserves_versions_and_modifiers():
    assert resolve_method_entity_canonical("SVM") == "support vector machine"
    assert resolve_method_entity_canonical("nnu-net") == "nnunet"
    assert resolve_method_entity_canonical("nnUNet v2") == "nnunet v2"
    assert resolve_method_entity_canonical("modified ResNet-34") == "modified resnet-34"
    assert resolve_method_entity_canonical("ChatGPT-4o") == "chatgpt-4o"


def test_skeleton_strips_weak_tokens():
    sk = method_skeleton("resnet-based segmentation framework model")
    assert "framework" not in sk.split()
    assert "model" not in sk.split()


def test_near_duplicate_candidates_suggest_but_do_not_resolve():
    names = [
        "drugreflector",
        "drugreflector framework",
        "totally unrelated method xyz",
    ]
    cands = near_duplicate_method_candidates(names, min_shared_tokens=1)
    pairs = {(c["alias"], c["suggested_canonical"]) for c in cands} | {
        (c["suggested_canonical"], c["alias"]) for c in cands
    }
    assert any("drugreflector" in a and "drugreflector" in b for a, b in pairs)
    # unresolved until curated
    assert resolve_method_canonical("drugreflector framework") == "drugreflector framework"


def test_near_duplicate_candidates_prefer_frequent_canonical_and_skip_established():
    candidates = near_duplicate_method_candidates(
        [
            "alpha beta",
            "alpha beta framework",
            "resnet",
            "resnet framework",
        ],
        min_shared_tokens=1,
        paper_counts={"alpha beta": 2, "alpha beta framework": 9},
    )

    assert {
        (row["alias"], row["suggested_canonical"]) for row in candidates
    } == {("alpha beta", "alpha beta framework")}


def test_run_method_cluster_audit_formats_ranked_candidates(monkeypatch):
    import analysis.method_synonyms as ms

    monkeypatch.setattr(
        ms,
        "_fetch_method_rows",
        lambda: [
            {"name": "drugreflector", "paper_cnt": 3},
            {"name": "drugreflector framework", "paper_cnt": 2},
        ],
    )

    report = run_method_cluster_audit(limit=10)

    assert "# Method Cluster Audit" in report
    assert "| Alias | Suggested canonical | Papers | Score | Reason |" in report
    assert "| drugreflector framework | drugreflector | 2 | 1.0 | skeleton |" in report
    assert "curate into `_METHOD_SYNONYMS` manually" in report
