# Idea Feasibility Baseline + Session Tool Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze Critic’s first successful V-01 args as an immutable session baseline (block relaxed re-specs; allow same/tighter) and cache identical IDEA tool calls within one `stream_idea_agent` run.

**Architecture:** Add `analysis/idea_session_guards.py` with pure compare helpers, `ToolResultCache`, and wrappers. `idea_agent.stream_idea_agent` builds one shared session, wraps Generator/Critic tools after `bind_idea_tools`, forces `accept=False` if `feasibility_spec_relaxed` appears in a Critic round, and extends prompts briefly.

**Tech Stack:** Python 3, pytest, existing `idea_agent` / `run_tool_agent` / `tool_feasibility_assess`.

**Spec:** `docs/superpowers/specs/2026-08-03-idea-feasibility-baseline-cache-design.md`

## Global Constraints

- Idea-path only — do not change `gap_agent` or Fangxin client math.
- Baseline source = first successful `feasibility_assess` **call args**; never update baseline on tighter calls.
- `hypothesis_id` is ignored for compare / baseline fields.
- Cache is per `stream_idea_agent` invocation only; do not persist.
- Never cache results that contain an `error` key.
- Prefer not mutating Fangxin success bodies; track `cache_hits` on the session object.
- TDD: failing test → implement → pass → commit per task.
- Commits only when the user/agent explicitly runs the commit step in this plan.

---

## File structure

| File | Responsibility |
|---|---|
| `fulltext_workflow/analysis/idea_session_guards.py` | Normalize/compare V-01 specs; `IdeaSessionGuards` (baseline + cache); wrap tools |
| `fulltext_workflow/idea_agent.py` | Wire guards into `stream_idea_agent`; prompt lines; accept gate |
| `fulltext_workflow/tests/test_idea_session_guards.py` | Unit tests for normalize, relation, cache, feasibility wrapper |
| `fulltext_workflow/tests/test_idea_agent_baseline_accept.py` | Stream-level: relaxed error ⇒ `accept=False` |

---

### Task 1: Spec normalize + relation classifier

**Files:**
- Create: `fulltext_workflow/analysis/idea_session_guards.py`
- Test: `fulltext_workflow/tests/test_idea_session_guards.py`

