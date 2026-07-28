# Study-Type Prompt Packs & Policy Matrix Design

**Date:** 2026-07-28  
**Status:** Approved for implementation planning  
**Scope:** Classify + Pass 1 + Pass 2 prompts; declarative per-type policy; four new relations; minimal downstream read adapters.  
**Depends on:** `2026-07-25-extraction-quality-design.md` (Pass 1 + Pass 2 reconcile remains the backbone).

## Problem summary

All eight `study_type` values currently share one section-extraction system prompt and one reconcile prompt. `study_type` is only a user-message label. Hard behavioral differences exist almost only for `review` / `meta_analysis` (drop `USES_DATASET`). That does not match how researchers read different genres: algorithm papers vs clinical validation vs surveys vs dataset releases vs foundation models.

## Goals

- Align extraction with **scholar reading lenses** (attention/priority) **and** **type-specific extractable boundaries**.
- Cover **classifier + Pass 1 + Pass 2**.
- Enforce a **full policy matrix** in postprocess / reconcile (not prompt-only).
- Allow a **small set of new relations** where existing edges are semantically wrong if overloaded.
- Ship **all eight study types in one phase**, with **minimal** downstream adaptation (ingest + display/stats; no gap-logic rewrite).

## Non-goals

- Replacing section extraction with a multi-role “scholar notes” then map pipeline.
- New entity types.
- Reworking gap UI, hotspot scoring, or feasibility APIs beyond safe ignore/whitelist of new relations.
- Healing historical DB without re-extract (re-extract is the source of truth).
- Special rich semantics for `other`.

## Approaches considered

| Approach | Summary | Verdict |
|----------|---------|---------|
| 1. Eight full prompt copies | Independent system prompts per type | Rejected — shared pathology rules drift |
| 2. Composable Prompt Pack + Policy Matrix | Shared core + per-type pack + enforceable matrix | **Chosen** |
| 3. Multi-role intermediate representation | Persona notes → triples | Rejected for this phase — cost and pipeline disruption |

## Architecture

```text
title + abstract + pub_types
  → classify_study_type (criteria aligned with packs)
  → study_type

Pass 1 (per section):
  system = Shared Core + StudyType Pack[study_type] + Section Overlay
  → triples
  → apply_policy_matrix(study_type)
  → existing entity_normalize / dataset_access
  → DB

Pass 2 (fulltext, if any):
  system = Shared Reconcile Core + Pack[study_type].reconcile
  → datasets / bindings / limitations (+ type-allowed survey/cover actions)
  → apply_policy_matrix(study_type)
  → DB

Downstream (minimal):
  existing consumers keep using legacy relations;
  new relations: graph color + read-only stats; Method heat still APPLIES_METHOD-only
```

### Two sources of truth

| Layer | Role | Form |
|-------|------|------|
| **Prompt Pack** | How a scholar reads this genre; what to prioritize | Text modules assembled by `study_type` |
| **Policy Matrix** | What may be written to DB; remaps and dataset mode | Testable config (`study_policy.py` or YAML loaded once) |

Packs guide generation; **matrix is authoritative** for allow/deny/remap.

### Module touchpoints

| Module | Change |
|--------|--------|
| `extractor/study_prompts/` | Shared core + eight packs (section + reconcile snippets) |
| `extractor/study_policy.py` | Matrix + `apply_policy(study_type, triples)` |
| `extractor/study_classifier.py` | Decision hints aligned with pack lenses |
| `extractor/section_extractor.py` | Assemble prompts; call `apply_policy` before/with postprocess |
| `extractor/entity_normalize.py` | Delegate review/meta dataset drop to matrix (no duplicated rule) |
| `extractor/fulltext_reconcile.py` | Type reconcile pack; optional `datasets[].role`; survey/cover writes |
| `extractor/triple_models.py` | Extend `RelationLiteral` |
| `graph/kg_builder.py`, gap tools | Whitelist/colors/stats; do not change combo core |
| `config.py` | Feature flags if needed (`STUDY_POLICY_ENABLED`, default on after pilot) |

## Scholar lenses and extraction boundaries

