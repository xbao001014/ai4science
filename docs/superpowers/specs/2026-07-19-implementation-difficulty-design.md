# Design: Proposal implementation difficulty (target + assessed)

**Date:** 2026-07-19  
**Status:** Approved for planning  
**Scope:** Gap UI target option, deterministic dual-axis scoring, idea-agent wiring, color annotation (no gate)  
**Related:** `2026-07-19-dataset-access-class-design.md` (Fangxin-first + `entities.access_class`); `analysis/impact_scoring.py` (q1/IF aggregates)

## Problem

Research proposal generation has Fangxin `feasibility_score` and Critic `technical_feasibility`, but no explicit **implementation difficulty** that users can target and that the system can assess. Journal quartile/IF is now in DB and should inform the research-contribution side of difficulty. Data-side difficulty should combine **Fangxin (primary)** with **public literature datasets** (`access_class=public`), without treating private/unknown corpora as deployable sources.

## Goals

1. User selects `target_difficulty ∈ {easy, moderate, hard}` before generating a proposal.
2. System computes `assessed_difficulty` on the same three-level scale via deterministic rules.
3. UI (and proposal header text) show both values with **salient color** for alignment / mismatch; **do not** block generation or Critic `accept` on mismatch.
4. `research_bar` uses supporting-paper quartile / IF; `engineering_bar` uses Fangxin feasibility first, with optional one-tier relief from related public datasets.
5. Reuse existing Dataset `access_class` extraction (re-extract will refresh labels; no new extractor schema in this feature).

## Non-goals

- No Critic reject / forced revision solely due to `difficulty_delta`.
- No five-level or continuous difficulty in the UI (internal ordinals OK).
- No ISSN/IF matching fixes in this work (low coverage → `q_coverage_low` badge only).
- Do not count `private` / `unknown` literature datasets as public relief.
- Do not replace Fangxin with public data when Fangxin is feasible (existing proposal rules remain).

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Product shape | Target select + auto assess (option C) |
| Meaning of difficulty | Composite: research contribution bar + engineering landing (option C) |
| Scale | Three levels: `easy` / `moderate` / `hard` |
| Mismatch policy | Annotate only; color-coded; no gate |
| Scoring approach | Deterministic dual-axis + `max()` combine (Approach 1) |
| Data for engineering | Fangxin primary + public `access_class` relief |
| Who computes assessed | Host module, not LLM self-score |

## Levels and colors

Ordinal: `easy=0`, `moderate=1`, `hard=2`.

| Field | Values |
|-------|--------|
| `target_difficulty` | user select |
| `assessed_difficulty` | `max(research_bar, engineering_bar)` |
| `difficulty_delta` | `ord(assessed) - ord(target)` ∈ {-2…+2} |

| Condition | Color |
|-----------|--------|
| `delta == 0` | green — aligned |
| `\|delta\| == 1` | amber — slight mismatch |
| `\|delta\| == 2` | red — strong mismatch |
| `q_coverage < 0.4` | extra gray badge `Q coverage low` (does not change the three-level color) |

Display: side-by-side pills `Target: …` / `Assessed: …` plus one-line breakdown, e.g.  
`research=hard (Q1 72%) · engineering=moderate (Fangxin 0.81 + public: Camelyon17)`.

## Scoring

### Inputs

- Supporting paper set `S`: prefer gap-linked PMIDs from KG analysis / hotspot evidence for the selected gap; if empty, fall back to papers returned by the same keyword tools the Designer already uses for the gap topic. Each row needs `quartile` / `impact_factor` when available (missing allowed).
- Fangxin: `feasibility_score`, `available_cohort_size` from existing `feasibility_assess`.
- Public datasets: from `datasets_for_topic` (or equivalent) filtered to `COALESCE(access_class,'unknown')='public'` for the gap keyword (refreshed by planned re-extract).

### A. `research_bar` (literature / contribution ceiling)

