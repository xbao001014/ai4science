# KG SQL Tool Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `execute_kg_sql` a reliable fallback tool for `gap_agent` and `idea_agent`, with prompt guidance, light runtime guards, and focused automated tests.

**Architecture:** Keep the existing curated-tool-first workflow and treat SQL as a targeted fallback for custom joins, grouped counts, time slices, and exact verification. Implement the behavior in three layers: tool contract in `analysis/gap_tools.py`, role guidance in `gap_agent.py` and `idea_agent.py`, and regression tests that lock in both runtime and prompt behavior.

**Tech Stack:** Python 3, pytest, SQLite, OpenAI-compatible tool schemas

## Global Constraints

- No UI work in `fulltext_workflow/gap_ui.py`.
- No new CLI entrypoint or standalone SQL console.
- No general SQL planner, repair loop, or query approval subsystem.
- No write-capable database access.
- Do not replace curated tools as the default analysis path.
- Follow TDD: write each failing test first, verify failure, then implement the minimum code to pass.

---

### Task 1: Lock down `execute_kg_sql` runtime behavior

**Files:**
- Modify: `fulltext_workflow/analysis/gap_tools.py`
- Create: `fulltext_workflow/tests/test_execute_kg_sql.py`
- Test: `fulltext_workflow/tests/test_execute_kg_sql.py`

**Interfaces:**
- Consumes: `tool_execute_kg_sql(sql: str, focus: str | None = None) -> dict`
- Produces: same function with enforced read-only behavior, row truncation metadata, and `document_sections` guardrails

- [ ] **Step 1: Write the failing tests**

```python
from analysis.gap_tools import tool_execute_kg_sql
from db.schema import get_conn, init_db


def test_execute_kg_sql_allows_simple_select():
    result = tool_execute_kg_sql("SELECT 1 AS value")
    assert result["data"] == [{"value": 1}]


def test_execute_kg_sql_rejects_write_statement():
    result = tool_execute_kg_sql("DROP TABLE papers")
    assert "Only SELECT/WITH/EXPLAIN allowed" in result["error"]


def test_execute_kg_sql_truncates_large_results():
    result = tool_execute_kg_sql(
        "WITH RECURSIVE nums(n) AS ("
        "SELECT 1 UNION ALL SELECT n + 1 FROM nums WHERE n < 120"
        ") SELECT n FROM nums"
    )
    assert result["row_count"] == 100
    assert result["truncated"] is True
    assert "Results capped" in result["hint"]


def test_execute_kg_sql_rejects_document_sections_without_limit():
    result = tool_execute_kg_sql("SELECT id, content FROM document_sections")
    assert "document_sections" in result["error"]
    assert "LIMIT" in result["error"]


def test_execute_kg_sql_allows_document_sections_with_limit():
    result = tool_execute_kg_sql(
        "SELECT id, content FROM document_sections LIMIT 5"
    )
    assert "error" not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest fulltext_workflow/tests/test_execute_kg_sql.py -v`

Expected: FAIL because `document_sections` without `LIMIT` is not yet blocked and the truncation/guardrail contract is incomplete.

- [ ] **Step 3: Write minimal implementation**

```python
_ALLOWED_SQL_PREFIXES = ("SELECT", "WITH", "EXPLAIN")
_SQL_MAX_ROWS = 100


def _query_needs_limit(sql: str, table: str) -> bool:
    lowered = sql.lower()
    return table in lowered and " limit " not in f" {lowered} "


def tool_execute_kg_sql(sql: str, focus: str | None = None) -> dict:
    sql_stripped = sql.strip().rstrip(";").strip()
    first_word = sql_stripped.split()[0].upper() if sql_stripped else ""
    if first_word not in _ALLOWED_SQL_PREFIXES:
        return {"error": f"Only SELECT/WITH/EXPLAIN allowed, got: {first_word}"}
    if _query_needs_limit(sql_stripped, "document_sections"):
        return {
            "error": "Queries touching document_sections must include LIMIT to avoid dumping raw section text.",
            "sql": sql_stripped,
        }
    # existing query-only execution + 100-row cap remains here
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest fulltext_workflow/tests/test_execute_kg_sql.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/analysis/gap_tools.py fulltext_workflow/tests/test_execute_kg_sql.py
git commit -m "feat: add kg sql runtime guardrails"
```

### Task 2: Teach `gap_agent` when SQL is appropriate

**Files:**
- Modify: `fulltext_workflow/gap_agent.py`
- Create: `fulltext_workflow/tests/test_gap_agent_sql_guidance.py`
- Test: `fulltext_workflow/tests/test_gap_agent_sql_guidance.py`

