# Idea Agent: Feasibility Baseline Freeze + Session Tool Cache

**Date:** 2026-08-03  
**Status:** Implemented  
**Scope:** Research-proposal Generator × Critic loop in `idea_agent.stream_idea_agent` only.  
**Depends on:** Idea tool soft slim (`2026-07-30-idea-agent-tool-slim-design.md`), Fangxin V-01 (`analysis/feasibility_tools.py`).

## Problem

Two failure modes showed up in live proposal runs (focus e.g. colorectal / spatial transcriptomics):

1. **Spec relaxation gaming.** Round-1 Critic calls `feasibility_assess` with demanding `required_labels` / `required_annotations`. Round-2 empties annotations and softens labels; score jumps (e.g. 4.5 → 8.2) and `accept=True`. Raising the score by lowering the bar is not an intended revision path.
2. **Stateless round re-fetch.** Each Generator/Critic round starts a fresh message history. The model re-runs nearly the same topic tools (recent papers, methods, datasets, V-03, metrics, …), wasting tool budget without new evidence.

## Goals

1. After the Critic’s **first successful** `feasibility_assess`, freeze that call’s args as the session **feasibility baseline**. Later V-01 calls may only be **same** or **tighter**; **relaxed** specs are rejected in code (no Fangxin call).
2. Within one `stream_idea_agent` session, cache IDEA tool results by `(tool_name, normalized_args)` so cross-round identical calls do not re-hit backends.
3. If a relaxed V-01 attempt occurs, force `accept=False` even if the model JSON claims accept / high score.
4. Keep revisions about evidence and writing quality, not about deleting requirements.

## Non-goals

- Changing Fangxin API clients or V-01 scoring math.
- Changing gap-debate / `gap_agent`.
- Using Generator §9 Markdown as the baseline source (baseline = Critic first successful V-01 args only).
- Shrinking revision-round tool packs to “issue-directed only” (deferred; cache is the chosen reuse mechanism).
- Persisting cache or baseline across separate UI/CLI runs.
- Hard UI redesign (optional status line for `feasibility_spec_relaxed` is enough).

## Approaches considered

| Approach | Pros | Cons |
|---|---|---|
| **1. Session wrappers in `idea_agent` (chosen)** | Localized; testable; no debate coupling | Idea-path only |
| 2. Hooks inside `run_tool_agent` | Reusable | Larger surface than needed |
| 3. Prompt + post-hoc §9 parse | Tiny diff | Does not enforce freeze |

**Chosen:** 1 — `FeasibilityBaseline` + `ToolResultCache` owned by the idea session; wrap tools before `run_tool_agent`.

## Architecture

```text
stream_idea_agent
  ├─ build role tool bundles + bind_idea_tools
  ├─ wrap with session guards (baseline + cache)
  └─ per round: Generator → draft → Critic → feedback
        Critic feasibility_assess:
          no baseline yet + success → set baseline, cache result
          same → prefer cache
          tighter → allow real call (new cache key); do NOT update baseline
          relaxed → return error; no Fangxin; no cache write
        other IDEA tools: cache hit/miss by normalized args
  └─ accept gate: relaxed error seen this critic round ⇒ accept=False
```

Module: `fulltext_workflow/analysis/idea_session_guards.py`  
Wire-up: `fulltext_workflow/idea_agent.py` (`stream_idea_agent`, prompts).  
Note: Generator’s tool pack does not include `feasibility_assess`; only Critic can set the baseline.

## Feasibility baseline

### When set

First session `feasibility_assess` that returns a **successful** payload: result is a `dict`, has no `error` key, **and** includes a numeric-parsable `feasibility_score`. Capture the **call arguments** (not the score) as baseline. Baseline is immutable for the rest of the session.

### Fields in baseline

| Field | In baseline? |
|---|---|
| `disease_id` | yes |
| `task_type` | yes |
| `required_labels` | yes |
| `required_molecular_markers` | yes |
| `required_annotations` | yes |
| `min_followup_months` | yes |
| `hypothesis_id` | **no** (optional metadata; ignored in compare) |

