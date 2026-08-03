"""Tests for idea session feasibility baseline + tool cache guards."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.idea_session_guards import (  # noqa: E402
    IdeaSessionGuards,
    ToolResultCache,
    cache_key,
    canonicalize_feasibility_args,
    compare_feasibility_specs,
    wrap_tools_with_cache,
)


def test_canonicalize_sorts_dedupes_lists_and_defaults_followup():
    out = canonicalize_feasibility_args(
        disease_id=" C_CA ",
        task_type="survival_prediction",
        required_labels=["vital_status", "OS", "vital_status"],
        required_molecular_markers=None,
        required_annotations=[" tumor_region "],
        min_followup_months=None,
        hypothesis_id="should-be-dropped",
    )
    assert out["disease_id"] == "c_ca"
    assert out["task_type"] == "survival_prediction"
    assert out["required_labels"] == ["overall_survival_months", "vital_status"]
    assert out["required_molecular_markers"] == []
    assert out["required_annotations"] == ["tumor_region"]
    assert out["min_followup_months"] == 0
    assert "hypothesis_id" not in out


def test_compare_alias_equivalent_labels_and_annotations_are_same():
    baseline = canonicalize_feasibility_args(
        disease_id="C_CA",
        required_labels=["overall_survival_months"],
        required_annotations=["tumor_region"],
    )
    aliases = canonicalize_feasibility_args(
        disease_id="c_ca",
        required_labels=["os"],
        required_annotations=["stroma_region"],
    )
    assert compare_feasibility_specs(baseline, aliases) == "same"


def test_compare_same_case_insensitive_lists():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    other = canonicalize_feasibility_args(
        disease_id="c_ca",
        task_type="Survival_Prediction",
        required_labels=["VITAL_STATUS"],
        required_annotations=["TUMOR_REGION"],
        min_followup_months=24,
    )
    assert compare_feasibility_specs(base, other) == "same"


def test_compare_tighter_superset_and_higher_followup():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    tighter = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status", "overall_survival_months"],
        required_annotations=["tumor_region", "immune_region"],
        min_followup_months=36,
    )
    assert compare_feasibility_specs(base, tighter) == "tighter"


def test_compare_relaxed_when_annotations_cleared():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status", "overall_survival_months"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    relaxed = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status", "overall_survival_months"],
        required_annotations=[],
        min_followup_months=24,
    )
    assert compare_feasibility_specs(base, relaxed) == "relaxed"


def test_compare_mixed_tighter_and_looser_is_relaxed():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["a", "b"],
        required_annotations=["x"],
        min_followup_months=24,
    )
    mixed = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["a", "b", "c"],  # tighter
        required_annotations=[],  # looser
        min_followup_months=24,
    )
    assert compare_feasibility_specs(base, mixed) == "relaxed"


def test_compare_disease_id_change_is_relaxed():
    base = canonicalize_feasibility_args(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        min_followup_months=24,
    )
    other = canonicalize_feasibility_args(
        disease_id="BRCA-IDC",
        task_type="survival_prediction",
        required_labels=["vital_status", "extra"],
        min_followup_months=36,
    )
    assert compare_feasibility_specs(base, other) == "relaxed"


def test_tool_cache_hit_skips_second_invoke():
    calls = {"n": 0}

    def fake_metrics(keyword: str = ""):
        calls["n"] += 1
        return {"description": "ok", "data": [{"metric": "auc"}]}

    cache = ToolResultCache()
    wrapped = wrap_tools_with_cache({"metrics_for_topic": fake_metrics}, cache)
    a = wrapped["metrics_for_topic"](keyword="crc histology")
    b = wrapped["metrics_for_topic"](keyword="crc histology")
    assert a == b
    assert calls["n"] == 1
    assert cache.hits == 1
    assert cache.misses == 1


def test_cache_key_stable_for_equivalent_args():
    a = cache_key("metrics_for_topic", {"keyword": "crc", "limit": 10})
    b = cache_key("metrics_for_topic", {"limit": 10, "keyword": " crc "})
    assert a == b
    assert cache_key("other", {"keyword": "crc", "limit": 10}) != a


def test_tool_cache_put_skips_none():
    calls = {"n": 0}

    def returns_none(**_kwargs):
        calls["n"] += 1
        return None

    cache = ToolResultCache()
    wrapped = wrap_tools_with_cache({"x": returns_none}, cache)
    assert wrapped["x"]() is None
    assert wrapped["x"]() is None
    assert calls["n"] == 2
    assert cache.hits == 0
    assert cache.misses == 2


def test_tool_cache_put_skips_falsy_non_dict():
    cache = ToolResultCache()
    cache.put("x", {}, None)
    cache.put("x", {}, False)
    cache.put("x", {}, 0)
    cache.put("x", {}, "")
    assert cache.get("x", {}) is None
    assert cache.misses == 1


def test_tool_cache_stores_truthy_non_dict():
    cache = ToolResultCache()
    cache.put("x", {"k": "v"}, "ok")
    assert cache.get("x", {"k": "v"}) == "ok"
    assert cache.hits == 1


def test_tool_cache_does_not_store_errors():
    calls = {"n": 0}

    def flaky(**_kwargs):
        calls["n"] += 1
        return {"error": "boom"}

    cache = ToolResultCache()
    wrapped = wrap_tools_with_cache({"x": flaky}, cache)
    assert wrapped["x"]()["error"] == "boom"
    assert wrapped["x"]()["error"] == "boom"
    assert calls["n"] == 2
    assert cache.hits == 0


def test_feasibility_sets_baseline_on_first_success():
    calls = {"n": 0}

    def fake_v01(**kwargs):
        calls["n"] += 1
        return {"feasibility_score": 0.4, "available_cohort_size": 10}

    session = IdeaSessionGuards()
    tools = session.wrap_tools({"feasibility_assess": fake_v01})
    out = tools["feasibility_assess"](
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    assert out["feasibility_score"] == 0.4
    assert session.baseline is not None
    assert session.baseline["required_annotations"] == ["tumor_region"]
    assert calls["n"] == 1


def test_feasibility_blocks_relaxed_without_calling():
    calls = {"n": 0}

    def fake_v01(**kwargs):
        calls["n"] += 1
        return {"feasibility_score": 0.4}

    session = IdeaSessionGuards()
    tools = session.wrap_tools({"feasibility_assess": fake_v01})
    tools["feasibility_assess"](
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    blocked = tools["feasibility_assess"](
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=[],
        min_followup_months=24,
    )
    assert blocked["error"] == "feasibility_spec_relaxed"
    assert "required_annotations" in blocked["relaxed_fields"]
    assert calls["n"] == 1
    assert session.relaxed_seen is True


def test_feasibility_same_args_uses_cache():
    calls = {"n": 0}

    def fake_v01(**kwargs):
        calls["n"] += 1
        return {"feasibility_score": 0.55}

    session = IdeaSessionGuards()
    tools = session.wrap_tools({"feasibility_assess": fake_v01})
    args = dict(
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    tools["feasibility_assess"](**args)
    tools["feasibility_assess"](**args)
    assert calls["n"] == 1
    assert session.last_spec_relation == "same"


def test_feasibility_alias_case_order_and_hypothesis_id_share_cache_entry():
    calls = {"n": 0}

    def fake_v01(**kwargs):
        calls["n"] += 1
        return {"feasibility_score": 0.55}

    session = IdeaSessionGuards()
    tool = session.wrap_tools({"feasibility_assess": fake_v01})["feasibility_assess"]
    tool(
        disease_id="C_CA",
        task_type="Survival_Prediction",
        required_labels=["vital_status", "overall_survival_months"],
        required_annotations=["tumor_region"],
        hypothesis_id="first",
    )
    tool(
        disease_id="c_ca",
        task_type="survival_prediction",
        required_labels=["OS", "VITAL_STATUS"],
        required_annotations=["STROMA_REGION"],
        hypothesis_id="second",
    )
    assert calls["n"] == 1
    assert session.cache.hits == 1


def test_feasibility_tighter_allowed_baseline_unchanged():
    calls = {"n": 0}

    def fake_v01(**kwargs):
        calls["n"] += 1
        return {"feasibility_score": 0.2}

    session = IdeaSessionGuards()
    tools = session.wrap_tools({"feasibility_assess": fake_v01})
    tools["feasibility_assess"](
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    tools["feasibility_assess"](
        disease_id="C_CA",
        task_type="survival_prediction",
        required_labels=["vital_status", "overall_survival_months"],
        required_annotations=["tumor_region"],
        min_followup_months=24,
    )
    assert calls["n"] == 2
    assert session.last_spec_relation == "tighter"
    assert session.baseline["required_labels"] == ["vital_status"]


def test_feasibility_baseline_does_not_slide_after_tighter_call():
    calls = {"n": 0}

    def fake_v01(**kwargs):
        calls["n"] += 1
        return {"feasibility_score": 0.4}

    session = IdeaSessionGuards()
    tool = session.wrap_tools({"feasibility_assess": fake_v01})["feasibility_assess"]
    tool(
        disease_id="C_CA",
        required_labels=["vital_status", "overall_survival_months"],
    )
    tool(
        disease_id="C_CA",
        required_labels=["vital_status", "overall_survival_months", "recurrence_status"],
    )
    blocked = tool(
        disease_id="C_CA",
        required_labels=["vital_status", "recurrence_status"],
    )
    assert blocked["error"] == "feasibility_spec_relaxed"
    assert session.baseline["required_labels"] == [
        "overall_survival_months",
        "vital_status",
    ]
    assert calls["n"] == 2
