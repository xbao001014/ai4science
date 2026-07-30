# Binding Actionability MVP Design — 2026-07-30

**Status:** Approved for implementation planning  
**Scope:** Register orphan study-type QA tool + Phase 2 MVP annotations on existing combo / priority / transferable opportunity surfaces.  
**Delivery batch:** Round 1 of 2 (Round 2 = study-type downstream ranking / dedicated UI).

## Problem

1. `tool_study_type_relation_stats` exists and is tested but is **not** registered in `SQL_TOOLS` / `TOOL_SCHEMAS`, so agents cannot call it.
2. Extraction-quality Phase 1 already persists `paper_entity_bindings` and trustworthy Dataset `access_class`, but Phase 2 hotspot/combo **actionability** was left interface-only — tools still ignore bindings.
3. Cartesian Method×Disease remains in `method_disease_combo_gap` / impact matrix; the **primary** opportunity narrative already moved to Task-bridged transferable candidates. This MVP must annotate and lightly re-rank, **not** revive Cartesian as the main story.

## Decisions

| Topic | Choice |
|-------|--------|
| Round scope | Tool registry + Phase 2 MVP; defer `COVERS_DISEASE` / `SURVEYS_METHOD` product UI |
| Phase 2 depth | Annotate existing tools (keep candidate sets); do not replace generators with bindings-first selection |
| UI | Extra columns on existing tables only; no new tabs |

## Goals

- Agents can call `study_type_relation_stats` for read-only counts of `SURVEYS_METHOD`, `COVERS_DISEASE`, `RELEASES_DATASET`, `PRETRAINS_ON`.
- `method_disease_combo_gap`, `literature_impact_priority_matrix`, and `emerging_gap_opportunities` each expose binding / public-dataset annotations.
- Light score bumps when public (or any) bindings exist; **candidate membership unchanged**.
- Empty bindings → zero counts, empty lists, `actionability_hint=no_binding`; behavior otherwise identical to today.

## Non-goals

- Rewriting combo gaps with `COVERS_DISEASE`.
- Ranking opportunities primarily by `SURVEYS_METHOD`.
- Dedicated study-type relation UI / debug Cartesian hole UI.
- Fangxin REST (`disease_alias_dict`, `slide_annotation_ref`).
- Full-corpus re-extract / operational pilot gates.
- Changing Task-bridge admission rules for transferable candidates.

## Architecture

```text
paper_entity_bindings + entities.access_class
        │
        ▼
analysis/binding_enrichment.py
  enrich_method_disease_rows(rows)  # batch lookup by (method, disease) names
        │
        ├── tool_method_disease_combo_gap
        ├── tool_literature_impact_priority_matrix  (+ score bump)
        └── compute_emerging_gap_opportunities      (+ score bump)

tool_study_type_relation_stats ──► SQL_TOOLS + TOOL_SCHEMAS (+ idea visibility)
```

### Annotation fields (per method–disease row)

| Field | Type | Meaning |
|-------|------|---------|
| `binding_paper_cnt` | int | Distinct `source_pmid` in `paper_entity_bindings` for that method–disease pair |
| `public_dataset_names` | list[str] or comma-joined str for tables | Up to 5 Dataset names with `access_class='public'` on bindings |
| `public_dataset_cnt` | int | Length of above |
| `actionability_hint` | str | `public_data` \| `bound_no_public` \| `no_binding` |

Name resolution: join bindings to Method/Disease entities by `entities.name` matching the row’s `method` / `disease` strings (same strings tools already emit). Prefer one batched SQL over N+1.

### Score bumps (additive, small)

| Condition | Add to `gap_priority_score` / `opportunity_score` |
|-----------|--------------------------------------------------|
| `public_dataset_cnt > 0` | +0.5 |
| else `binding_paper_cnt > 0` | +0.25 |
| else | +0 |

Do **not** filter rows in or out based on bindings.

### Tool registry

- Add `"study_type_relation_stats": tool_study_type_relation_stats` to `SQL_TOOLS`.
- Add matching OpenAI-style schema in `TOOL_SCHEMAS` (no required params; optional `focus` only if already a pattern — default none).
- Ensure gap registry / idea agent surfaces that mirror gap SQL tools include the name (same path as other `SQL_TOOLS` entries).
- Optional one-line agent prompt note: QA counts for study-type-specific relations; survey/cover ≠ applied method / target disease.

### UI

- Where Streamlit already renders these tool results as dataframes, new keys appear as columns.
- If a view hard-codes column lists, append the annotation columns.
- No new tabs, captions beyond a short column header if needed.

## Module touchpoints

| Module | Change |
|--------|--------|
| `analysis/binding_enrichment.py` | **New** — batch enrich helper + hint helper |
| `analysis/gap_tools.py` | Register study-type tool; enrich combo + priority matrix |
| `analysis/weekly_hotspot.py` | Enrich transferable opportunity rows + score bump |
| `gap_agent.py` / `idea_agent.py` | Prompt note only if schemas alone are insufficient |
| `gap_ui.py` | Column lists only if hard-coded |
| `tests/` | Registry, enrichment fixture, score-membership invariants |

## Testing

1. Registry contains `study_type_relation_stats` in tools and schemas.
2. Fixture with method/disease/public dataset binding → enriched fields correct; without binding → `no_binding`.
3. Same candidate set before/after enrichment; scores increase only when bump conditions hold.
4. Existing combo / transferable / SQL registry tests remain green.

## Success criteria

- Agent-callable study-type relation counts.
- Combo, impact matrix, and transferable opportunities carry annotation fields; UI shows them.
- No bindings ⇒ empty annotations, unchanged ranking vs pre-bump baseline aside from new zero fields.
- Task-bridge admission and Cartesian generator membership unchanged.

## Round 2 (explicitly deferred)

- Combo rewrite using `COVERS_DISEASE`.
- Opportunity ranking using `SURVEYS_METHOD`.
- Dedicated UI for study-type relations / raw coverage holes.

## Related specs

- `2026-07-25-extraction-quality-design.md` — Phase 2 interfaces (now implemented as this MVP)
- `2026-07-28-study-type-prompt-policy-design.md` — deferred product features remain Round 2
- `2026-07-29-transferable-gap-task-quality-design.md` — Task-bridge remains primary opportunity narrative