**Interfaces:**
- Produces:
  - `normalize_feasibility_spec(args: dict) -> dict` with keys `disease_id`, `task_type`, `required_labels`, `required_molecular_markers`, `required_annotations`, `min_followup_months` (lists as sorted unique casefolded strings; ids/types stripped casefolded strings for compare — also keep `*_display` originals optional; simplest: store both `normalized` compare view and preserve originals separately in baseline snapshot)
  - Prefer simpler API used below:
    - `canonicalize_feasibility_args(**kwargs) -> dict` — display snapshot (lists sorted unique stripped; preserve original casing of first-seen tokens; `min_followup_months` int default 0; drop `hypothesis_id`)
    - `compare_feasibility_specs(baseline: dict, attempted: dict) -> str` — returns `"same" | "tighter" | "relaxed"`
  - List compare uses casefold equality; relation rules per spec.

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_idea_session_guards.py`:

```python
"""Tests for idea session feasibility baseline + tool cache guards."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.idea_session_guards import (  # noqa: E402
    canonicalize_feasibility_args,
    compare_feasibility_specs,
)


def test_canonicalize_sorts_dedupes_lists_and_defaults_followup():
    out = canonicalize_feasibility_args(
        disease_id=" C_CA ",
        task_type="survival_prediction",
        required_labels=["vital_status", "Overall_Survival_Months", "vital_status"],
        required_molecular_markers=None,
        required_annotations=[" tumor_region "],
        min_followup_months=None,
        hypothesis_id="should-be-dropped",
    )
    assert out["disease_id"] == "C_CA"
    assert out["task_type"] == "survival_prediction"
    assert out["required_labels"] == ["Overall_Survival_Months", "vital_status"]
    assert out["required_molecular_markers"] == []
    assert out["required_annotations"] == ["tumor_region"]
    assert out["min_followup_months"] == 0
    assert "hypothesis_id" not in out


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
        required_annotations=["tumor_region", "stroma_region"],
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe -m pytest tests/test_idea_session_guards.py -v
```

Expected: FAIL (import error / module missing).

- [ ] **Step 3: Implement canonicalize + compare**

Create `fulltext_workflow/analysis/idea_session_guards.py`:

```python
"""Session guards for idea_agent: V-01 baseline freeze + tool result cache."""
from __future__ import annotations

import json
from typing import Any, Callable

_SPEC_KEYS = (
    "disease_id",
    "task_type",
    "required_labels",
    "required_molecular_markers",
    "required_annotations",
    "min_followup_months",
)
_LIST_KEYS = (
    "required_labels",
    "required_molecular_markers",
    "required_annotations",
)


def _norm_token(value: Any) -> str:
    return str(value).strip()


def _fold(value: str) -> str:
    return value.casefold()


def _canon_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    best: dict[str, str] = {}
    for raw in values:
        tok = _norm_token(raw)
        if not tok:
            continue
        key = _fold(tok)
        best.setdefault(key, tok)
    return [best[k] for k in sorted(best)]


def canonicalize_feasibility_args(**kwargs: Any) -> dict[str, Any]:
    labels = kwargs.get("required_labels")
    markers = kwargs.get("required_molecular_markers")
    anns = kwargs.get("required_annotations")
    follow = kwargs.get("min_followup_months")
    try:
        follow_i = int(follow) if follow is not None and str(follow).strip() != "" else 0
    except (TypeError, ValueError):
        follow_i = 0
    return {
        "disease_id": _norm_token(kwargs.get("disease_id") or ""),
        "task_type": _norm_token(kwargs.get("task_type") or "survival_prediction"),
        "required_labels": _canon_list(labels if isinstance(labels, list) else None),
        "required_molecular_markers": _canon_list(
            markers if isinstance(markers, list) else None
        ),
        "required_annotations": _canon_list(anns if isinstance(anns, list) else None),
        "min_followup_months": follow_i,
    }


def _list_set(spec: dict[str, Any], key: str) -> set[str]:
    return {_fold(x) for x in spec.get(key) or []}


def compare_feasibility_specs(baseline: dict, attempted: dict) -> str:
    b = canonicalize_feasibility_args(**baseline)
    a = canonicalize_feasibility_args(**attempted)
    if _fold(b["disease_id"]) != _fold(a["disease_id"]):
        return "relaxed"
    if _fold(b["task_type"]) != _fold(a["task_type"]):
        return "relaxed"
    if int(a["min_followup_months"]) < int(b["min_followup_months"]):
        return "relaxed"

    any_strict = int(a["min_followup_months"]) > int(b["min_followup_months"])
    for key in _LIST_KEYS:
        bs, as_ = _list_set(b, key), _list_set(a, key)
        if not bs.issubset(as_):
            return "relaxed"
        if as_ != bs:
            any_strict = True

    if (
        _fold(b["disease_id"]) == _fold(a["disease_id"])
        and _fold(b["task_type"]) == _fold(a["task_type"])
        and int(a["min_followup_months"]) == int(b["min_followup_months"])
        and all(_list_set(b, k) == _list_set(a, k) for k in _LIST_KEYS)
    ):
        return "same"
    return "tighter" if any_strict else "same"


def relaxed_fields(baseline: dict, attempted: dict) -> list[str]:
    b = canonicalize_feasibility_args(**baseline)
    a = canonicalize_feasibility_args(**attempted)
    fields: list[str] = []
    if _fold(b["disease_id"]) != _fold(a["disease_id"]):
        fields.append("disease_id")
    if _fold(b["task_type"]) != _fold(a["task_type"]):
        fields.append("task_type")
    if int(a["min_followup_months"]) < int(b["min_followup_months"]):
        fields.append("min_followup_months")
    for key in _LIST_KEYS:
        if not _list_set(b, key).issubset(_list_set(a, key)):
            fields.append(key)
    return fields
```

(Keep file open for Task 2–3 additions in the same module.)

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe -m pytest tests/test_idea_session_guards.py -v
```

Expected: PASS (all Task 1 tests).

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/analysis/idea_session_guards.py fulltext_workflow/tests/test_idea_session_guards.py
git commit -m "$(cat <<'EOF'
feat: add feasibility spec canonicalize and compare helpers

EOF
)"
```

---

### Task 2: ToolResultCache + wrap_tools_with_cache

**Files:**
- Modify: `fulltext_workflow/analysis/idea_session_guards.py`
- Test: `fulltext_workflow/tests/test_idea_session_guards.py`

**Interfaces:**
- Consumes: none beyond Task 1
- Produces:
  - `class ToolResultCache` with `get(name, args_dict) -> Any | None`, `put(name, args_dict, result)`, `hits: int`, `misses: int`
  - `def cache_key(name: str, args: dict) -> str`
  - `def wrap_tools_with_cache(tools: dict[str, Callable], cache: ToolResultCache) -> dict[str, Callable]`
  - Cache stores only results that are dicts **without** `"error"` key, or non-dict truthy results; never store dicts with `"error"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_idea_session_guards.py`:

```python
from analysis.idea_session_guards import ToolResultCache, wrap_tools_with_cache


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
```

- [ ] **Step 2: Run new tests — expect FAIL**

Run:

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe -m pytest tests/test_idea_session_guards.py::test_tool_cache_hit_skips_second_invoke tests/test_idea_session_guards.py::test_tool_cache_does_not_store_errors -v
```

Expected: FAIL (classes/functions missing).

- [ ] **Step 3: Implement cache**

Append to `idea_session_guards.py`:

```python
def _canonical_args_json(args: dict[str, Any]) -> str:
    def _norm(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {str(k): _norm(obj[k]) for k in sorted(obj)}
        if isinstance(obj, (list, tuple)):
            return [_norm(x) for x in obj]
        if obj is None:
            return None
        if isinstance(obj, str):
            return obj.strip()
        return obj

    return json.dumps(_norm(args), ensure_ascii=False, sort_keys=True, default=str)


class ToolResultCache:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0

    def _key(self, name: str, args: dict[str, Any]) -> str:
        return f"{name}::{_canonical_args_json(args)}"

    def get(self, name: str, args: dict[str, Any]) -> Any | None:
        key = self._key(name, args)
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def put(self, name: str, args: dict[str, Any], result: Any) -> None:
        if isinstance(result, dict) and "error" in result:
            return
        self._store[self._key(name, args)] = result


def wrap_tools_with_cache(
    tools: dict[str, Callable[..., Any]],
    cache: ToolResultCache,
) -> dict[str, Callable[..., Any]]:
    import inspect

    wrapped: dict[str, Callable[..., Any]] = {}
    for name, fn in tools.items():

        def _make(tool_name: str, f: Callable[..., Any]):
            def _wrapped(**kwargs: Any) -> Any:
                hit = cache.get(tool_name, kwargs)
                if hit is not None:
                    return hit
                # get() already counted a miss; call underlying
                result = f(**kwargs)
                cache.put(tool_name, kwargs, result)
                return result

            try:
                _wrapped.__signature__ = inspect.signature(f)  # type: ignore[attr-defined]
            except (TypeError, ValueError):
                pass
            _wrapped.__name__ = getattr(f, "__name__", tool_name)
            return _wrapped

        wrapped[name] = _make(name, fn)
    return wrapped
```

**Bugfix for miss double-count:** `get` increments miss when absent; callers of `get` then `put` is fine for wrap. Do **not** call `get` then manually increment again.

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe -m pytest tests/test_idea_session_guards.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/analysis/idea_session_guards.py fulltext_workflow/tests/test_idea_session_guards.py
git commit -m "$(cat <<'EOF'
feat: add session tool result cache for idea agent

EOF
)"
```

---

### Task 3: Feasibility baseline wrapper

**Files:**
- Modify: `fulltext_workflow/analysis/idea_session_guards.py`
- Test: `fulltext_workflow/tests/test_idea_session_guards.py`

**Interfaces:**
- Produces:
  - `class IdeaSessionGuards` with:
    - `cache: ToolResultCache`
    - `baseline: dict | None`
    - `relaxed_seen: bool` (sticky for the whole session; Critic round gate can also track per-round — use sticky session flag `relaxed_seen` and reset is NOT required because any relaxed attempt should block accept for that round; set True when relaxed error returned)
    - `last_spec_relation: str | None`
    - `wrap_tools(tools: dict) -> dict` — applies cache to all tools; if `feasibility_assess` present, replace with baseline-aware wrapper **inside** or **instead of** plain cache wrap for that name
  - Feasibility wrapper logic:
    1. Canonicalize attempted args (ignore hypothesis_id for baseline storage).
    2. If `baseline is None`: call underlying (via cache key); on success (`dict` without `error` and parsable `feasibility_score`), set `baseline = canonicalize_feasibility_args(**kwargs)`.
    3. Else compare: `relaxed` → return error dict, set `relaxed_seen=True`, `last_spec_relation="relaxed"`, do not call underlying.
    4. `same` / `tighter` → call through cache; set `last_spec_relation`; never update baseline.

- [ ] **Step 1: Write the failing tests**

```python
from analysis.idea_session_guards import IdeaSessionGuards


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
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe -m pytest tests/test_idea_session_guards.py -k feasibility -v
```

Expected: FAIL (`IdeaSessionGuards` missing).

- [ ] **Step 3: Implement `IdeaSessionGuards`**

Append to `idea_session_guards.py`:

```python
def _is_successful_feasibility(result: Any) -> bool:
    if not isinstance(result, dict) or "error" in result:
        return False
    raw = result.get("feasibility_score")
    if raw is None or str(raw).strip() == "":
        return False
    try:
        float(raw)
    except (TypeError, ValueError):
        return False
    return True


class IdeaSessionGuards:
    def __init__(self) -> None:
        self.cache = ToolResultCache()
        self.baseline: dict[str, Any] | None = None
        self.relaxed_seen = False
        self.last_spec_relation: str | None = None

    def wrap_tools(
        self, tools: dict[str, Callable[..., Any]]
    ) -> dict[str, Callable[..., Any]]:
        import inspect

        # Cache-wrap everything first, then replace feasibility with guarded wrapper
        # that still uses self.cache for same/tighter calls.
        cached = wrap_tools_with_cache(tools, self.cache)
        if "feasibility_assess" not in tools:
            return cached

        underlying = tools["feasibility_assess"]

        def feasibility_assess(**kwargs: Any) -> Any:
            attempted = canonicalize_feasibility_args(**kwargs)
            if self.baseline is None:
                result = self.cache.get("feasibility_assess", kwargs)
                if result is None:
                    # cache.get already counted miss
                    result = underlying(**kwargs)
                    self.cache.put("feasibility_assess", kwargs, result)
                else:
                    # hit path: get already counted hit — but we called get after a
                    # logical miss path above only when None. OK.
                    pass
                # Fix double-wrap issue: do NOT use cached["feasibility_assess"] here.
                if self.baseline is None and _is_successful_feasibility(result):
                    self.baseline = attempted
                self.last_spec_relation = None if self.baseline is None else "same"
                return result

            relation = compare_feasibility_specs(self.baseline, attempted)
            self.last_spec_relation = relation
            if relation == "relaxed":
                self.relaxed_seen = True
                return {
                    "error": "feasibility_spec_relaxed",
                    "baseline": dict(self.baseline),
                    "attempted": attempted,
                    "relaxed_fields": relaxed_fields(self.baseline, attempted),
                }

            result = self.cache.get("feasibility_assess", kwargs)
            if result is None:
                result = underlying(**kwargs)
                self.cache.put("feasibility_assess", kwargs, result)
            return result

        try:
            feasibility_assess.__signature__ = inspect.signature(underlying)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            pass

        out = dict(cached)
        out["feasibility_assess"] = feasibility_assess
        return out
```

**Important implementation note for the agent:** The snippet above has a subtle first-call cache interaction. Implement first success path as:

```python
if self.baseline is None:
    hit = self.cache.get("feasibility_assess", kwargs)
    if hit is not None:
        result = hit
    else:
        result = underlying(**kwargs)
        self.cache.put("feasibility_assess", kwargs, result)
    if _is_successful_feasibility(result):
        self.baseline = attempted
    self.last_spec_relation = "same" if self.baseline is not None else None
    return result
```

Do **not** route first/later V-01 through `cached["feasibility_assess"]` (that would double-count cache stats). Other tools use `wrap_tools_with_cache` as usual.

- [ ] **Step 4: Run — expect PASS**

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe -m pytest tests/test_idea_session_guards.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/analysis/idea_session_guards.py fulltext_workflow/tests/test_idea_session_guards.py
git commit -m "$(cat <<'EOF'
feat: freeze first V-01 args and block relaxed feasibility re-specs

EOF
)"
```

---

### Task 4: Wire `stream_idea_agent` + prompts + accept gate

**Files:**
- Modify: `fulltext_workflow/idea_agent.py`
- Test: `fulltext_workflow/tests/test_idea_agent_baseline_accept.py`

**Interfaces:**
- Consumes: `IdeaSessionGuards` from Task 3
- Produces: session-wrapped tools in Generator/Critic loops; force `accept=False` when Critic tool results include `feasibility_spec_relaxed`; prompt strings mention freeze + no relaxation

- [ ] **Step 1: Write the failing stream test**

Create `fulltext_workflow/tests/test_idea_agent_baseline_accept.py`:

```python
"""stream_idea_agent must reject accept when V-01 spec was relaxed."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import idea_agent  # noqa: E402


