# Gap Debate Tool-Pack Soft Slim Design

**Date:** 2026-07-30  
**Status:** Proposed, awaiting review  
**Scope:** Soft-slim the gap-debate tool surface by role (Optimist / Skeptic / Moderator). Keep all tool implementations; restrict which schemas each role sees and rewrite prompt quotas.

## Problem summary

The gap debate currently exposes a large shared tool pack (`GAP_TOOLS` + feasibility tools for Moderator). Prompt rules also force broad scanning (“call at least 5 tools”, “include 1 graph_*”). In real runs (e.g. breast cancer):

- Optimist calls 10+ tools per round, including weak-signal scanners and broken free-form SQL.
- Overlapping limitation / combo / graph tools create noise rather than research guidance.
- Empty tools (`limitation_gap_status`, `emerging_gap_opportunities` for some foci) still consume iterations.
- DeepEvidence-style evidence suggests: too many tools + unclear division hurts more than it helps.

For a **research-guidance** product, the useful signals are: focus coverage, limitation lifecycle, transferable opportunities, actionable improvements, frontier papers, and Fangxin feasibility — not Cartesian coverage holes or extraction QA counters.

## Goals

1. Give each debate role a **small, role-specific tool surface** (≤6 / ≤5 / ≤4).
2. Replace “call many tools” quotas with an ordered, capped workflow.
3. Keep all existing tool functions available for analyze / CLI / future reuse.
4. Make Optimist stop treating `method_disease_combo_gap` and graph scanners as primary opportunity evidence.
5. Keep `execute_kg_sql` as a **verification fallback**, mainly for Skeptic / Moderator conflict resolution.

## Non-goals

- Hard-delete tools from `SQL_TOOLS` / codebase.
- Merge limitation tools into a new `limitation_gap_brief` (follow-up).
- Slim `idea_agent` in this round.
- UI redesign of `gap_ui.py`.
- Changing Fangxin API tools’ underlying implementation.

## Approach (chosen)

**Role-specific tool surfaces + prompt quotas** (soft slim).

Rejected for this round:

- Unified 8-tool pack shared by all roles — Skeptic still sees scan tools.
- Hard delete — too risky while analyze/CLI may still call tools.
- Limitation brief merge — valuable, but expands scope.

## Role tool surfaces

### Optimist (≤6 tools)

Ordered preference:

1. `corpus_focus_coverage`
2. `limitation_temporal_profile`
3. `emerging_gap_opportunities`
4. `improvement_suggestions_by_topic`
5. `recent_highcite_papers`
6. `disease_task_coverage` (optional coverage check)

Explicitly **not** exposed: `method_disease_combo_gap`, `combo_gap_temporal`, all `graph_*`, `execute_kg_sql`, `hotspot_entities`, `metric_evidence_quality`, `study_type_relation_stats`, `literature_impact_priority_matrix`, `limitation_gap_status`, `limitation_impact_rank`.

### Skeptic (≤5 tools)

1. `corpus_focus_coverage`
2. `limitation_temporal_profile`
3. `author_stated_gaps`
4. `execute_kg_sql` (max 2 calls per phase; targeted verification only)
5. One cross-check tool: prefer `disease_task_coverage` (or `recent_highcite_papers` if needed for claim checking)

Explicitly **not** exposed: combo scanners, graph scanners, emerging opportunity board, improvement suggestions (Optimist-facing), Fangxin catalog.

### Moderator (≤4 tools)

1. `literature_data_cross_matrix`
2. `pathology_disease_catalog`
3. `corpus_focus_coverage` (when needed for scale statements)
4. `execute_kg_sql` (conflict adjudication only)

Explicitly **not** exposed: fine-grained V1.1 distribution tools (`subtype_distribution`, `attribute_distribution`, `molecular_positivity`, `text_disease_matches`, `disease_cohort_stats`) and full KG scan pack.

## Prompt / loop changes (`gap_agent.py`)

- Remove Optimist rules: “at least 5 tools” and “including 1 graph_*”.
- Add per-role budgets and preferred order matching the lists above.
- User messages for Optimist round 1 should instruct the ordered sequence rather than “call many tools”.
- Skeptic: keep independent verification, but prefer curated checks + limited SQL.
- Moderator: emphasize feasibility synthesis; discourage re-scanning the KG.

`max_iters` may stay as a hard ceiling, but prompts should make soft budgets the primary control (`Optimist ≤6`, `Skeptic ≤5`, `Moderator ≤4` tool calls).

## Code structure

Keep implementations intact. Add a small selector helper, e.g.:

```python
def select_tool_bundle(
    names: list[str],
    tools: dict[str, Any],
    schemas: list[dict],
) -> tuple[dict[str, Any], list[dict]]:
    ...
```

Wire in `stream_gap_debate_agent`:

- Optimist / Skeptic: subsets of `GAP_TOOLS` / `GAP_TOOL_SCHEMAS`
- Moderator: subset of `GAP_FEASIBILITY_TOOLS` / `GAP_FEASIBILITY_SCHEMAS` (plus any required KG tools listed above)

Continue using `bind_tools_with_focus` on each role’s subset.

## Testing

Add focused tests (no live LLM):

1. Optimist schema names == approved set; size ≤ 6.
2. Skeptic schema includes `execute_kg_sql`, excludes `method_disease_combo_gap` and `graph_*`.
3. Moderator schema includes cross-matrix + disease catalog; excludes V1.1 distribution tools.
4. Prompt contract: Optimist prompt must not require “at least 5 tools” / `graph_*`; must mention the ordered core tools / budget.

## Success criteria

- Role schema sizes match design caps.
- Prompt no longer forces broad multi-tool scanning.
- Existing SQL guard / focus-bind regressions remain green.
- A restarted debate should show Optimist spending most calls on coverage → limitation → transferable → improvement, not combo/graph/SQL thrash.

## Follow-ups (out of scope)

- Merge limitation tools into `limitation_gap_brief`.
- Soft-slim `idea_agent` similarly.
- Optionally demote `method_disease_combo_gap` description to “coverage diagnostic only” even for non-agent callers.
