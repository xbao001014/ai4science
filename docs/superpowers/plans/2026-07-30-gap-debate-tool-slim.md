# Gap Debate Tool-Pack Soft Slim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Soft-slim the gap-debate tool surface so Optimist / Skeptic / Moderator each see only a small role-specific tool pack, with prompt budgets that stop forced multi-tool scanning.

**Architecture:** Keep all tool implementations registered in the full `GAP_TOOLS` / feasibility registries. Add `select_tool_bundle()` to slice tools+schemas by name. Wire role-specific bundles in `gap_agent.py` and rewrite prompts/user messages to ordered, capped workflows.

**Tech Stack:** Python 3, pytest, existing OpenAI-compatible tool schemas

## Global Constraints

- Soft slim only: do not hard-delete tools from `SQL_TOOLS` / codebase.
- Do not merge limitation tools into `limitation_gap_brief` in this round.
- Do not slim `idea_agent` in this round.
- No UI redesign of `gap_ui.py`.
- Follow TDD: failing test first, then minimal implementation.
- Do not create git commits unless the user explicitly asks (working tree may already be dirty).

---

### Task 1: Add `select_tool_bundle` helper

**Files:**
- Modify: `fulltext_workflow/analysis/agent_utils.py`
- Create: `fulltext_workflow/tests/test_select_tool_bundle.py`
- Test: `fulltext_workflow/tests/test_select_tool_bundle.py`

**Interfaces:**
- Consumes: `tools: dict[str, Any]`, `schemas: list[dict]` with OpenAI function-tool shape
- Produces: `select_tool_bundle(names: list[str], tools: dict[str, Any], schemas: list[dict]) -> tuple[dict[str, Any], list[dict]]`

- [ ] **Step 1: Write the failing tests**

```python
from analysis.agent_utils import select_tool_bundle


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def test_select_tool_bundle_keeps_order_and_filters():
    tools = {"a": lambda: 1, "b": lambda: 2, "c": lambda: 3}
    schemas = [_schema("a"), _schema("b"), _schema("c")]
    selected_tools, selected_schemas = select_tool_bundle(["c", "a"], tools, schemas)
    assert list(selected_tools) == ["c", "a"]
    assert [s["function"]["name"] for s in selected_schemas] == ["c", "a"]


def test_select_tool_bundle_raises_on_unknown_name():
    tools = {"a": lambda: 1}
    schemas = [_schema("a")]
    try:
        select_tool_bundle(["missing"], tools, schemas)
        assert False, "expected KeyError"
    except KeyError as exc:
        assert "missing" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest fulltext_workflow/tests/test_select_tool_bundle.py -v`

Expected: FAIL with `ImportError` / `cannot import name 'select_tool_bundle'`

- [ ] **Step 3: Write minimal implementation**

```python
def select_tool_bundle(
    names: list[str],
    tools: dict[str, Any],
    schemas: list[dict],
) -> tuple[dict[str, Any], list[dict]]:
    schema_by_name = {
        s["function"]["name"]: s
        for s in schemas
        if isinstance(s, dict) and "function" in s
    }
    missing = [n for n in names if n not in tools or n not in schema_by_name]
    if missing:
        raise KeyError(f"Unknown tool(s) for bundle: {missing}")
    selected_tools = {n: tools[n] for n in names}
    selected_schemas = [schema_by_name[n] for n in names]
    return selected_tools, selected_schemas
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest fulltext_workflow/tests/test_select_tool_bundle.py -v`

Expected: PASS

- [ ] **Step 5: Commit only if user requested**

```bash
# skip unless explicitly asked
```

### Task 2: Define role tool-name constants and schema contract tests

**Files:**
- Modify: `fulltext_workflow/gap_agent.py`
- Create: `fulltext_workflow/tests/test_gap_agent_tool_slim.py`
- Test: `fulltext_workflow/tests/test_gap_agent_tool_slim.py`

