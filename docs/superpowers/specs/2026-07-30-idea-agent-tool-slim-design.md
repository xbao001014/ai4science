# Research Proposal (`idea_agent`) Tool-Pack Soft Slim Design

**Date:** 2026-07-30  
**Status:** Implemented (soft slim landed; restart gap_ui to pick up)  
**Scope:** Soft-slim the research-proposal Generator × Critic tool surface. Keep all tool implementations; restrict which schemas each role sees and rewrite prompt quotas. Mirror the gap-debate soft slim (`2026-07-30-gap-debate-tool-slim-design.md`).

## Problem summary

`idea_agent` still exposes the full merged pack:

- 8 topical SQL tools (`related_papers`, `methods_for_topic`, …)
- 3 `graph_*` scanners
- 11 Fangxin feasibility / V1.1 distribution tools
- `execute_kg_sql`

Prompt quotas force broad scanning:

- Generator: “at least 5 tools, including 1 `graph_*`” + must call `public_dataset_assess`
- Critic: “at least 2 KG tools” + must call `feasibility_assess` / `public_dataset_assess`

This conflicts with the research-guidance product goal and with the already-slimmed gap debate. Graph scanners and V1.1 fine-grained distribution tools dilute rounds that should ground methods, metrics, improvements, and Fangxin feasibility. Under partial extraction (e.g. breast focus papers ≫ extracted papers), forced multi-tool scanning amplifies title-match noise.

## Goals

1. Give Generator and Critic **small, role-specific tool surfaces** (Generator ≤7, Critic ≤5).
2. Replace “call many tools / include graph_*” quotas with an ordered, capped workflow.
3. Keep all existing tool functions available for analyze / CLI / `IDEA_TOOLS` introspection / future reuse.
4. Keep Fangxin feasibility core (`public_dataset_assess`, `feasibility_assess`, disease resolution) as first-class.
5. Keep `execute_kg_sql` as a **Critic verification fallback** (not a Generator discovery tool).

## Non-goals

- Hard-delete tools from `_SQL_IDEA_TOOLS` / `GRAPH_TOOLS` / `FEASIBILITY_TOOLS`.
- Slim or redesign `gap_ui.py` research-proposal tab beyond any label that already reads from live schemas.
- Change Fangxin API tool implementations.
- Merge or rewrite topical SQL tool bodies.
- Change difficulty scoring / proposal Markdown section structure.

## Approaches considered

| Approach | Pros | Cons |
|---|---|---|
| **A. Role-specific soft slim (chosen)** | Matches gap debate; low risk; keeps implementations | Two schema packs to maintain |
| B. Shared 8-tool pack for both roles | Simpler registry | Critic still sees drafting tools; Generator still sees verification-only tools |
| C. Prompt-only (keep full schemas) | Tiny diff | Models still see ~23 tools; quotas alone rarely enough |

**Chosen:** A — same pattern as gap debate (`select_tool_bundle` + role name lists + prompt budgets).

## Role tool surfaces

### Generator (≤7 tools)

Ordered preference:

1. `recent_papers_for_topic` — frontier grounding (prefer over `related_papers` to bias recent evidence)
2. `methods_for_topic`
3. `datasets_for_topic`
4. `metrics_for_topic`
5. `improvement_suggestions_for_topic` (fallback: if empty/sparse, may still call `author_limitations_for_topic` **only when** that tool is also in the pack — see note below)
6. `public_dataset_assess` (V-03; required once when discussing external/public data or drafting data plan)
7. `pathology_disease_catalog` (when disease_id is unmapped / needs confirmation)

**Pack note on limitations:** To stay ≤7, expose **either**:

- Preferred pack (≤7): include `improvement_suggestions_for_topic` and omit `author_limitations_for_topic`; prompt says “if suggestions are sparse, state limitation uncertainty from metrics/papers rather than inventing.”

**or** swap: if product prefers problem-statement first, replace `improvement_suggestions_for_topic` with `author_limitations_for_topic`.

**Decision locked for this round:** prefer `improvement_suggestions_for_topic` (actionability). Do **not** expose both in the Generator schema pack.

Explicitly **not** exposed to Generator:

- all `graph_*`
- `execute_kg_sql`
- `related_papers` (superseded by `recent_papers_for_topic` in this pack)
- `modality_coverage_for_topic`
- `author_limitations_for_topic` (this round)
- `feasibility_assess` (Critic owns V-01; Generator may still write Fangxin params section from catalog + prior debate context)
- `data_gap_analysis`, `literature_data_cross_matrix`
- V1.1 fine tools: `disease_cohort_stats`, `subtype_distribution`, `attribute_distribution`, `molecular_positivity`, `text_disease_matches`
- `pathology_tasks_for_disease` (optional later; omit this round to keep ≤7)

### Critic (≤5 tools)