def test_stream_forces_accept_false_on_relaxed_feasibility(monkeypatch):
    def fake_build_bundle(role: str):
        if role == "generator":
            return {"noop": lambda **k: {}}, [
                {
                    "type": "function",
                    "function": {
                        "name": "noop",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        return {"feasibility_assess": lambda **k: {}}, [
            {
                "type": "function",
                "function": {
                    "name": "feasibility_assess",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def fake_bind(tools, _gap):
        return tools

    def fake_run_tool_agent(*, messages, tools, tool_schemas, role, **_kwargs):
        if role == "generator":
            messages.append(
                {"role": "assistant", "content": "## 1. Background\nDraft"}
            )
            if False:
                yield {}
            return
        # Critic: emit relaxed tool error then high-score accept JSON
        yield {
            "type": "tool_result",
            "role": "critic",
            "name": "feasibility_assess",
            "result": {
                "error": "feasibility_spec_relaxed",
                "relaxed_fields": ["required_annotations"],
            },
        }
        messages.append(
            {
                "role": "assistant",
                "content": (
                    '```json\n{"overall_score": 9.0, "accept": true, '
                    '"feasibility_score": 0.9, "available_cohort_size": 1000, '
                    '"dimension_scores": {}, "strengths": [], '
                    '"critical_issues": [], "kg_verification": "", '
                    '"data_feasibility_verification": "", '
                    '"revision_priority": ""}\n```'
                ),
            }
        )
        if False:
            yield {}

    monkeypatch.setattr(idea_agent, "build_idea_role_tool_bundle", fake_build_bundle)
    monkeypatch.setattr(idea_agent, "bind_idea_tools", fake_bind)
    monkeypatch.setattr(idea_agent, "run_tool_agent", fake_run_tool_agent)
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _t: ("C_CA", "test"))
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *a, **k: ("## 1. Background\nDraft", False),
    )
    monkeypatch.setattr(
        idea_agent, "load_supporting_papers_for_keyword", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        idea_agent, "load_public_datasets_for_keyword", lambda *_a, **_k: []
    )

    events = list(
        idea_agent.stream_idea_agent(
            gap_text="colorectal cancer spatial transcriptomics",
            max_rounds=1,
            accept_score=8.0,
        )
    )
    feedback = [e for e in events if e.get("type") == "feedback"]
    assert feedback, events
    assert feedback[0]["accept"] is False
```

Also assert prompts (lightweight) in the same file or extend `test_idea_agent_tool_slim.py`:

```python
def test_prompts_mention_feasibility_baseline_freeze():
    assert "feasibility" in idea_agent.CRITIC_SYSTEM_PROMPT.lower()
    assert "relax" in idea_agent.GENERATOR_SYSTEM_PROMPT.lower() or "removing labels" in idea_agent.GENERATOR_SYSTEM_PROMPT.lower()
    assert "baseline" in idea_agent.CRITIC_SYSTEM_PROMPT.lower() or "first successful" in idea_agent.CRITIC_SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe -m pytest tests/test_idea_agent_baseline_accept.py -v
```

Expected: FAIL (`accept` still True).

- [ ] **Step 3: Wire idea_agent**

In `idea_agent.py`:

1. Import:

```python
from analysis.idea_session_guards import IdeaSessionGuards
```

2. After building `gen_tools` / `crit_tools` via `bind_idea_tools`, create one session and wrap both:

```python
session_guards = IdeaSessionGuards()
gen_tools = session_guards.wrap_tools(gen_tools)
crit_tools = session_guards.wrap_tools(crit_tools)
```

(Place immediately after current `bind_idea_tools` calls ~lines 689–690.)

3. In the Critic event loop, track relaxed:

```python
critic_relaxed = False
for event in run_tool_agent(...):
    ...
    if event.get("type") in ("tool_result", "tool_error"):
        result = event.get("result")
        err = event.get("error")
        if isinstance(result, dict) and result.get("error") == "feasibility_spec_relaxed":
            critic_relaxed = True
        if err == "feasibility_spec_relaxed":
            critic_relaxed = True
        if session_guards.relaxed_seen:
            critic_relaxed = True
    ...
```

Note: `run_tool_agent` yields `tool_error` with `error` string when result has `error` key — handle both.

4. After computing `accept`:

```python
if critic_relaxed or session_guards.relaxed_seen:
    accept = False
```

5. Optionally attach to feedback event:

```python
"feasibility_baseline": session_guards.baseline,
"spec_relation": session_guards.last_spec_relation,
```

6. Prompt additions (exact strings to insert):

In `GENERATOR_SYSTEM_PROMPT` Tool-use / revision area, add:

```text
- Revision rounds must NOT improve feasibility by removing required_labels, \
required_annotations, required_molecular_markers, or lowering min_followup_months. \
Keep the same Fangxin spec (or tighten it); revise evidence and writing instead.
```

In `CRITIC_SYSTEM_PROMPT` after the must-call feasibility bullet, add:

```text
- Runtime freezes the first successful feasibility_assess argument baseline; \
prefer re-calling with the same args. If a tool returns error \
feasibility_spec_relaxed, accept must be false and revisions must not relax requirements.
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd fulltext_workflow
../.venv/Scripts/python.exe -m pytest tests/test_idea_session_guards.py tests/test_idea_agent_baseline_accept.py tests/test_idea_agent_tool_slim.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/idea_agent.py fulltext_workflow/tests/test_idea_agent_baseline_accept.py
git commit -m "$(cat <<'EOF'
feat: enforce V-01 baseline freeze and session tool cache in idea agent

EOF
)"
```

---

### Task 5: Spec status + smoke checklist

**Files:**
- Modify: `docs/superpowers/specs/2026-08-03-idea-feasibility-baseline-cache-design.md` (Status → Implemented)

- [ ] **Step 1: Update spec status line**

Change `**Status:** Approved (design)` → `**Status:** Implemented`.

- [ ] **Step 2: Manual smoke (optional if Fangxin/LLM unavailable)**

- Restart `gap_ui`.
- Run a 2-round proposal where R1 Critic uses annotations and R2 tries to clear them — expect tool error `feasibility_spec_relaxed` and no accept.
- Confirm repeated identical topic tool args across rounds do not double backend work (`session_guards.cache.hits` via debugger/log if added).

- [ ] **Step 3: Commit docs**

```bash
git add docs/superpowers/specs/2026-08-03-idea-feasibility-baseline-cache-design.md
git commit -m "$(cat <<'EOF'
docs: mark feasibility baseline cache design implemented

EOF
)"
```

---

## Spec coverage self-review

| Spec requirement | Task |
|---|---|
| Freeze first successful Critic V-01 args | Task 3–4 |
| same / tighter allowed; relaxed blocked | Task 1, 3 |
| Baseline immutable on tighter | Task 3 |
| `hypothesis_id` ignored | Task 1 |
| Session same-arg cache | Task 2–4 |
| Do not cache errors | Task 2 |
| Force accept=False on relaxed | Task 4 |
| Prompt notes | Task 4 |
| Idea-only; no gap_agent / Fangxin math change | All tasks |
| Tests listed in spec | Tasks 1–4 |

## Placeholder / consistency check

- Module name locked: `idea_session_guards.py`.
- Error code locked: `feasibility_spec_relaxed`.
- Relation strings locked: `same` / `tighter` / `relaxed`.
- No TBD steps remain.