**Interfaces:**
- Consumes: `select_tool_bundle`, `GAP_TOOLS`, `GAP_TOOL_SCHEMAS`, `GAP_FEASIBILITY_TOOLS`, `GAP_FEASIBILITY_SCHEMAS`
- Produces:
  - `OPTIMIST_TOOL_NAMES: list[str]` (len ≤ 6)
  - `SKEPTIC_TOOL_NAMES: list[str]` (len ≤ 5)
  - `MODERATOR_TOOL_NAMES: list[str]` (len ≤ 4)
  - `build_role_tool_bundle(role: str) -> tuple[dict, list]`

Exact name lists (verbatim from spec):

```python
OPTIMIST_TOOL_NAMES = [
    "corpus_focus_coverage",
    "limitation_temporal_profile",
    "emerging_gap_opportunities",
    "improvement_suggestions_by_topic",
    "recent_highcite_papers",
    "disease_task_coverage",
]

SKEPTIC_TOOL_NAMES = [
    "corpus_focus_coverage",
    "limitation_temporal_profile",
    "author_stated_gaps",
    "execute_kg_sql",
    "disease_task_coverage",
]

MODERATOR_TOOL_NAMES = [
    "literature_data_cross_matrix",
    "pathology_disease_catalog",
    "corpus_focus_coverage",
    "execute_kg_sql",
]
```

- [ ] **Step 1: Write the failing tests**

```python
from gap_agent import (
    MODERATOR_TOOL_NAMES,
    OPTIMIST_TOOL_NAMES,
    SKEPTIC_TOOL_NAMES,
    build_role_tool_bundle,
)


def test_optimist_bundle_size_and_exclusions():
    tools, schemas = build_role_tool_bundle("optimist")
    names = [s["function"]["name"] for s in schemas]
    assert names == OPTIMIST_TOOL_NAMES
    assert len(names) <= 6
    assert "method_disease_combo_gap" not in names
    assert not any(n.startswith("graph_") for n in names)
    assert "execute_kg_sql" not in names
    assert set(tools) == set(names)


def test_skeptic_bundle_has_sql_not_scanners():
    tools, schemas = build_role_tool_bundle("skeptic")
    names = [s["function"]["name"] for s in schemas]
    assert names == SKEPTIC_TOOL_NAMES
    assert "execute_kg_sql" in names
    assert "method_disease_combo_gap" not in names
    assert not any(n.startswith("graph_") for n in names)


def test_moderator_bundle_feasibility_focused():
    tools, schemas = build_role_tool_bundle("moderator")
    names = [s["function"]["name"] for s in schemas]
    assert names == MODERATOR_TOOL_NAMES
    assert "literature_data_cross_matrix" in names
    assert "pathology_disease_catalog" in names
    assert "subtype_distribution" not in names
    assert "disease_cohort_stats" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest fulltext_workflow/tests/test_gap_agent_tool_slim.py -v`

Expected: FAIL because constants / `build_role_tool_bundle` are missing

- [ ] **Step 3: Write minimal implementation**

In `gap_agent.py`:

```python
from analysis.agent_utils import bind_tools_with_focus, select_tool_bundle, ...

OPTIMIST_TOOL_NAMES = [...]  # as above
SKEPTIC_TOOL_NAMES = [...]
MODERATOR_TOOL_NAMES = [...]


def build_role_tool_bundle(role: str) -> tuple[dict[str, Any], list[dict]]:
    role = role.lower().strip()
    if role == "optimist":
        return select_tool_bundle(OPTIMIST_TOOL_NAMES, GAP_TOOLS, GAP_TOOL_SCHEMAS)
    if role == "skeptic":
        return select_tool_bundle(SKEPTIC_TOOL_NAMES, GAP_TOOLS, GAP_TOOL_SCHEMAS)
    if role == "moderator":
        # Moderator needs KG tools + feasibility tools
        merged_tools = {**GAP_TOOLS, **GAP_FEASIBILITY_TOOLS}
        merged_schemas = GAP_TOOL_SCHEMAS + GAP_FEASIBILITY_SCHEMAS
        return select_tool_bundle(MODERATOR_TOOL_NAMES, merged_tools, merged_schemas)
    raise ValueError(f"Unknown debate role: {role}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest fulltext_workflow/tests/test_gap_agent_tool_slim.py -v`

