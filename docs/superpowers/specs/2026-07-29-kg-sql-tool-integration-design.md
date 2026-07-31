# KG SQL Tool Integration Design

**Date:** 2026-07-29  
**Status:** Proposed, awaiting review  
**Scope:** Make `execute_kg_sql` a deliberate, test-covered fallback for `gap_agent` and `idea_agent`, rather than a passive extra tool in the registry.

## Problem summary

`execute_kg_sql` now exists in `analysis/gap_tools.py` and is registered in `GAP_TOOL_SCHEMAS`, so the model can technically call it. That is not enough for reliable use:

- the tool description does not strongly communicate when it should be used;
- agent prompts do not distinguish between broad discovery and targeted SQL verification;
- the runtime guard is minimal, so expensive or low-signal queries remain possible;
- there is no focused test coverage proving the read-only restrictions and intended guardrails.

As a result, the feature is present in code but not yet operationalized as part of the research workflow.

## Goals

- Make `execute_kg_sql` a clear fallback path when pre-built tools cannot answer a targeted question.
- Bias `Optimist`, `Skeptic`, and `Moderator` toward different SQL usage patterns aligned with their roles.
- Reuse the same guidance in `idea_agent` so tool behavior is consistent across agent flows.
- Add focused automated tests for SQL safety, truncation, and high-risk query guards.

## Non-goals

- No UI work in `gap_ui.py`.
- No new CLI entrypoint or standalone SQL console.
- No general SQL planner, repair loop, or query approval subsystem.
- No write-capable database access.
- No attempt to replace the existing curated tools as the default analysis path.

## Approaches considered

| Approach | Summary | Verdict |
|----------|---------|---------|
| 1. Prompt-only | Tell agents to use SQL when needed | Too weak; behavior likely unstable |
| 2. Prompt + schema guidance | Encode usage rules in both prompts and tool description | Good baseline |
| 3. Prompt + schema + light runtime guard | Add low-cost enforcement for obvious bad queries | **Chosen** |

The chosen approach keeps the feature lightweight while still making misuse less likely.

## Desired behavior

### Role-specific usage

- `Optimist` should default to curated tools for broad scan and candidate generation.
- `Optimist` may use `execute_kg_sql` only when it needs a custom join, aggregation, year slice, or evidence count not exposed by an existing tool.
- `Skeptic` should treat `execute_kg_sql` as a preferred option for targeted verification or falsification of a concrete claim.
- `Moderator` should avoid exploratory SQL and use it only to resolve a conflict between prior findings.
- `idea_agent` should follow the same broad rule as `Optimist`: curated tools first, SQL for custom verification or aggregation.

### Tool selection policy

The agents should internalize the following policy:

1. Use curated tools first for standard gap-analysis questions.
2. Switch to `execute_kg_sql` only when the needed shape is missing: custom joins, grouped counts, time filters, evidence cross-checks, or exact verification.
3. Keep SQL narrow: prefer explicit columns, meaningful `WHERE`, and `LIMIT`.
4. Do not use SQL for raw section dumping unless the question explicitly requires section text.

## Production changes

### 1. `analysis/gap_tools.py`

Keep `execute_kg_sql` as the implementation point and strengthen it in three ways:

- **Schema description**: rewrite the tool description to say when to use it, when not to use it, and what tables are available.
- **Light guardrails**:
  - continue to allow only `SELECT`, `WITH`, and `EXPLAIN`;
  - reject direct `document_sections` queries that do not include `LIMIT`;
  - keep the 100-row cap and return a clear truncation hint;
  - return actionable error messages so the model can self-correct.
- **No complex SQL policing**: do not parse SQL deeply or require a mandatory `WHERE` on every query.

### 2. `gap_agent.py`

Update the role prompts so SQL is part of the strategy rather than an undocumented capability.

- `Optimist`: emphasize curated tools first, SQL only for custom counting / joining / slicing.
- `Skeptic`: explicitly encourage SQL for claim checking, evidence counting, and contradiction testing.
- `Moderator`: discourage SQL except for narrow adjudication queries.

These changes belong in the system-prompt text near the existing focus constraints so the guidance applies consistently across debate rounds.

### 3. `idea_agent.py`

Add the same usage guidance to the relevant prompt text there. The goal is not identical wording, but identical decision logic: SQL is a fallback for custom verification, not the default analysis mode.

## Test plan

Implementation must follow TDD with focused tests first.

### Tool tests

Add `fulltext_workflow/tests/test_execute_kg_sql.py` covering:

- allows a simple `SELECT` query;
- rejects write statements such as `DROP`;
- truncates results above 100 rows and returns a truncation hint;
- rejects `document_sections` access without `LIMIT`;
- allows `document_sections` access when `LIMIT` is present.

These tests should use the real SQLite test DB path already used by the project, not mocks.

### Prompt / registry tests

Add or extend lightweight tests that assert:

- `execute_kg_sql` is present in merged tool schemas;
- its description includes fallback-style guidance rather than generic SQL wording;
- the `gap_agent` prompt text includes explicit policy for when SQL should be used;
- the `idea_agent` prompt text includes matching fallback guidance.

The purpose is not to snapshot whole prompts, only to protect the critical usage contract.

## Error handling

- Invalid or blocked SQL should return structured errors with the original statement included when safe.
- Truncation should not be treated as an error; it should be a successful result with a hint.
- Guardrail failures should explain the fix, for example: add `LIMIT` when querying `document_sections`.

## Verification

Before completion:

- run the new focused SQL tests and watch them fail before implementation;
- run them again after implementation and confirm pass;
- run any affected nearby tests for agent prompt / tool registry behavior;
- run lint diagnostics on edited files.

## Open decisions resolved

- No UI exposure in this task.
- No generic SQL console command in this task.
- No commit is included as part of this task unless explicitly requested by the user.
