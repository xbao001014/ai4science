# Feasibility: Temporary WSI → Annotation Assumption

**Date:** 2026-08-06  
**Status:** Implemented  
**Scope:** `feasibility/assessment.py`, `analysis/feasibility_tools.py`, `config.py`, `idea_agent.py` (Generator/Critic prompts), `gap_ui.py` (V-01 render), related tests  
**Related:** Does **not** rewrite landscape pools; sits on top of `2026-08-04-feasibility-api-faithful-pools-design.md` as an assess-time relief valve until Fangxin exposes real ROI/annotation REST.

## Problem

API-faithful pools correctly report sparse/zero annotation counts (e.g. `C_XR` `has_tumor_region=0`). Hypotheses that require any `required_annotations` collapse to `feasibility_score=0` / `INSUFFICIENT`, so Idea Critic reject rates and proposal difficulty stay depressed even when WSI volume is large. Fangxin will improve annotation APIs later; until then, scoring needs a temporary, disclosed assumption.

## Decisions

| Item | Choice |
|------|--------|
| Scope of assumption | All items in `required_annotations` (option C) |
| Assumed count | Always `has_wsi` when `has_wsi > 0` (option A) — not ratio floor; not “only when observed==0” |
| Where applied | Assess-time only (approach 1); landscape cache stays observed |
| Report disclosure | Split observed vs assumed lists (option B) |
| Molecular / survival / follow-up | Unchanged (no WSI assumption) |
| Feature flag | `FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI` default `True` |

## Principles

1. Landscape / pool JSON remain API observations; do not write assumed counts into `pathology_landscape`.
2. Scoring may use assumed annotation counts only when the flag is on and `has_wsi > 0`.
3. Callers (Idea proposal §9, Critic verification, Gap UI) must always see which annotations were **observed** vs **assumed_from_wsi**.
4. Assumed annotations must not be phrased as “API-verified”; Critic must not reject solely because assumptions exist.
5. Turning the flag off restores pure API-faithful annotation `min` behavior without bootstrap.

## Assessment behavior

In `assess_feasibility_from_pools`, for each `req.required_annotations` entry when the flag is on and `has_wsi > 0`:

1. Resolve pool key via existing `_ANNOTATION_POOL_KEYS` (unknown names → `has_{ann}`).
2. `raw = int(pools[key])` if present else `0`.
3. `effective = has_wsi`.
4. `cohort = min(cohort, effective)`; `breakdown[has_{ann}] = effective`.
5. Classify:
   - `raw > 0` → `annotation_assumption.observed`
   - `raw == 0` → `annotation_assumption.assumed_from_wsi`
6. Record `raw_observed[ann] = raw` and `assumed_count = has_wsi`.

When flag is off: keep current API-faithful path (`effective = raw`, zero tightens cohort).

`required_labels` without a pool / survival-follow-up keys still go to `unverified_requirements` and do not get WSI assumption. Labels normalized into annotations (TNM/grade) follow the annotation path above.

## Response contract

`feasibility_assess` / assessment JSON adds:

```json
"annotation_assumption": {
  "observed": ["tnm_stage"],
  "assumed_from_wsi": ["tumor_region"],
  "raw_observed": {"tnm_stage": 1, "tumor_region": 0},
  "assumed_count": 12066
}
```

Empty / `null` when flag off, no annotation requirements, or `has_wsi == 0`.

`note` may briefly mention assumed annotations; structured field is the source of truth.

## Idea / Proposal / UI

- **Generator §9**: after `required_annotations`, require two bullets:
  - 标注（接口实测）: …
  - 标注（有 WSI 临时假定）: …
- **Critic**: if `assumed_from_wsi` non-empty, `data_feasibility_verification` must name them; do not treat assumptions as verified API coverage; do not force `accept=false` only because assumptions exist.
- **Gap UI** V-01: under 样本分解, show `annotation_assumption` (observed / assumed_from_wsi / raw_observed). Landscape panel continues to show observed pools.

## Tests

- Flag on + `has_wsi=N` + required `tumor_region` with raw 0 → `available_cohort_size=N`, score 1.0 (given no other tighteners), `assumed_from_wsi` contains `tumor_region`.
- Flag on + raw TNM=1 → effective=`has_wsi`, item listed under `observed`, `raw_observed.tnm_stage=1`.
- Flag off + raw 0 → cohort 0 / score 0 (faithful).
- Survival/follow-up still unverifiable; molecular still uses observed pools only.
- Prompt/contract smoke: tool result includes `annotation_assumption` shape.

## Out of scope

- Writing assumed values into landscape bootstrap
- Assuming molecular markers or survival/follow-up from WSI
- Changing Critic numeric accept thresholds
- Paginating patient lists or new Fangxin annotation endpoints
- Auto-disabling the flag when `slide_annotation_ref` appears (manual flag for now)

## Success criteria

- Polyp / ROI-style ideas with WSI-rich disease codes (e.g. `C_XR`) no longer score `INSUFFICIENT` solely for missing annotation pools.
- Final proposals and V-01 UI clearly separate 实测 vs 临时假定 annotations.
- `FEASIBILITY_ASSUME_ANNOTATIONS_FROM_WSI=False` restores 2026-08-04 behavior without re-bootstrap.