Expected: PASS

- [ ] **Step 5: Commit only if user requested**

### Task 3: Wire role bundles into the debate loop

**Files:**
- Modify: `fulltext_workflow/gap_agent.py` (`stream_gap_debate_agent`)
- Test: `fulltext_workflow/tests/test_gap_agent_tool_slim.py` (extend with a smoke assertion that helper is used, or keep Task 2 coverage)

**Interfaces:**
- Consumes: `build_role_tool_bundle(role)`, `bind_tools_with_focus(tools, focus)`
- Produces: Optimist/Skeptic/Moderator `run_tool_agent(...)` calls using role-specific tools+schemas

- [ ] **Step 1: Write / extend a failing behavioral stub if needed**

Prefer keeping Task 2 as the contract. If desired, add:

```python
def test_build_role_tool_bundle_unknown_role():
    try:
        build_role_tool_bundle("narrator")
        assert False
    except ValueError:
        pass
```

- [ ] **Step 2: Run test to verify failure or confirm missing wiring manually via reading `stream_gap_debate_agent`**

- [ ] **Step 3: Replace shared bundles in `stream_gap_debate_agent`**

Replace:

```python
debate_tools = bind_tools_with_focus(GAP_TOOLS, focus)
moderator_tools = bind_tools_with_focus(GAP_FEASIBILITY_TOOLS, focus)
```

With:

```python
opt_tools_raw, opt_schemas = build_role_tool_bundle("optimist")
ske_tools_raw, ske_schemas = build_role_tool_bundle("skeptic")
mod_tools_raw, mod_schemas = build_role_tool_bundle("moderator")
opt_tools = bind_tools_with_focus(opt_tools_raw, focus)
ske_tools = bind_tools_with_focus(ske_tools_raw, focus)
mod_tools = bind_tools_with_focus(mod_tools_raw, focus)
```

Then pass `opt_tools`/`opt_schemas` to Optimist, `ske_*` to Skeptic, `mod_*` to Moderator `run_tool_agent` calls (both final-report and feedback paths).

- [ ] **Step 4: Run role-bundle tests**

Run: `pytest fulltext_workflow/tests/test_gap_agent_tool_slim.py -v`

Expected: PASS

- [ ] **Step 5: Commit only if user requested**

### Task 4: Rewrite prompt quotas and user-message instructions

**Files:**
- Modify: `fulltext_workflow/gap_agent.py` (system prompts + user message builders)
- Create or extend: `fulltext_workflow/tests/test_gap_agent_sql_guidance.py` / prefer `fulltext_workflow/tests/test_gap_agent_tool_slim.py`
- Test: `fulltext_workflow/tests/test_gap_agent_tool_slim.py`

**Interfaces:**
- Consumes: existing `OPTIMIST_SYSTEM_PROMPT`, `SKEPTIC_SYSTEM_PROMPT`, `MODERATOR_SYSTEM_PROMPT`
- Produces: prompts with budgets `≤6` / `≤5` / `≤4` and ordered tool guidance; no “at least 5 tools” / “graph_*” requirement

- [ ] **Step 1: Write the failing prompt-contract tests**

