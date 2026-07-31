# Research Proposal (`idea_agent`) Tool-Pack Soft Slim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Soft-slim the research-proposal Generator × Critic tool surface so each role sees a small ordered pack, without forced `graph_*` / “≥5 tools” scanning.

**Architecture:** Keep full `IDEA_TOOLS` / `IDEA_TOOL_SCHEMAS` as the registry. Reuse `select_tool_bundle()`. Add `GENERATOR_TOOL_NAMES` / `CRITIC_TOOL_NAMES` and `build_idea_role_tool_bundle()`. Wire `stream_idea_agent` to bind and pass role-specific bundles; rewrite prompts and round-1 user message.

**Tech Stack:** Python 3, pytest, existing OpenAI-compatible tool schemas

## Global Constraints

- Soft slim only: do not hard-delete tools from `_SQL_IDEA_TOOLS` / `GRAPH_TOOLS` / `FEASIBILITY_TOOLS`.
- Exact Generator pack (verbatim from spec): `recent_papers_for_topic`, `methods_for_topic`, `datasets_for_topic`, `metrics_for_topic`, `improvement_suggestions_for_topic`, `public_dataset_assess`, `pathology_disease_catalog`.
- Exact Critic pack (verbatim from spec): `feasibility_assess`, `public_dataset_assess`, `metrics_for_topic`, `execute_kg_sql`, `text_disease_matches`.
- Generator must not see `execute_kg_sql` or any `graph_*`.
- Critic SQL: max 2 calls (prompt contract).
- No UI redesign of `gap_ui.py`.
- Follow TDD: failing test first, then minimal implementation.
- Do not create git commits unless the user explicitly asks.

---

### Task 1: Role bundle constants + schema contract tests

**Files:**
- Modify: `fulltext_workflow/idea_agent.py`
- Create: `fulltext_workflow/tests/test_idea_agent_tool_slim.py`
- Test: `fulltext_workflow/tests/test_idea_agent_tool_slim.py`

**Interfaces:**
- Consumes: `select_tool_bundle` from `analysis.agent_utils`; full `IDEA_TOOLS` / `IDEA_TOOL_SCHEMAS`
- Produces:
  - `GENERATOR_TOOL_NAMES: list[str]` (len ≤ 7)
  - `CRITIC_TOOL_NAMES: list[str]` (len ≤ 5)
  - `build_idea_role_tool_bundle(role: str) -> tuple[dict[str, Any], list[dict]]`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for idea_agent Generator/Critic soft tool slim."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import idea_agent  # noqa: E402
from idea_agent import (  # noqa: E402
    CRITIC_SYSTEM_PROMPT,
    CRITIC_TOOL_NAMES,
    GENERATOR_SYSTEM_PROMPT,
    GENERATOR_TOOL_NAMES,
    build_idea_role_tool_bundle,
)


def test_generator_bundle_size_and_exclusions():
    tools, schemas = build_idea_role_tool_bundle("generator")
    names = [s["function"]["name"] for s in schemas]
    assert names == GENERATOR_TOOL_NAMES
    assert len(names) <= 7
    assert names == [
        "recent_papers_for_topic",
        "methods_for_topic",
        "datasets_for_topic",
        "metrics_for_topic",
        "improvement_suggestions_for_topic",
        "public_dataset_assess",
        "pathology_disease_catalog",
    ]
    assert "execute_kg_sql" not in names
    assert not any(n.startswith("graph_") for n in names)
    assert "author_limitations_for_topic" not in names
    assert set(tools) == set(names)


def test_critic_bundle_has_feasibility_and_sql():
    tools, schemas = build_idea_role_tool_bundle("critic")
    names = [s["function"]["name"] for s in schemas]
    assert names == CRITIC_TOOL_NAMES
    assert len(names) <= 5
    assert names == [
        "feasibility_assess",
        "public_dataset_assess",
        "metrics_for_topic",
        "execute_kg_sql",
        "text_disease_matches",
    ]
    assert "methods_for_topic" not in names
    assert not any(n.startswith("graph_") for n in names)
    assert set(tools) == set(names)


def test_build_idea_role_tool_bundle_unknown_role():
    try:
        build_idea_role_tool_bundle("narrator")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_generator_prompt_uses_budget_not_forced_scan():
    assert "at least 5 tools" not in GENERATOR_SYSTEM_PROMPT
    assert "graph_*" not in GENERATOR_SYSTEM_PROMPT
    assert "≤7" in GENERATOR_SYSTEM_PROMPT or "at most 7" in GENERATOR_SYSTEM_PROMPT.lower()
    assert "improvement_suggestions_for_topic" in GENERATOR_SYSTEM_PROMPT
    assert "public_dataset_assess" in GENERATOR_SYSTEM_PROMPT