1. `feasibility_assess` (V-01; required)
2. `public_dataset_assess` (V-03; required when proposal cites or omits public datasets)
3. `metrics_for_topic` (evidence-quote consistency check)
4. `execute_kg_sql` (max 2 calls; targeted verification only)
5. `text_disease_matches` (only when disease_id mapping is disputed / unmapped)

Explicitly **not** exposed to Critic:

- all `graph_*`
- Generator drafting scanners (`methods_for_topic`, `recent_papers_for_topic`, …) except the single metrics cross-check above
- `data_gap_analysis`, `literature_data_cross_matrix`, other V1.1 distribution tools except `text_disease_matches`
- `pathology_disease_catalog` / `pathology_tasks_for_disease` (Generator already resolved disease when possible; Critic uses `text_disease_matches` + `feasibility_assess`)

## Prompt / loop changes (`idea_agent.py`)

- Remove Generator rules: “at least 5 tools” and “including 1 graph_*”.
- Remove Critic “at least 2 KG tools” as a volume quota; replace with the ordered Critic pack + required V-01/V-03 where applicable.
- Add budgets: Generator ≤7 tool calls per drafting phase; Critic ≤5; Critic SQL ≤2.
- Round-1 user message: instruct the ordered Generator sequence, not “call many tools”.
- Keep `SQL_FALLBACK_GUIDANCE` on Critic; Generator prompt should say curated tools only (no SQL discovery).
- Keep gap-anchor / disease_id rules unchanged.
- Keep finalize-proposal path (`_ensure_proposal_draft`) unchanged.

`max_iters` may stay as a hard ceiling; soft budgets are the primary control.

## Code structure

Reuse `select_tool_bundle` from `analysis/agent_utils.py`.

In `idea_agent.py`:

```python
GENERATOR_TOOL_NAMES = [...]  # ≤7
CRITIC_TOOL_NAMES = [...]     # ≤5

def build_idea_role_tool_bundle(role: str) -> tuple[dict, list]:
    # merge IDEA_TOOLS + schemas once, then select_tool_bundle by role
```

Wire in `stream_idea_agent`:

- Generator `run_tool_agent(..., tools=gen_tools, tool_schemas=gen_schemas)`
- Critic `run_tool_agent(..., tools=crit_tools, tool_schemas=crit_schemas)`
- Continue `bind_idea_tools` on each role’s subset (or bind full then select — prefer: select first, then bind, so wrappers only wrap exposed tools)

Keep module-level `IDEA_TOOLS` / `IDEA_TOOL_SCHEMAS` as the **full** registry for UI metrics / CLI / tests that assert registration of `execute_kg_sql`. Role bundles are what agents see at call time.

Update existing SQL guidance tests if they assume Critic/Generator prompts both mention SQL the same way: Critic must still mention `execute_kg_sql` as fallback; Generator may omit SQL usage or explicitly say “do not use execute_kg_sql”.

## Testing

Focused tests (no live LLM):

1. Generator schema names == approved set; size ≤ 7; no `graph_*`; no `execute_kg_sql`.
2. Critic schema includes `feasibility_assess`, `public_dataset_assess`, `execute_kg_sql`; excludes `graph_*` and `methods_for_topic`.
3. Prompt contract: Generator must not require “at least 5 tools” / `graph_*`; must mention budget / ordered core tools.
4. Critic prompt: SQL capped; must still require feasibility checks.
5. `stream_idea_agent` uses matching role bundles (monkeypatch like gap debate test).
6. Existing `test_idea_agent_sql_guidance.py`: full `IDEA_TOOLS` still registers `execute_kg_sql`; adjust prompt assertions so Generator-only omission of SQL is allowed if Critic still carries the fallback contract.

## Success criteria

- Role schema sizes match design caps.
- Prompt no longer forces graph scanning or “call ≥5 tools”.
- Fangxin V-01 / V-03 remain required where specified.
- Existing SQL guard / focus-bind / idea SQL registration regressions remain green.
- A restarted research-proposal run should show Generator spending calls on papers → methods → datasets → metrics → improvements → V-03 (/ catalog), not graph/SQL thrash.

## Follow-ups (out of scope)

- Optionally add `author_limitations_for_topic` back by swapping or raising Generator cap to 8.
- Optionally expose `pathology_tasks_for_disease` to Generator when disease_id is known.
- Align gap-ui tool count metric to “role pack size” vs full `IDEA_TOOLS` length.
- Further demote unused V1.1 tools in other agents.

## Relation to gap debate slim

| | Gap debate | Research proposal |
|---|---|---|
| Roles | Optimist / Skeptic / Moderator | Generator / Critic |
| Primary evidence | coverage, limitations, transferable gaps | methods, metrics, datasets, Fangxin feasibility |
| SQL | Skeptic / Moderator | Critic only |
| Graph | removed from all roles | removed from both roles |