**Interfaces:**
- Consumes: `OPTIMIST_SYSTEM_PROMPT`, `SKEPTIC_SYSTEM_PROMPT`, `MODERATOR_SYSTEM_PROMPT`
- Produces: prompt text that encodes curated-tool-first policy and role-specific SQL fallback rules

- [ ] **Step 1: Write the failing tests**

```python
from gap_agent import (
    MODERATOR_SYSTEM_PROMPT,
    OPTIMIST_SYSTEM_PROMPT,
    SKEPTIC_SYSTEM_PROMPT,
)


def test_optimist_prompt_says_curated_tools_first():
    assert "Use curated tools first" in OPTIMIST_SYSTEM_PROMPT
    assert "execute_kg_sql" in OPTIMIST_SYSTEM_PROMPT


def test_skeptic_prompt_prefers_sql_for_targeted_verification():
    assert "execute_kg_sql" in SKEPTIC_SYSTEM_PROMPT
    assert "targeted verification" in SKEPTIC_SYSTEM_PROMPT


def test_moderator_prompt_limits_sql_to_conflict_resolution():
    assert "execute_kg_sql" in MODERATOR_SYSTEM_PROMPT
    assert "only to resolve conflicts" in MODERATOR_SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest fulltext_workflow/tests/test_gap_agent_sql_guidance.py -v`

Expected: FAIL because the current prompts do not mention `execute_kg_sql` or the curated-tool-first fallback policy.

- [ ] **Step 3: Write minimal implementation**

```python
SQL_FALLBACK_GUIDANCE = """\
- Use curated tools first for standard gap-analysis questions.
- Use execute_kg_sql only when you need a custom join, grouped count, year filter, or exact evidence cross-check not exposed by an existing tool.
- Keep SQL narrow: explicit columns, meaningful WHERE, and LIMIT.
- Do not dump raw document_sections unless exact section text is necessary.
"""

OPTIMIST_SYSTEM_PROMPT = """\
...
Tool-use rules:
""" + SQL_FALLBACK_GUIDANCE + """\
- Prefer curated tools for broad scan.
..."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest fulltext_workflow/tests/test_gap_agent_sql_guidance.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/gap_agent.py fulltext_workflow/tests/test_gap_agent_sql_guidance.py
git commit -m "feat: guide gap agent sql fallback usage"
```

### Task 3: Mirror the SQL fallback contract in `idea_agent`

**Files:**
- Modify: `fulltext_workflow/idea_agent.py`
- Create: `fulltext_workflow/tests/test_idea_agent_sql_guidance.py`
- Test: `fulltext_workflow/tests/test_idea_agent_sql_guidance.py`

**Interfaces:**
- Consumes: the proposal-generation prompt strings in `idea_agent.py`
- Produces: prompt text that keeps curated topical tools as the default and uses SQL as a targeted fallback

- [ ] **Step 1: Write the failing tests**

```python
import idea_agent


def test_idea_agent_prompt_mentions_execute_kg_sql():
    prompt_text = "\n".join(
        value for name, value in vars(idea_agent).items()
        if name.endswith("_SYSTEM_PROMPT") and isinstance(value, str)
    )
    assert "execute_kg_sql" in prompt_text


def test_idea_agent_prompt_keeps_sql_as_fallback():
    prompt_text = "\n".join(
        value for name, value in vars(idea_agent).items()
        if name.endswith("_SYSTEM_PROMPT") and isinstance(value, str)
    )
    assert "Use curated tools first" in prompt_text
    assert "custom join" in prompt_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest fulltext_workflow/tests/test_idea_agent_sql_guidance.py -v`

Expected: FAIL because the current idea-agent prompts do not describe SQL fallback behavior.

- [ ] **Step 3: Write minimal implementation**

```python
SQL_FALLBACK_GUIDANCE = """\
- Use curated tools first for standard topic scoping.
- Use execute_kg_sql only for custom joins, grouped counts, year filters, or exact evidence verification.
- Keep SQL narrow with explicit columns and LIMIT.
"""

PROPOSER_SYSTEM_PROMPT = """\
...
Tool-use rules:
""" + SQL_FALLBACK_GUIDANCE + """\
..."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest fulltext_workflow/tests/test_idea_agent_sql_guidance.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/idea_agent.py fulltext_workflow/tests/test_idea_agent_sql_guidance.py
git commit -m "feat: align idea agent sql fallback guidance"
```

### Task 4: Verify merged schema and final regression surface

**Files:**
- Modify: `fulltext_workflow/tests/test_execute_kg_sql.py`
- Create: `fulltext_workflow/tests/test_gap_tool_registry_sql.py`
- Test: `fulltext_workflow/tests/test_gap_tool_registry_sql.py`