| study_type | Scholar focus | Emphasize | Weaken / forbid | New relations |
|------------|---------------|-----------|-----------------|---------------|
| `ai_algorithm` | Contribution, task, baselines, data, metrics | `APPLIES_METHOD`, `COMPARES_METHOD`, `PERFORMS_TASK`, `USES_DATASET`, `ACHIEVES_METRIC` | Background methods as APPLIES | — |
| `clinical_study` | Cohort/disease, endpoints, AI used, clinical limits | `TARGETS_DISEASE`, `PERFORMS_TASK`, `USES_DATASET`, `REPORTS_LIMITATION` | Algorithm name-dropping without study use | — |
| `review` | Coverage, method landscape, field gaps | `COVERS_DISEASE`, `SURVEYS_METHOD`, field-level limitations | No `USES_DATASET` (unless rare self-analysis); no APPLIES for surveyed methods | `COVERS_DISEASE`, `SURVEYS_METHOD` |
| `meta_analysis` | Inclusion, pooled endpoints, heterogeneity | Same family as review; stricter quantitative framing | Default: no constituent-study datasets as this paper’s USES | Same as review |
| `dataset_benchmark` | Released data, protocol, benchmark tasks, baselines | `RELEASES_DATASET`, `PERFORMS_TASK`, `COMPARES_METHOD`, `ACHIEVES_METRIC` | Confusing cited public sets with released set | `RELEASES_DATASET` |
| `foundation_model` | Pretrain data, model contribution, transfer tasks | `APPLIES_METHOD`, `PRETRAINS_ON`, downstream task/dataset | Marking all downstream methods as APPLIES | `PRETRAINS_ON` |
| `multimodal` | Modality set, fusion method, per-modality data | Multiple `USES_MODALITY`, method, tasks/datasets | Single-modality under-extraction; radiology-as-primary (keep existing pathology preference) | — |
| `other` | Only clearly stated study facts | Shared core, prefer sparse | Uncertain → omit | New relations **denied** |

### New relation semantics

- `SURVEYS_METHOD` → Method: discussed as landscape/representative in review/meta (not implemented here).
- `COVERS_DISEASE` → Disease: diseases in survey scope (not necessarily a single-study primary target).
- `RELEASES_DATASET` → Dataset: dataset contributed/released by this paper (may co-exist with `USES_DATASET`).
- `PRETRAINS_ON` → Dataset: pretraining corpus / large unlabeled pool (finetune/eval still `USES_DATASET`).

Entity types remain unchanged.

## Policy matrix

### Shape

```text
study_type → {
  allow: set[relation]
  deny: set[relation]
  remap: { from_relation → to_relation }
  prefer: list[relation]   # prompt priority only
  dataset_mode: experimental | none | release_ok | pretrain_ok
}
```

### Default forced rules

| study_type | deny (hard) | remap | dataset_mode |
|------------|-------------|-------|--------------|
| `ai_algorithm` | — | — | `experimental` |
| `clinical_study` | — | — | `experimental` |
| `review` | `USES_DATASET`, `RELEASES_DATASET`, `PRETRAINS_ON` | `APPLIES_METHOD`→`SURVEYS_METHOD`; `TARGETS_DISEASE`→`COVERS_DISEASE` when `evidence_quote` present, else drop | `none` |
| `meta_analysis` | Same as review by default | Same as review | `none` (default) |
| `dataset_benchmark` | — | Do **not** auto-remap `USES_DATASET`→`RELEASES_DATASET` | `release_ok` |
| `foundation_model` | — | — | `pretrain_ok` |
| `multimodal` | — | — | `experimental` |
| `other` | All four new relations | — | `experimental` |

`dataset_mode`:

- `experimental`: current meaning of `USES_DATASET`.
- `none`: strip dataset-class edges `USES_DATASET`, `RELEASES_DATASET`, and `PRETRAINS_ON` (Pass 1 + Pass 2 clear), same intent as today’s review/meta cleanup.
- `release_ok`: allow `RELEASES_DATASET` and `USES_DATASET`.
- `pretrain_ok`: allow `PRETRAINS_ON` and `USES_DATASET`.

**Meta narrow exception:** only if Pass 2 (or explicit evidence) states authors ran their own pooled analysis on a named cohort, allow that `USES_DATASET` keep; default remains `none`. Do not loosen Pass 1 by default.

**Remap scope:** remap rules apply **only** to `review` / `meta_analysis`, never to clinical or algorithm papers.