### Normalization

- List fields: strip, casefold for compare, dedupe, sort.
- Missing / `None` list → empty set.
- Missing `min_followup_months` → `0` for compare.
- `disease_id` / `task_type`: strip; compare case-insensitively (preserve original baseline spelling for error payloads).

### Relation to baseline

| Relation | Rule |
|---|---|
| `same` | All normalized fields equal |
| `tighter` | `disease_id` and `task_type` unchanged; each of labels/markers/annotations is a **superset** of baseline (equality allowed); `min_followup_months ≥` baseline; and **at least one** list is a strict super-set **or** followup strictly greater |
| `relaxed` | Any list is a strict subset of baseline, or followup decreases, or `disease_id` / `task_type` changes |

Mixed “some tighter, some looser” ⇒ **`relaxed`** (any loosening fails).

### Relaxed call behavior

Do not call Fangxin. Return:

```json
{
  "error": "feasibility_spec_relaxed",
  "baseline": { "...": "..." },
  "attempted": { "...": "..." },
  "relaxed_fields": ["required_annotations", "..."]
}
```

Do not write this payload into the success cache.

### Tighter call behavior

Allowed; may call Fangxin (or miss cache). **Do not** replace the baseline with the tighter args (avoids a sliding freeze that later permits “less tight than last call but still looser than original”).

## Session tool cache

- **Scope:** one `stream_idea_agent` invocation; shared across Generator and Critic rounds.
- **Key:** `(tool_name, canonical_json(normalized_args))`.
- **Normalize args:** stable key order; list fields sorted after the same string normalize used for baseline where applicable; treat missing optional kwargs consistently with tool defaults when known.
- **Hit:** return the prior result unchanged (do not mutate Fangxin-shaped bodies). Track hits on the session object (`cache_hits`); surface `cached: true` on streamed `tool_result` events only if `run_tool_agent` already forwards arbitrary event fields—otherwise rely on session counters / logs.
- **Store:** only non-error results. Never cache `feasibility_spec_relaxed` or other `error` payloads.
- **Coverage:** all tools in the Generator and Critic idea bundles for that session.

## Accept / feedback gate

Existing rules remain (`ACCEPT_SCORE`, `FEASIBILITY_SCORE_MARGINAL`). Add:

- If this Critic round observed `error == feasibility_spec_relaxed` on any tool result → force `accept=False` regardless of model JSON / score.
- Feedback / events may include `feasibility_baseline` (snapshot) and last `spec_relation` for observability.

## Prompt changes (short)

**Generator (esp. revision rounds):** Do not improve feasibility by removing labels, annotations, markers, or lowering `min_followup_months`. Revise with evidence, clarity, or an explicit data-limitation section under the same (or tighter) Fangxin spec.

**Critic:** Runtime enforces the first successful V-01 arg baseline. Prefer re-calling V-01 with the **same** baseline args. On `feasibility_spec_relaxed`, set `accept=false` and demand revision without relaxing requirements.

## Testing

1. Unit: normalize + `same` / `tighter` / `relaxed` (including mixed → relaxed; disease_id change → relaxed).
2. Unit: relaxed wrapper does not invoke underlying `tool_feasibility_assess` / client.
3. Unit: identical args second call hits cache (mock counter).
4. Integration-style (monkeypatch `run_tool_agent`): relaxed error in Critic round ⇒ streamed feedback `accept=False`.

## Rollout

1. Land guards module + `idea_agent` wiring + tests.
2. Restart `gap_ui` to pick up.
3. No DB migration.

## Open decisions (locked in brainstorm)

| Decision | Choice |
|---|---|
| Scope | Anti-relax primary + same-arg cache |
| Freeze policy | Code-level; same or tighter only |
| Baseline source | Critic first successful `feasibility_assess` args |
| Tool reuse | Session same-arg cache |
| Implementation locus | Idea-session wrappers (not `run_tool_agent` core) |