def test_critic_prompt_limits_sql_and_keeps_feasibility():
    assert "execute_kg_sql" in CRITIC_SYSTEM_PROMPT
    assert "at most 2" in CRITIC_SYSTEM_PROMPT.lower() or "max 2" in CRITIC_SYSTEM_PROMPT.lower()
    assert "feasibility_assess" in CRITIC_SYSTEM_PROMPT
    assert "≤5" in CRITIC_SYSTEM_PROMPT or "at most 5" in CRITIC_SYSTEM_PROMPT.lower()
    assert "graph_*" not in CRITIC_SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest fulltext_workflow/tests/test_idea_agent_tool_slim.py -v`

Expected: FAIL — cannot import `GENERATOR_TOOL_NAMES` / `build_idea_role_tool_bundle`, and/or prompt still contains `at least 5 tools` / `graph_*`.

- [ ] **Step 3: Write minimal implementation (constants + bundle helper)**

Near the top of `idea_agent.py` after `IDEA_TOOL_SCHEMAS` is defined, add:

```python
from analysis.agent_utils import (
    best_assistant_content,
    bind_tools_with_focus,
    finalize_assistant_content,
    last_assistant_content,
    looks_like_proposal,
    parse_json_block,
    run_tool_agent,
    select_tool_bundle,
)

GENERATOR_TOOL_NAMES = [
    "recent_papers_for_topic",
    "methods_for_topic",
    "datasets_for_topic",
    "metrics_for_topic",
    "improvement_suggestions_for_topic",
    "public_dataset_assess",
    "pathology_disease_catalog",
]

CRITIC_TOOL_NAMES = [
    "feasibility_assess",
    "public_dataset_assess",
    "metrics_for_topic",
    "execute_kg_sql",
    "text_disease_matches",
]


def build_idea_role_tool_bundle(role: str) -> tuple[dict[str, Any], list[dict]]:
    role = role.lower().strip()
    if role == "generator":
        return select_tool_bundle(GENERATOR_TOOL_NAMES, IDEA_TOOLS, IDEA_TOOL_SCHEMAS)
    if role == "critic":
        return select_tool_bundle(CRITIC_TOOL_NAMES, IDEA_TOOLS, IDEA_TOOL_SCHEMAS)
    raise ValueError(f"Unknown idea role: {role}")
```

Leave prompts for Task 2; temporarily skip prompt assertions if needed by implementing Task 1+2 together in one TDD cycle for this file — preferred: implement prompts in Task 2 after bundle tests for names pass (comment out prompt tests only if split; better implement both in sequence in same session).

- [ ] **Step 4: Run name/bundle tests to verify they pass**

Run: `pytest fulltext_workflow/tests/test_idea_agent_tool_slim.py::test_generator_bundle_size_and_exclusions fulltext_workflow/tests/test_idea_agent_tool_slim.py::test_critic_bundle_has_feasibility_and_sql fulltext_workflow/tests/test_idea_agent_tool_slim.py::test_build_idea_role_tool_bundle_unknown_role -v`

Expected: PASS

- [ ] **Step 5: Commit only if user requested**

```bash
# skip unless explicitly asked
```

---

### Task 2: Rewrite Generator / Critic prompts and round-1 user message

**Files:**
- Modify: `fulltext_workflow/idea_agent.py` (`GENERATOR_SYSTEM_PROMPT`, `CRITIC_SYSTEM_PROMPT`, round-1 `gen_user` string)
- Modify: `fulltext_workflow/tests/test_idea_agent_sql_guidance.py` (allow Generator to omit SQL if Critic still carries fallback)
- Test: `fulltext_workflow/tests/test_idea_agent_tool_slim.py` (prompt tests from Task 1)
- Test: `fulltext_workflow/tests/test_idea_agent_sql_guidance.py`

**Interfaces:**
- Consumes: role name lists from Task 1
- Produces: prompt text with budgets; Critic retains `execute_kg_sql` fallback guidance; Generator curated-only

- [ ] **Step 1: Adjust SQL guidance test for role split**

Update `test_idea_agent_sql_guidance.py` so `execute_kg_sql` / curated-first guidance is asserted on **Critic** (and optional shared `SQL_FALLBACK_GUIDANCE`), not necessarily on Generator:

```python
def test_idea_agent_prompt_mentions_execute_kg_sql():
    assert "execute_kg_sql" in idea_agent.CRITIC_SYSTEM_PROMPT


