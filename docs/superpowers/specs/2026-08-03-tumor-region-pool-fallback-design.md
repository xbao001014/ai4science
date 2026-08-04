# Feasibility: Optimistic Annotation Pool Fallback

**Date:** 2026-08-03  
**Status:** Superseded (optimistic floors) — see `2026-08-04-feasibility-api-faithful-pools-design.md`. Field normalization (TNM/grade out of labels) remains valid under the new spec.  
**Scope:** `feasibility/landscape_builder.py`, `feasibility/assessment.py`, `analysis/feasibility_tools.py`

## Problem

Fangxin catalog diseases are well-resourced, but attribute APIs often under-report annotations (0 or a handful of keyword hits). Example: C_CA had `has_tnm_stage=1` / `has_tumor_region=0`, so requiring TNM or region collapsed `feasibility_score` to ~0. Models also put `tnm_stage` / `histological_grade` under `required_labels`, which hit the sparse TNM pool key directly.

## Approach

1. Pool build: `_pool_count_with_floor(observed, patient_count, ratio)` — if observed &lt; max(10, 5% of patients), use `max(observed, patient_count * ratio)` for TNM / grade / tumor_region / stage III–IV.
2. Assess-time floor on the same keys so **already-cached** landscapes benefit without immediate `--force` bootstrap.
3. Normalize: move clinical staging/grade fields from labels → annotations; alias DFS / survival_status → survival/death labels.
4. Survival-without-MSI shortcut uses `min(cohort, alt)` instead of replacing cohort.

## Result (C_CA example params)

Before: sparse `has_tnm_stage=1` → score ~0 when TNM is required.  
After: floored TNM/grade → score ~0.85, cohort ~476 (same request).