Reuse aggregates in the spirit of `aggregate_paper_impact`:
- `q1_ratio`, `avg_if` over papers in `S` that have usable IF/Q.
- `q_coverage = |papers with valid quartile| / |S|`.
- Preprints / proceedings do not count as Q1; papers without IF are excluded from `avg_if` mean (not imputed).

| Condition | `research_bar` |
|-----------|----------------|
| `q1_ratio ≥ 0.55` OR `avg_if ≥ 8` | `hard` |
| `q1_ratio ≥ 0.25` OR `avg_if ≥ 3` | `moderate` |
| else (including mostly missing Q) | `easy` |

Thresholds are config constants (tunable). If `q_coverage < 0.4`, set `q_coverage_low=true`.

### B. `engineering_bar` (landing difficulty)

**Fangxin tier** (`fangxin_tier`):

| Condition | Tier |
|-----------|------|
| `feasibility_score ≥ 0.8` AND cohort ≥ 500 | `easy` |
| `feasibility_score ≥ 0.5` OR cohort ≥ 200 | `moderate` |
| else | `hard` |

**Public relief** (only if `fangxin_tier != easy`):
- If ≥1 topic-related `public` dataset exists → lower engineering by **one** tier (`hard→moderate`, `moderate→easy`).
- Record `relies_on_public: [names]` in breakdown.
- `private` / `unknown` do not grant relief.
- Proposal rules unchanged: label public datasets; Fangxin remains primary when feasible.

`engineering_bar = apply_public_relief(fangxin_tier)`.

### C. Combine

```
assessed_difficulty = max(research_bar, engineering_bar)
```

## Integration

### Gap UI

- Selectbox `Target difficulty` next to Generate (default `moderate`).
- Pass `target_difficulty` into `stream_idea_agent`.
- On completion, render dual pills + breakdown from `difficulty_assessed` event / final payload.

### Module

- New: `analysis/difficulty_scoring.py` (pure functions + unit tests).
- Emit event `type: difficulty_assessed` after feasibility + paper/dataset context are available (final round preferred; may refresh each draft if cheap).

### Designer

- Inject `target_difficulty` and short steering text (easy → landable methods / mid-tier evidence; hard → may align with high-Q1 methods but Fangxin-first + labeled public only).
- Keep calling `feasibility_assess` and `datasets_for_topic`.
- Do **not** require LLM to invent `assessed_difficulty`.

### Critic

- Host may attach `target_difficulty`, `assessed_difficulty`, `difficulty_delta` into review payload for display.
- Existing gates (`feasibility_score`, Fangxin-first, public labeling) unchanged.
- **No** accept/reject rule on `difficulty_delta`.

### Persistence

- Store on proposal/ops record: `target_difficulty`, `assessed_difficulty`, `difficulty_delta`, `difficulty_breakdown_json`.
- Markdown header line with textual difficulty summary (colors live in UI).

## Extractor / rollout note

Dataset `access_class` comes from the existing extract pipeline. **Re-extract will run subsequently** to refresh Dataset labels before or as this feature is used in production. This design does not add extractor fields; engineering public-relief quality depends on that re-extract.

IF/quartile coverage gaps (e.g. unmatched MDPI / Nat Commun) only affect `q_coverage` / research aggregates; fix matching separately if needed.

## Testing

- Unit: research_bar thresholds; fangxin_tier; public relief ±1; `max` combine; delta/color mapping; missing Q → easy + `q_coverage_low`.
- Unit: private/unknown datasets do not relieve; public list appears in breakdown.
- UI/agent smoke (optional): selectbox passed through; event present; pills render for delta 0/1/2.

## Rollout

1. `difficulty_scoring.py` + tests.
2. Wire `stream_idea_agent` + Gap UI selectbox + color pills.
3. Persist breakdown on proposals.
4. Rely on planned **re-extract** for robust `access_class` public relief; until then relief may be sparse/`unknown`-heavy.
