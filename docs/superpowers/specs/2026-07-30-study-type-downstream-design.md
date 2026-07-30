# Study-Type Downstream Signals Design — 2026-07-30

**Status:** Approved for implementation planning  
**Scope:** Round 2 after Binding Actionability MVP — dual-channel combo gaps via `COVERS_DISEASE`, secondary sort via `SURVEYS_METHOD`, UI columns only.  
**Related:** `2026-07-28-study-type-prompt-policy-design.md` (deferred product items); `2026-07-30-binding-actionability-mvp-design.md` (Round 1).

## Problem

Study-type relations (`SURVEYS_METHOD`, `COVERS_DISEASE`, …) are extracted and QA-countable, but combo / priority / transferable surfaces still treat disease coverage and method survey edges as invisible. Round 1 annotated bindings without using these study-type signals.

## Decisions

| Topic | Choice |
|-------|--------|
| Delivery | Product logic + UI columns; no new tabs |
| `COVERS_DISEASE` | Dual channel: keep APPLIES×TARGETS applied gaps; add covered-only candidates with `gap_kind` |
| `SURVEYS_METHOD` | Secondary sort key only — do not change primary scores or Method heat |
| UI | Extra columns on existing tables |

## Goals

- `method_disease_combo_gap` returns applied + covered rows, clearly labeled.
- Priority matrix and transferable opportunities expose `surveys_method_paper_cnt` (and covers counts where applicable) and sort by primary score, then survey count descending.
- Method heat remains `APPLIES_METHOD` only.
- Agents and UI can distinguish covered ≠ applied and survey ≠ applied method.

## Non-goals

- New Streamlit tabs or dedicated study-type pages.
- Mixing `COVERS_DISEASE` into Method×Disease heat / Cartesian disease Top-N for the applied channel.
- Adding survey counts into `opportunity_score` / `gap_priority_score` / binding bumps.
- Changing Task-bridge admission for transferable candidates.
- Finishing leftover `idea_agent` SQL commit hygiene (separate unless requested).

## Architecture

```text
study_type_signals.py
  batch surveys_method_paper_cnt by method name
  batch covers_disease_paper_cnt by disease name
  build covered-channel gap pairs
        │
        ├── tool_method_disease_combo_gap  (applied + covered, truncate ≤40)
        ├── tool_literature_impact_priority_matrix  (secondary sort)
        └── compute_emerging_gap_opportunities      (secondary sort)
```

### Fields

| Field | Meaning |
|-------|---------|
| `gap_kind` | `applied` \| `covered` (transferable rows: `applied` or omit — prefer set to `applied`) |
| `covers_disease_paper_cnt` | Distinct papers with active `COVERS_DISEASE` → that disease |
| `surveys_method_paper_cnt` | Distinct papers with active `SURVEYS_METHOD` → that method |

Round 1 binding fields and score bumps remain unchanged and apply after study-type annotation (or in either order, as long as bumps stay on primary scores only).

### Applied channel (unchanged membership)

- Hot methods: Top-N by `APPLIES_METHOD`.
- Hot diseases: Top-N by `TARGETS_DISEASE` (focus-aware as today).
- Gaps: co-occurrence 0 → `unexplored`; ≤2 → `minimal`.
- Set `gap_kind=applied`.

### Covered channel

- Methods: same hot APPLIES Top-N as applied.
- Diseases: Top-N by active `COVERS_DISEASE` counts (focus-aware when focus filters diseases).
- Include pair only if APPLIES×TARGETS co-occurrence for that pair is **0**.
- Require `covers_disease_paper_cnt ≥ 1` for the disease.
- Set `gap_kind=covered`, `gap=unexplored`, `paper_cnt=0`.
- Skip pairs already present in the applied gap list.

### Truncation

1. Build full applied list (enriched).
2. Build covered list (enriched), excluding applied pairs.
3. Emit `applied[:40]` then fill remaining slots with covered until total length ≤ 40.

### Secondary sort

After primary scores (including Round 1 binding bumps):

- Transferable: `sort(key=(-opportunity_score, -surveys_method_paper_cnt))`
- Priority matrix: `sort(key=(-gap_priority_score, -surveys_method_paper_cnt))`
- Combo applied block: optional secondary by `-surveys_method_paper_cnt`
- Combo covered block: sort by `(-covers_disease_paper_cnt, -surveys_method_paper_cnt)` before append

Primary numeric scores must not incorporate survey counts.

### UI

- Append columns: `gap_kind`, `covers_disease_paper_cnt`, `surveys_method_paper_cnt` where combo / opportunities / matrix tables hard-code columns (`opp_cols` and any curated combo frames).
- Generic `st.dataframe` tool views pick up keys automatically.
- No new tabs.

### Agent copy

One-line guidance: covered channel is review/coverage mention via `COVERS_DISEASE`, not applied target co-occurrence; `SURVEYS_METHOD` is survey mention, not `APPLIES_METHOD` heat.

## Module touchpoints

| Module | Change |
|--------|--------|
| `analysis/study_type_signals.py` | **New** — batch counters + covered pair builder helpers |
| `analysis/gap_tools.py` | Dual-channel combo; annotate + secondary sort on matrix |
| `analysis/weekly_hotspot.py` | Annotate + secondary sort on transferable rows |
| `gap_ui.py` | Column lists |
| `gap_agent.py` | Prompt bullet |
| `tests/test_study_type_downstream.py` | Dual channel, sort, regression |

## Testing

1. Covered appears when COVERS exists and applied co-occurrence is 0; absent when applied co-occurrence > 0.
2. Applied gaps still labeled `gap_kind=applied` with prior semantics.
3. Equal primary scores → higher `surveys_method_paper_cnt` ranks first; unequal primary scores → primary wins.
4. Binding bump behavior unchanged.
5. Method heat tools still ignore `SURVEYS_METHOD`.

## Success criteria

- Combo returns merged applied+covered list ≤40 with stable labeling.
- Priority and transferable sorts use survey as secondary key only.
- UI shows the three new columns on relevant tables.
- No new tabs; Method heat unchanged.

## Explicitly still deferred

- Dedicated study-type relation explorer UI.
- Using `SURVEYS_METHOD` inside primary opportunity/priority formulas.
- Rewriting transferable admission around cover edges.