def test_idea_agent_prompt_keeps_sql_as_fallback():
    assert "Use curated tools first" in idea_agent.CRITIC_SYSTEM_PROMPT
    assert "custom join" in idea_agent.CRITIC_SYSTEM_PROMPT
```

Keep `test_idea_agent_registers_sql_fallback_tool_and_schema` unchanged (full registry).

- [ ] **Step 2: Run SQL guidance tests — expect FAIL if Critic prompt not yet updated, or PASS on mention if still present**

Run: `pytest fulltext_workflow/tests/test_idea_agent_sql_guidance.py -v`

- [ ] **Step 3: Rewrite prompts**

Replace Generator tool-use rules block with:

```text
Tool-use rules:
- Budget: at most 7 tool calls while drafting.
- Ordered preference: recent_papers_for_topic → methods_for_topic → datasets_for_topic → metrics_for_topic → improvement_suggestions_for_topic → public_dataset_assess → pathology_disease_catalog (when disease_id is unmapped).
- Do not call graph_* tools or execute_kg_sql.
- Prefer improvement_suggestions_for_topic for actionable next steps; if suggestions are sparse, state limitation uncertainty from metrics/papers rather than inventing.
- Must call public_dataset_assess (V-03) once when discussing external/public data or drafting the data plan.
- Call datasets_for_topic when discussing external data; respect access_class (public|private|unknown). Prefer V-03 recommended_public when labeling public datasets.
- Use pathology_disease_catalog to confirm Fangxin disease support when disease_id is unclear.
```

Replace Critic review rules tool section with:

```text
Review rules:
""" + SQL_FALLBACK_GUIDANCE + """\
- Budget: at most 5 tool calls; execute_kg_sql at most 2 (targeted verification only).
- Ordered preference: feasibility_assess → public_dataset_assess → metrics_for_topic → execute_kg_sql (if needed) → text_disease_matches (if disease_id disputed/unmapped).
- Must call feasibility_assess (V-01) to check disease_id / task_type / label requirements.
- Must call public_dataset_assess (V-03) when the proposal cites public datasets or omits them.
- Do not call graph_* tools.
```

Update round-1 `gen_user` from:

```text
"Call at least 5 tools (including 1 graph_* and public_dataset_assess), "
"then output the full English proposal."
```

to:

```text
"Follow the Generator tool budget (≤7): recent papers → methods → datasets → "
"metrics → improvement suggestions → public_dataset_assess "
"(+ pathology_disease_catalog if disease_id unmapped), "
"then output the full English proposal."
```

- [ ] **Step 4: Run prompt + SQL tests**

Run: `pytest fulltext_workflow/tests/test_idea_agent_tool_slim.py fulltext_workflow/tests/test_idea_agent_sql_guidance.py -v`

Expected: PASS (except stream wiring test if not yet added)

- [ ] **Step 5: Commit only if user requested**

---

### Task 3: Wire `stream_idea_agent` to role bundles

**Files:**
- Modify: `fulltext_workflow/idea_agent.py` (`stream_idea_agent`)
- Modify: `fulltext_workflow/tests/test_idea_agent_tool_slim.py` (add stream test)
- Test: `fulltext_workflow/tests/test_idea_agent_tool_slim.py`

**Interfaces:**
- Consumes: `build_idea_role_tool_bundle`, `bind_idea_tools`
- Produces: Generator and Critic `run_tool_agent` calls receive distinct bound tool packs

- [ ] **Step 1: Write failing stream wiring test**

```python
def test_stream_idea_agent_uses_matching_role_bundles(monkeypatch):
    bundle_calls = []
    agent_calls = []

    def fake_build_bundle(role):
        bundle_calls.append(role)
        return {f"{role}_raw": object()}, [
            {"type": "function", "function": {"name": f"{role}_schema"}}
        ]

    def fake_bind_idea_tools(tools, gap_text):
        name = next(iter(tools))
        return {f"bound_{name}": object()}

    def fake_run_tool_agent(*, messages, tools, tool_schemas, role, **_kwargs):
        agent_calls.append((role, list(tools), tool_schemas))
        if role == "critic":
            content = (
                "```json\n"
                '{"overall_score": 9.0, "accept": true, "feasibility_score": 0.9, '
                '"available_cohort_size": 500, "dimension_scores": {}, '
                '"strengths": [], "critical_issues": [], "kg_verification": "", '
                '"data_feasibility_verification": "", "revision_priority": ""}\n'
                "```"
            )
        else:
            content = (
                "## 1. Background and Rationale\n"
                "## 2. Research Objectives\n"
                "## 3. Research Content\n"
                "## 4. Technical Approach\n"
                "## 5. Clinical Study Design\n"
                "## 6. Innovations\n"
                "## 7. Expected Outcomes and Impact\n"
                "## 8. Timeline\n"
                "## 9. Fangxin Data Integration Parameters\n"
                "REVISION_NOTE: Initial version\n"
            )
        messages.append({"role": "assistant", "content": content})
        if False:
            yield {}

    monkeypatch.setattr(idea_agent, "build_idea_role_tool_bundle", fake_build_bundle)
    monkeypatch.setattr(idea_agent, "bind_idea_tools", fake_bind_idea_tools)
    monkeypatch.setattr(idea_agent, "run_tool_agent", fake_run_tool_agent)
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _t: ("BRCA-IDC", "test"))
    monkeypatch.setattr(
        idea_agent,
        "_assess_difficulty_placeholder",
        None,
    )

    # Patch difficulty path: stream_idea_agent calls nested helpers — monkeypatch
    # assess_implementation_difficulty and related loaders to no-op if invoked.
    monkeypatch.setattr(
        idea_agent,
        "assess_implementation_difficulty",
        lambda **_k: {
            "level": "moderate",
            "score": 0.5,
            "rationale": "test",
            "drivers": [],
        },
    )
    monkeypatch.setattr(idea_agent, "load_supporting_papers_for_keyword", lambda *_a, **_k: [])
    monkeypatch.setattr(idea_agent, "load_public_datasets_for_keyword", lambda *_a, **_k: [])
    monkeypatch.setattr(
        idea_agent,
        "format_difficulty_markdown_header",
        lambda _r: "> **Difficulty**: moderate",
    )

    list(
        idea_agent.stream_idea_agent(
            gap_text="Breast cancer WSI grading gap",
            max_rounds=1,
            accept_score=0.0,
        )
    )

    assert "generator" in bundle_calls
    assert "critic" in bundle_calls
    roles = [c[0] for c in agent_calls]
    assert "generator" in roles
    assert "critic" in roles
    for role, tools, schemas in agent_calls:
        assert list(tools)[0].startswith("bound_")
        assert schemas[0]["function"]["name"] == f"{role}_schema"