`allow` for each type = (legacy relations appropriate to that type) ∪ (new relations enabled for that type). Anything not allowed is denied. Implementation may encode `allow` as “all registered relations minus deny” plus explicit new-relation enable flags to avoid huge tables—but behavior must match the tables above.

## Pass 1 behavior

1. Build system prompt: Shared Core + Pack[type] + existing section overlay (intro/methods/…).
2. LLM returns triples; `RelationLiteral` includes new relations.
3. `apply_policy(study_type, triples)`: deny→drop; remap→rewrite; unknown→drop.
4. Existing `postprocess_triples` / dataset_access; review/meta dataset dropping **calls matrix** (`dataset_mode=none`) instead of a second hard-coded list.

## Pass 2 behavior

1. Reconcile system = shared reconcile core + `Pack[type].reconcile` checklist.
2. Extend JSON minimally:
   - `datasets[].role`: `experimental | release | pretrain | drop` (in addition to keep/merge/drop action as needed).
   - Optional `surveyed_methods[]` / `covered_diseases[]` for review/meta → persist as new relations with quotes.
3. Apply policy again before write; `dataset_mode=none` still clears dataset edges.
4. Bindings: review/meta still do not attach datasets; other types unchanged.

## Classifier alignment

Update study-type system/user guidance so decisions follow the scholar-focus column (e.g. protocol + release → `dataset_benchmark`; pretrain + broad transfer → `foundation_model`). Keep PubMed heuristics for review / meta_analysis / clinical_study. Misclassification risk is accepted but monitored via pilot confusion checks.

## Downstream (phase-1 minimal)

| Consumer | Behavior |
|----------|----------|
| Graph / viz | Color or label new relations; Method heat **APPLIES_METHOD only** (`SURVEYS_METHOD` excluded) |
| gap_tools / hotspot | Core queries unchanged; add read-only counts for the four new relations for QA |
| idea / gap agent | Tool text: survey coverage ≠ applied method; released set ≠ cited-only set |
| DB | `relations.relation` TEXT already stores new strings; keep ingest whitelist in sync with `RelationLiteral` |

### Explicitly deferred

- Rewriting combo gaps with `COVERS_DISEASE`.
- Ranking opportunities with `SURVEYS_METHOD`.
- Dedicated UI for new relations.

## Idempotency and rollout

- Full benefit requires Pass 1+2 re-extract after packs/matrix land.
- Pilot: 20–50 PMIDs, **stratified by study_type** (ensure review, dataset_benchmark, foundation_model, ai_algorithm, clinical_study represented when corpus allows).
- Feature flag optional; default path should use packs+matrix once pilot gates pass.
- Compatible with `2026-07-25` reconcile statuses and supersede semantics.

## Testing

- Unit: matrix deny/remap/dataset_mode for each study_type.
- Unit: prompt assembly includes the correct pack fragment.
- Integration: fixture papers → JSON → DB for review, dataset_benchmark, foundation_model, ai_algorithm.
- Human pilot gates (tunable):
  - review/meta: active `USES_DATASET` ≈ 0; residual false `APPLIES_METHOD` ≈ 0 after policy.
  - dataset_benchmark: release vs use agreement ≥ 80% on sampled rows.
  - foundation_model: pretrain vs eval set not conflated on spot check.
  - Regression: ai_algorithm platform-blacklist / public precision no worse than current extraction-quality baseline.

## Success criteria

1. All eight types have pack + matrix entries; assembly path unit-tested.
2. Pilot stratified gates above met.
3. Downstream main paths do not error on unknown/new relations.
4. Spec does not remove Pass 2; it specializes prompts and enforcement by type.

## Open parameters

| Parameter | Default |
|-----------|---------|
| Pack size budget | ~400–600 tokens of type-specific text per pack (excluding shared core) |
| Review disease remap | prefer remap `TARGETS_DISEASE`→`COVERS_DISEASE`; drop if no quote |
| Meta self-analysis exception | Pass 2 explicit keep only |
| `STUDY_POLICY_ENABLED` | true after pilot tooling validates |

## Relationship to prior design

This document **extends** extraction-quality Pass 1/2. It does not replace reconcile, platform blacklist, or limitation merge. Those remain; study-type packs and matrix specialize them.
