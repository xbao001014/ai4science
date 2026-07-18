# Visualization Tab: Focus Gaps × Fangxin Support

Date: 2026-07-18  
Status: Approved for planning  
Scope: `fulltext_workflow` Gap UI **Visualization** tab redesign

## Problem

The current Visualization tab (debate funnel, tool treemap, method×disease heatmap, lit×data scatter) does not give operators a clear decision view. Users need an intuitive side-by-side of:

1. Research gaps under the sidebar **focus**
2. Matching **Fangxin LIS** data support for those diseases

## Goals

- Independent of Gap Debate by default (focus + KG + landscape cache).
- If a debate report exists, overlay / prioritize matched gaps.
- One glance: pick a gap combo on the left → see Fangxin coverage on the right.
- Do not bootstrap LIS APIs from this tab (read cache only).

## Non-goals

- Replacing Data Feasibility (V-01/V-02, bootstrap, live API probes).
- Changing debate agents, combo/cross tool SQL, or disease mapper logic beyond reuse.
- New chart types beyond small subtype/molecular bars for the right panel.
- Auto-scanning the full corpus when focus is empty.

## UX Layout

Top → bottom:

1. **Focus summary strip** (4 metrics)
   - Combo count (after filters)
   - Literature-scarce count (`unexplored` / `minimal`)
   - Mapped Fangxin disease count
   - High data-support share (`data == high`)
2. **Two-column main area**
   - Left: opportunity table (selectable)
   - Right: Fangxin disease detail for the selected row
3. **Collapsed “Session diagnostics”**
   - Existing debate funnel + tool treemap (only meaningful after debate)

Empty / guidance states:

| Condition | Behavior |
|-----------|----------|
| No focus | Metrics zero + info to set sidebar focus; no full-corpus scan |
| Focus but empty KG combos | Prompt to run extract |
| Row selected, no landscape | Prompt to Bootstrap Landscape in Data Feasibility |
| Debate gaps unmatched | Info list under the table; do not invent fake combo rows |

## Left panel: opportunity table

### Row sources

- Primary: `tool_method_disease_combo_gap(focus=...)`.
- Optional overlay: parse gap titles from debate `report`; token-overlap match onto method/disease rows.

### Columns

| Column | Meaning |
|--------|---------|
| Source | `Corpus` or `Debate` (Debate wins when matched) |
| Method | Method entity |
| Disease | Disease entity (KG name) |
| Lit gap | `unexplored` / `minimal` / other |
| Papers | `paper_cnt` |
| Fangxin | Mapped `disease_id`, or `—` |
| Data | `high` (≥500 cases) / `medium` (≥200) / `low` / `none` (unmapped or no cache) |

### Sort (stable)

1. `Source == Debate` first  
2. Lit gap: unexplored → minimal → other  
3. Data: high → medium → low → none  
4. Papers ascending (scarcer first)  
5. Method, Disease alphabetical tie-break  

### Filters / selection

- Default: only `Lit gap ∈ {unexplored, minimal}`; checkbox “Show all coverage levels” for full set.
- Top-N slider: 10–50, default 30.
- Selection via Streamlit-friendly control (e.g. selectbox of unique row keys), default = first sorted row.
- Selection stored in `session_state["viz_selected_combo"]` and drives the right panel.

### Debate matching

- Tokenize gap titles; require ≥1 meaningful overlapping token with method and/or disease (stopwords excluded).
- Matched rows: `Source=Debate`; caption “N debate gaps matched”.
- Unmatched debate titles: listed under the table only.

## Right panel: Fangxin detail

### Inputs

- Selected row’s disease name + resolved `disease_id` (reuse `map_gap_to_disease` / catalog aliases if not pre-resolved).

### Data policy

- **Read-only** from `pathology_landscape` SQLite.
- No bootstrap / force-reload / live V1.1 fan-out from Visualization.

### Content (when cache hit)

1. Header: `disease_id`, ZH/EN names, Data badge, `updated_at`
2. Scale metrics (4): `total_cases`, WSI slides (or WSI cases), follow-up cases, molecular-labeled cases (from `sample_size` / `feasibility_pools`)
3. Subtype distribution: horizontal bar, top 8 from `v11.subtype_distribution`
4. Molecular positivity: bar or compact table, top 8 from `v11.molecular_positivity`
5. Caption pointing users to Data Feasibility → V-01 for deeper assessment

### Empty states

| Case | UI |
|------|-----|
| No selection | “Select a row on the left” |
| Name present, map fails | Show text + “Cannot map to Fangxin DiseaseCode” |
| `disease_id` without landscape | “No landscape cache for {id} — Bootstrap in Data Feasibility” |
| Landscape without v11 extras | Still show scale metrics; subtype/molecular captions |

Data badge thresholds must match the left-table Data column.

## Architecture

| Unit | Responsibility |
|------|----------------|
| `viz/gap_opportunity.py` (new) | Pure functions: build rows, sort, debate match, data tier, summary metrics; no Streamlit |
| `viz/gap_viz.py` | Keep funnel/treemap builders; add small plotly helpers for subtype/molecular bars |
| `gap_ui.render_gap_visualization_tab` | Rewrite to summary + two columns + diagnostics expander |

Reuse existing:

- `tool_method_disease_combo_gap`
- `map_gap_to_disease` / landscape catalog helpers already used in gap_ui
- `get_all_landscape` / payload fields already shown in Data Feasibility

## Error handling

- Missing plotly: left table still works; right charts fall back to `st.dataframe`.
- Combo/landscape errors: `st.warning` + empty panel; never crash the whole tab.
- Empty focus: no automatic unfiltered corpus query.

## Testing

New `tests/test_gap_opportunity.py`:

- Sort priority (Debate, lit gap, data, papers)
- Debate match → Source + unmatched list
- Data tier boundaries (0 / 199 / 200 / 500)
- Summary metric counts

Keep `tests/test_gap_viz.py` green (diagnostics builders unchanged in behavior).

## Docs

Update `fulltext_workflow/gap_ui_guide.md` §5.3 to describe the dual-pane opportunity view; move funnel/treemap under Session diagnostics.

## Success criteria

- With focus + extracted KG + landscape cache, Visualization is usable without running Gap Debate.
- After debate, matched gaps appear at the top of the left table and selection still drives Fangxin detail.
- Operators can answer: “For this focus, which scarce method×disease pairs have usable Fangxin cohorts?” without leaving the tab for the first-pass answer.