```python
from gap_agent import (
    MODERATOR_SYSTEM_PROMPT,
    OPTIMIST_SYSTEM_PROMPT,
    SKEPTIC_SYSTEM_PROMPT,
)


def test_optimist_prompt_uses_budget_not_forced_scan():
    assert "at least 5 tools" not in OPTIMIST_SYSTEM_PROMPT
    assert "graph_*" not in OPTIMIST_SYSTEM_PROMPT
    assert "≤6" in OPTIMIST_SYSTEM_PROMPT or "at most 6" in OPTIMIST_SYSTEM_PROMPT.lower()
    assert "emerging_gap_opportunities" in OPTIMIST_SYSTEM_PROMPT
    assert "improvement_suggestions_by_topic" in OPTIMIST_SYSTEM_PROMPT


def test_skeptic_prompt_limits_sql_and_scan():
    assert "execute_kg_sql" in SKEPTIC_SYSTEM_PROMPT
    assert "at most 2" in SKEPTIC_SYSTEM_PROMPT.lower() or "max 2" in SKEPTIC_SYSTEM_PROMPT.lower()
    assert "method_disease_combo_gap" not in SKEPTIC_SYSTEM_PROMPT


def test_moderator_prompt_prefers_feasibility_tools():
    assert "literature_data_cross_matrix" in MODERATOR_SYSTEM_PROMPT
    assert "pathology_disease_catalog" in MODERATOR_SYSTEM_PROMPT
    assert "at most 4" in MODERATOR_SYSTEM_PROMPT.lower() or "≤4" in MODERATOR_SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest fulltext_workflow/tests/test_gap_agent_tool_slim.py -v -k prompt`

Expected: FAIL on old “at least 5 tools” / missing budget text

- [ ] **Step 3: Update prompts and user messages**

Optimist system prompt tool rules should become:

```text
Tool-use rules:
- Use at most 6 tool calls.
- Preferred order: corpus_focus_coverage → limitation_temporal_profile →
  emerging_gap_opportunities → improvement_suggestions_by_topic →
  recent_highcite_papers → disease_task_coverage.
- Do not treat coverage holes as research opportunities.
- Do not call tools outside your available tool list.
```

Skeptic:

```text
- Use at most 5 tool calls.
- Prefer corpus_focus_coverage, limitation_temporal_profile, author_stated_gaps.
- Use execute_kg_sql for targeted verification at most 2 times.
```

Moderator:

```text
- Use at most 4 tool calls.
- Prefer literature_data_cross_matrix and pathology_disease_catalog.
- Use execute_kg_sql only to resolve conflicts.
```

Also change Optimist round-1 user message from:

```text
Then call at least 5 tools (including 1 graph_*), ...
```

to:

```text
Follow the preferred tool order (at most 6 calls), then output candidate-gap Markdown.
```

- [ ] **Step 4: Run prompt + bundle tests**

Run: `pytest fulltext_workflow/tests/test_gap_agent_tool_slim.py -v`

Expected: PASS

- [ ] **Step 5: Commit only if user requested**

### Task 5: Final verification

**Files:**
- Test: `fulltext_workflow/tests/test_select_tool_bundle.py`
- Test: `fulltext_workflow/tests/test_gap_agent_tool_slim.py`
- Test: `fulltext_workflow/tests/test_bind_tools_sql_args.py`
- Test: `fulltext_workflow/tests/test_execute_kg_sql.py`
- Test: `fulltext_workflow/tests/test_gap_agent_sql_guidance.py`

- [ ] **Step 1: Run focused suites**

```bash
pytest fulltext_workflow/tests/test_select_tool_bundle.py \
       fulltext_workflow/tests/test_gap_agent_tool_slim.py \
       fulltext_workflow/tests/test_bind_tools_sql_args.py \
       fulltext_workflow/tests/test_execute_kg_sql.py \
       fulltext_workflow/tests/test_gap_agent_sql_guidance.py -v
```

- [ ] **Step 2: Read lints on edited files**

Edited paths:

- `fulltext_workflow/analysis/agent_utils.py`
- `fulltext_workflow/gap_agent.py`
- `fulltext_workflow/tests/test_select_tool_bundle.py`
- `fulltext_workflow/tests/test_gap_agent_tool_slim.py`

- [ ] **Step 3: Fix any failures**

- [ ] **Step 4: Re-run focused suites**

- [ ] **Step 5: Commit only if user requested**

## Self-review

- **Spec coverage:** role surfaces, soft-slim (no deletes), prompt quotas, selector helper, tests, non-goals all mapped to tasks.
- **Placeholder scan:** no TBD/TODO left; exact tool name lists included.
- **Type consistency:** `select_tool_bundle` / `build_role_tool_bundle` signatures used consistently across tasks.
