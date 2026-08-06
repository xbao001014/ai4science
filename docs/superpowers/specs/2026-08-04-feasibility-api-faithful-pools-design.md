# Feasibility: API-Faithful Pools (No Estimates)

**Date:** 2026-08-04  
**Status:** Implemented  
**Scope:** `feasibility/landscape_builder.py`, `feasibility/assessment.py`, `feasibility/client.py`, `analysis/feasibility_tools.py`, `gap_ui.py` (样本分解), related tests  
**Supersedes (optimistic floors only):** `2026-08-03-tumor-region-pool-fallback-design.md`  
**Scoring impact (Idea Critic + Proposal difficulty):** `2026-08-04-feasibility-faithful-pools-scoring-impact.md`  
**Plan:** `docs/superpowers/plans/2026-08-04-feasibility-api-faithful-pools.md`

## Problem

V-01 pools mixed Fangxin API observations with hard-coded ratios (`patient_count × 0.85` survival, `×0.75` follow-up, etc.) and optimistic floors for sparse annotations. UI breakdowns (e.g. C_CA `has_overall_survival_months=2302` vs `has_wsi=560`) looked like interface facts but were estimates. That is not faithful to the API.

Separately, `catalog.total_cases` (sum of hospital `PatientCount`) and `list_patients` length are **two endpoints**, not a dedup pipeline. Defensive `set(PatientId)` only dedups within one patients response.

## Decisions

| Item | Choice |
|------|--------|
| Overall mode | Observed-first + explicit gaps (option B) |
| Unverifiable requirements | Do not shrink `min`; list in `unverified_requirements` (option A) |
| Cohort base | Hospital `PatientCount` sum as `cohort_base` (option A) |
| Implementation style | Minimal change: drop ratios/floors; expose coverage metadata (approach 1) |
| Recommendation gate | Unchanged thresholds; unverified items do **not** force demotion |

## Principles

1. Numeric pool values used in `available_cohort_size` / `feasibility_score` must be API-derived observations (or deterministic intersections of API rows), never ratio estimates or floors.
2. Missing API capability → mark unverifiable; never invent counts.
3. `cohort_base` = `sum(PatientCount)` from `/diseases/sample-count-by-hospital`.
4. Patient list is a **sample scope** for attribute/molecular matching; expose `patient_list_coverage`, do not overwrite `cohort_base` with list length.
5. Label→annotation normalization (TNM/grade out of `required_labels`) remains; only optimistic floors are removed.

## Architecture

Unchanged pipeline skeleton:

```
Fangxin API → landscape_builder pools → pathology_landscape (SQLite)
→ feasibility_assess → assess_feasibility_from_pools → gap_ui / idea_agent
```

Semantic change: pools and assessment no longer invent survival/follow-up/annotation floors.

## Pool construction (`landscape_builder`)

| Key | Source | Notes |
|-----|--------|-------|
| `cohort_base` | `aggregate_hospital_stats(...).patient_count` | Assessment denominator and start cohort |
| `enumerated_patients` | Unique `PatientId` count from `list_patients` | Metadata only |
| `has_wsi` | If `slide_count > 0`, set equal to `cohort_base`; else 0 / omit | Do **not** set `has_wsi = len(patient_ids)` |
| `has_tnm_stage`, `has_who_grade`, `has_tumor_region`, `lauren` / stage III–IV | Keyword match on attributes ∩ enumerated patient set | Raw observed counts; **no** `_pool_count_with_floor` |
| Molecular `has_*` | Molecular list endpoints ∩ enumerated patients | Observed |
| `has_survival_label`, `has_death_event`, `meets_followup_*`, `all_survival_no_msi`, … | **Do not write numeric estimates** | Provenance `unverifiable` (omit key or `null` + provenance map) |

Also persist:

- `pool_provenance`: map of pool key → `observed` \| `unverifiable`
- `patient_list_coverage`: `{ "enumerated": N, "catalog_total": cohort_base }`

Remove `_pool_count_with_floor` usage (and the helper if unused).

`infer_tasks` / catalog `label_completeness` that currently divide estimated survival by total must not present estimates as coverage; prefer omit, 0 with provenance, or only observed-backed fields.

## Assessment (`assessment`)

1. Start: `cohort = cohort_base` (if missing in old cache, fall back to `has_wsi` and note compatibility).
2. For each **verifiable** required label / annotation / marker / stage filter: `cohort = min(cohort, observed)`.
3. For each **unverifiable** requirement: append to `unverified_requirements`; **do not** `min`.
4. `available_cohort_size = cohort` (observed intersection only).
5. `feasibility_score = round(cohort / max(cohort_base, 1), 2)` clamped to \[0, 1\].
6. `breakdown`: integer counts for observed keys; omit or `null` for unverifiable; always include `all_criteria_met` = observed intersection; document in `note` that unmet unverified requirements are listed separately.
7. Delete assess-time `_POOL_FLOOR_RATIOS` / `_pool_get` floor behavior; reading a pool key returns the raw int (or default when key absent for optional paths).

Survival-without-MSI shortcut: only apply if the shortcut pool key is **observed**; if it was previously an estimate, remove or treat as unverifiable (do not invent `all_survival_no_msi`).

## Tool / UI / Agent contract

`feasibility_assess` (and assessment JSON) add:

- `cohort_base`
- `unverified_requirements`: list of strings (field names or requirement tokens)
- `patient_list_coverage`: `{enumerated, catalog_total}`

UI「样本分解」:

- Table: observed counts only
- Adjacent: unverified list + coverage ratio text

Idea / Critic prompts: one line — do not treat unverified requirements as satisfied; do not invent cohort sizes.

## Migration

- Old landscape rows may contain estimated survival/follow-up and floored annotation counts.
- Assessment: no floors. For known estimate-only keys (`has_survival_label`, `meets_followup_*`, …), treat as unverifiable even if a number is present in cache (prefer not trusting stale estimates).
- Recommend `bootstrap --force` to rebuild landscapes after deploy.
- Mark `2026-08-03-tumor-region-pool-fallback-design.md` status as **Superseded** for floor parts; keep field-normalization intent as still valid under this spec.

## Tests

- Replace sparse-floor tests: observed TNM=1 with required TNM → cohort/`min` reflects 1, not floored uplift.
- Required OS / follow-up with no API → appears in `unverified_requirements`; does not force cohort to 0 by itself.
- `cohort_base` from hospital sum; `enumerated_patients` / coverage reported; `has_wsi` not overwritten by list length when slides exist.
- Update landscape tumor-region fallback tests to assert raw observed (or 0), not floor ratios.

## Out of scope

- Paginating `/diseases/patients` to full catalog
- New Fangxin follow-up/survival count APIs
- V-03 public dataset channel
- Changing `FEASIBLE` / `MARGINAL` numeric thresholds

## Success criteria

- C_CA-style breakdown no longer shows ~2302 survival / ~2031 follow-up from ratios.
- Requiring only WSI (+ any observed annotations) uses hospital `cohort_base` as start; sparse observed annotations genuinely tighten via `min`.
- Requiring survival/follow-up yields explicit `unverified_requirements` without fabricated counts in `available_cohort_size`.
