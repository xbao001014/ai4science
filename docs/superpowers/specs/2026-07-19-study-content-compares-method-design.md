# Design: Study-content extraction + COMPARES_METHOD

**Date:** 2026-07-19  
**Status:** Approved for implementation (pending user review of this file)  
**Scope:** `fulltext_workflow` extractor (prompt + Pydantic + postprocess + docs/tests)

## Problem

Extraction currently leans on “mentioned in text” plus Method granularity filters. Background / related-work mentions (methods, diseases, modalities) still enter the KG as if they were this paper’s study content. Baselines that are experimentally compared are mixed into `APPLIES_METHOD` with contribution methods.

## Goals

1. Prefer **this paper’s research content** for all Paper→X relations (Disease, Method, Task, Modality, Dataset, Metric, Limitation).
2. Split Method edges into two columns:
   - `APPLIES_METHOD` — proposed / adopted core methods
   - `COMPARES_METHOD` — explicit baselines / comparison methods that participate in this paper’s experiments
3. Drop methods that are only cited (related work) with no experimental role here.

## Non-goals

- No new DB column (`role`); no schema migration (relation name is enough).
- No second relation type for Disease/Task “background vs study”.
- No large gap_ui / agent redesign in this change (gap agents keep using `APPLIES_METHOD` as primary Method signal).

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Coverage | Option C: all Paper→X study-content filtering |
| Baselines | Separate relation `COMPARES_METHOD` → Method |
| Conflict | Same Method on both relations → keep `APPLIES_METHOD`, drop `COMPARES_METHOD` |
| Repair | Object-type repair still maps Method → `APPLIES_METHOD` by default; never auto-promote to `COMPARES_METHOD` |

## Study-content policy (prompt)

Add a global rule to `_BASE_SYSTEM`:

- Extract only facts about **this paper’s own study**: cohort, tasks performed, methods used or proposed, modalities/datasets used, metrics reported, limitations stated by authors.
- Do **not** extract background-only mentions from related work, field surveys, or illustrative examples that are not this study’s objects.

Per type:

| Type / relation | Keep | Drop |
|-----------------|------|------|
| `APPLIES_METHOD` | Proposed model/module; backbone adopted in this pipeline | Citation-only; experimental baselines → use `COMPARES_METHOD` |
| `COMPARES_METHOD` | Explicit baseline / compared-against / outperformed **and** used in this paper’s comparison | Name-drop without experiment |
| Disease | Study cohort / experimental disease targets | Other cancers only as examples in intro |
| Task / Modality / Dataset | This paper’s task and data | Other tasks/modalities only surveyed |
| Metric / Limitation | Reported metrics; author-stated limitations | Generic field complaints |

Section hints:

- `introduction` / `discussion` / `future_work`: keep existing ban on `APPLIES_METHOD`; do **not** emit `COMPARES_METHOD` unless the section clearly reports this paper’s experimental comparison (normally methods/results).
- `methods` / `results` / `abstract`: primary sources for both Method relations and study Disease/Task/Modality/Dataset.

JSON examples must include at least one `COMPARES_METHOD` example and state `metric_value` as string.

## Schema / validation

- Extend `RelationLiteral` with `COMPARES_METHOD`.
- Extend relation→object map: `COMPARES_METHOD` → `Method`.
- Object→relation default for Method remains `APPLIES_METHOD` (repair path).
- Existing Paper-subject / numeric `metric_value` coercion stays unchanged.

No SQLite migration: `relations.relation` is free text.

## Postprocess (`entity_normalize.py`)

1. Apply the same Method quality filters (generic / low-value) to both `APPLIES_METHOD` and `COMPARES_METHOD`.
2. Optionally extend `_NO_APPLIES_METHOD_SECTIONS` logic: drop `COMPARES_METHOD` from `introduction` / `discussion` / `future_work` (same section set), unless we later relax for results-like discussion—**default: same ban set**.
3. After filtering, if the same normalized Method name appears under both relations in the batch, remove the `COMPARES_METHOD` triple(s).
4. Do not invent `COMPARES_METHOD` in `repair_triple_relation`.

## Downstream

| Consumer | Change |
|----------|--------|
| `scripts/compare_extraction_quality.py` | Report top Methods for both relations |
| Gap / idea agents | Unchanged this round (still key off contribution methods) |
| Tests | New cases for `COMPARES_METHOD`, conflict preference, section ban |
| `extractor/GRANULARITY.md` | Document study-content policy + new relation |

## Testing

- Unit: validate `COMPARES_METHOD` triples; conflict drop; section drop; Method filters apply to both.
- Manual smoke (optional): one abstract with “we propose X and compare against Y” → one `APPLIES_METHOD` + one `COMPARES_METHOD`.

## Rollout

- Code + tests + GRANULARITY update.
- Existing DB rows keep old `APPLIES_METHOD` mix until re-extract; operators re-run extract on papers of interest (no automatic rewrite of historical edges).