**Interfaces:**
- Consumes: `analysis.graph_tools.init_gap_registry()`, `GAP_TOOL_SCHEMAS`
- Produces: regression coverage that `execute_kg_sql` remains present and self-describing in the merged registry used by agents

- [ ] **Step 1: Write the failing tests**

```python
from analysis.graph_tools import GAP_TOOL_SCHEMAS, init_gap_registry


def test_execute_kg_sql_present_in_merged_gap_tool_schemas():
    init_gap_registry()
    names = [tool["function"]["name"] for tool in GAP_TOOL_SCHEMAS]
    assert "execute_kg_sql" in names


def test_execute_kg_sql_schema_describes_fallback_usage():
    init_gap_registry()
    schema = next(
        tool["function"]
        for tool in GAP_TOOL_SCHEMAS
        if tool["function"]["name"] == "execute_kg_sql"
    )
    description = schema["description"]
    assert "Use when pre-built tools cannot answer" in description
    assert "Returns up to 100 rows" in description
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest fulltext_workflow/tests/test_gap_tool_registry_sql.py -v`

Expected: FAIL because the current schema description is too generic or does not include the fallback contract text.

- [ ] **Step 3: Write minimal implementation**

```python
{
    "name": "execute_kg_sql",
    "description": (
        "Execute a read-only SQL SELECT query against the KG SQLite database. "
        "Use when pre-built tools cannot answer your question or you need custom "
        "joins, aggregations, year filters, or exact verification. "
        "Returns up to 100 rows."
    ),
    ...
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest fulltext_workflow/tests/test_gap_tool_registry_sql.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/tests/test_gap_tool_registry_sql.py fulltext_workflow/analysis/gap_tools.py
git commit -m "test: cover kg sql tool registry contract"
```

### Task 5: Final verification

**Files:**
- Modify: none required unless fixes are needed
- Test: `fulltext_workflow/tests/test_execute_kg_sql.py`
- Test: `fulltext_workflow/tests/test_gap_agent_sql_guidance.py`
- Test: `fulltext_workflow/tests/test_idea_agent_sql_guidance.py`
- Test: `fulltext_workflow/tests/test_gap_tool_registry_sql.py`

**Interfaces:**
- Consumes: all prior task outputs
- Produces: verified passing implementation with clean diagnostics

- [ ] **Step 1: Run focused test suite**

```bash
pytest fulltext_workflow/tests/test_execute_kg_sql.py \
       fulltext_workflow/tests/test_gap_agent_sql_guidance.py \
       fulltext_workflow/tests/test_idea_agent_sql_guidance.py \
       fulltext_workflow/tests/test_gap_tool_registry_sql.py -v
```

- [ ] **Step 2: Read lint diagnostics for edited files**

```text
ReadLints(paths=[
  "fulltext_workflow/analysis/gap_tools.py",
  "fulltext_workflow/gap_agent.py",
  "fulltext_workflow/idea_agent.py",
  "fulltext_workflow/tests/test_execute_kg_sql.py",
  "fulltext_workflow/tests/test_gap_agent_sql_guidance.py",
  "fulltext_workflow/tests/test_idea_agent_sql_guidance.py",
  "fulltext_workflow/tests/test_gap_tool_registry_sql.py",
])
```

- [ ] **Step 3: Fix any failing tests or introduced lints**

```python
# Keep fixes scoped to the verified failures only.
```

- [ ] **Step 4: Re-run focused test suite**

```bash
pytest fulltext_workflow/tests/test_execute_kg_sql.py \
       fulltext_workflow/tests/test_gap_agent_sql_guidance.py \
       fulltext_workflow/tests/test_idea_agent_sql_guidance.py \
       fulltext_workflow/tests/test_gap_tool_registry_sql.py -v
```

- [ ] **Step 5: Commit**

```bash
git add fulltext_workflow/analysis/gap_tools.py \
        fulltext_workflow/gap_agent.py \
        fulltext_workflow/idea_agent.py \
        fulltext_workflow/tests/test_execute_kg_sql.py \
        fulltext_workflow/tests/test_gap_agent_sql_guidance.py \
        fulltext_workflow/tests/test_idea_agent_sql_guidance.py \
        fulltext_workflow/tests/test_gap_tool_registry_sql.py
git commit -m "feat: operationalize kg sql fallback for agents"
```

## Self-review

- **Spec coverage:** runtime guardrails, prompt guidance in both agent flows, schema contract, and verification are all mapped to tasks.
- **Placeholder scan:** no `TODO`/`TBD` placeholders remain; each task includes concrete paths, commands, and expected outcomes.
- **Type consistency:** the plan consistently targets `tool_execute_kg_sql(sql: str, focus: str | None = None) -> dict` and prompt-string constants in `gap_agent.py` / `idea_agent.py`.