```

If `accept_score=0.0` still runs Critic: good. If stream exits early on accept, set `accept_score=10.0` and force Critic accept false on first call — prefer `max_rounds=1` with Critic returning accept true after Generator.

Simplify if difficulty assessment is hard to mock: read `stream_idea_agent` and monkeypatch only what the first round needs. Minimal assert: `bundle_calls` contains generator then critic, and `run_tool_agent` receives distinct schema lists.

- [ ] **Step 2: Run test — expect FAIL** (still uses shared `idea_tools`)

Run: `pytest fulltext_workflow/tests/test_idea_agent_tool_slim.py::test_stream_idea_agent_uses_matching_role_bundles -v`

- [ ] **Step 3: Wire stream**

Replace:

```python
idea_tools = bind_idea_tools(IDEA_TOOLS, gap_text)
```

with:

```python
gen_tools_raw, gen_schemas = build_idea_role_tool_bundle("generator")
crit_tools_raw, crit_schemas = build_idea_role_tool_bundle("critic")
gen_tools = bind_idea_tools(gen_tools_raw, gap_text)
crit_tools = bind_idea_tools(crit_tools_raw, gap_text)
```

In Generator `run_tool_agent` call: `tools=gen_tools`, `tool_schemas=gen_schemas`.  
In Critic `run_tool_agent` call: `tools=crit_tools`, `tool_schemas=crit_schemas`.

- [ ] **Step 4: Run full slim + SQL regression**

Run: `pytest fulltext_workflow/tests/test_idea_agent_tool_slim.py fulltext_workflow/tests/test_idea_agent_sql_guidance.py -v`

Expected: PASS

- [ ] **Step 5: Commit only if user requested**

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Generator ≤7 exact pack | Task 1 |
| Critic ≤5 exact pack | Task 1 |
| No graph_* / Generator no SQL | Task 1–2 |
| Prompt budgets; remove ≥5 + graph_* | Task 2 |
| Round-1 ordered user message | Task 2 |
| stream uses role bundles + bind | Task 3 |
| Full IDEA_TOOLS still registers execute_kg_sql | Task 2 (existing test) |
| Soft slim only / no UI redesign | Global constraints |

## Self-review notes

- No placeholders left in task steps.
- `select_tool_bundle` already exists from gap slim — do not recreate.
- Prompt tests and SQL guidance tests must stay consistent after Generator drops SQL mention.
