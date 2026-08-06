# API-Faithful Feasibility Pools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make V-01 feasibility pools and assessment use only Fangxin API observations (no ratio estimates or optimistic floors), expose unverifiable requirements and patient-list coverage.

**Architecture:** `landscape_builder` writes observed pools + provenance metadata; `assessment` starts from `cohort_base`, mins only verifiable keys, lists unverifiable requirements; UI/tools surface the new fields. Scoring follow-ups are out of scope (see scoring-impact spec).

**Tech Stack:** Python 3, pytest, existing Fangxin HTTP client / SQLite landscape cache

**Spec:** `docs/superpowers/specs/2026-08-04-feasibility-api-faithful-pools-design.md`

## Global Constraints

- No `patient_count * ratio` estimates for survival/follow-up
- No `_pool_count_with_floor` / assess-time floors
- `cohort_base` = hospital `PatientCount` sum; do not overwrite with `list_patients` length
- Unverifiable requirements do not participate in `min`; do not force recommendation demotion
- Keep label→annotation normalization in `feasibility_tools`
- Do not change Critic accept thresholds / `fangxin_tier` in this plan

## File map

| File | Role |
|------|------|
| `fulltext_workflow/feasibility/landscape_builder.py` | Observed pools, provenance, coverage |
| `fulltext_workflow/feasibility/assessment.py` | Unverifiable-aware assess |
| `fulltext_workflow/feasibility/client.py` | Persist provenance/coverage on landscape entry |
| `fulltext_workflow/gap_ui.py` | Show unverified + coverage |
| `fulltext_workflow/idea_agent.py` | One Critic prompt line |
| `fulltext_workflow/tests/test_landscape_tumor_region_fallback.py` | Rewrite for observed-only |
| `fulltext_workflow/tests/test_feasibility_sparse_annotation_floor.py` | Rewrite for unverifiable / raw TNM |

---

### Task 1: Landscape pools — observed only

**Files:**
- Modify: `fulltext_workflow/feasibility/landscape_builder.py`
- Modify: `fulltext_workflow/tests/test_landscape_tumor_region_fallback.py`
- Modify: `fulltext_workflow/feasibility/client.py` (persist metadata)

**Interfaces:**
- Produces: `build_feasibility_pools(...) -> { pools, pool_provenance, patient_list_coverage, cohort_base, stats, ... }`
- `pools` ints only for observed keys; no `has_survival_label` / `meets_followup_*` numeric estimates

- [ ] **Step 1: Rewrite landscape tests (fail under old floors)**

Replace floor assertions with observed-only expectations (see test file rewrite in implementation).

- [ ] **Step 2: Run tests — expect FAIL**

```
../.venv/Scripts/python.exe -m pytest tests/test_landscape_tumor_region_fallback.py -v
```

- [ ] **Step 3: Implement `build_feasibility_pools`**

- `cohort_base = stats["patient_count"]` (do not `max` with list length for base)
- `has_wsi = cohort_base if slide_count > 0 else 0`
- Annotation/molecular = raw `len(matched)`
- Omit estimate keys; set `pool_provenance` for unverifiable survival/follow-up keys
- `patient_list_coverage = {enumerated, catalog_total}`
- Remove `_pool_count_with_floor`
- `infer_tasks` / `infer_followup`: only emit when observed keys present

- [ ] **Step 4: Persist on landscape entry in `client.build_landscape_entry`**

Add `pool_provenance`, `patient_list_coverage` next to `feasibility_pools`.

- [ ] **Step 5: Run landscape tests — PASS**

---

### Task 2: Assessment — unverifiable + no floors

**Files:**
- Modify: `fulltext_workflow/feasibility/assessment.py`
- Modify: `fulltext_workflow/tests/test_feasibility_sparse_annotation_floor.py`

**Interfaces:**
- Produces: `assess_feasibility_from_pools` adds `cohort_base`, `unverified_requirements`, `patient_list_coverage`
- Estimate-only keys always unverifiable even if stale cache has numbers: `has_survival_label`, `has_death_event`, `meets_followup_*`, `all_survival_no_msi`, `all_survival_tnm_no_msi`

- [ ] **Step 1: Rewrite assessment tests**

- Sparse TNM=1 → cohort 1, score tiny; no floor uplift
- Required OS + follow-up with stale estimate keys in pools → unverified list; cohort not shrunk by those keys
- Keep `test_normalize_moves_tnm_and_grade_out_of_labels`

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement assessment**

- Remove `_POOL_FLOOR_RATIOS` flooring in `_pool_get`
- Start cohort from `cohort_base` or fallback `has_wsi`
- Verifiable vs unverifiable branching
- Skip `all_survival_no_msi` shortcut unless provenance says observed (default: skip / treat unverifiable)
- Update `note` when unverified non-empty

- [ ] **Step 4: Run assessment + related feasibility tests**

```
../.venv/Scripts/python.exe -m pytest tests/test_feasibility_sparse_annotation_floor.py tests/test_feasibility.py -v
```

Fix any regressions that assumed estimates/floors.

---

### Task 3: UI + Critic prompt line

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`render_feasibility_result` / 样本分解)
- Modify: `fulltext_workflow/idea_agent.py` (CRITIC prompt)

- [ ] **Step 1:** After breakdown table, show `unverified_requirements` and `patient_list_coverage`
- [ ] **Step 2:** Add Critic line: do not treat unverified requirements as satisfied; do not invent cohort sizes
- [ ] **Step 3:** Run focused pytest suite above again

---

### Task 4: Spec status

- [ ] Mark design status Implemented in `2026-08-04-feasibility-api-faithful-pools-design.md`

**Commits:** only if user requests; otherwise leave working tree for review.
