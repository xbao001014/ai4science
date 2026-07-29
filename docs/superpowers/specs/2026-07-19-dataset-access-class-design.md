# Design: Dataset access_class + Fangxin-first proposals

**Date:** 2026-07-19  
**Status:** Implemented (ready for re-extract)
**Scope:** Extractor Dataset labeling, entity schema, idea-agent tools/prompts (end-to-end)

## Problem

`USES_DATASET` stores dataset names only. Literature mixes public benchmarks (Camelyon, TCGA, …) and private/institutional cohorts. Research proposals should prefer Fangxin pathology data, may use public datasets as supplements, and must label public sources explicitly. Today neither the KG nor the proposal agent encodes public vs private.

## Goals

1. Every Dataset entity has `access_class ∈ {public, private, unknown}`.
2. Classification: **curated public alias list first**, then private cue patterns / LLM hint.
3. Proposal pipeline: **Fangxin primary**; public datasets allowed when marked; do not replace Fangxin when Fangxin is feasible.

## Non-goals

- No split relations (`USES_PUBLIC_DATASET` / `USES_PRIVATE_DATASET`).
- Fangxin is not ingested as a literature Dataset entity (feasibility API remains the source of truth).
- Not a complete world catalog of pathology datasets—seed high-frequency aliases only.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| End-to-end scope | Extract → KG → proposal tools/prompts |
| Classification | Public alias list + LLM/private cues (option B) |
| Storage | Keep `USES_DATASET`; add `entities.access_class` (option 1) |
| Precedence on conflict | `public` > `private` > `unknown` |

## Schema

- Add nullable column `access_class TEXT` on `entities` (meaningful for `type='Dataset'` only).
- Migration in `_migrate_db` / `init_db` path: `ALTER TABLE entities ADD COLUMN access_class TEXT`.
- `upsert_entity(name, type, access_class=None)`:
  - Insert with resolved class when provided.
  - On conflict, upgrade class by precedence if the new class is stronger.
- No change to `relations` schema.

## Extraction + normalize

### Prompt (`section_extractor`)

- Study-content only for Dataset (already required).
- Optional triple field or parallel hint: `access_hint` ∈ `public|private|unknown` (coerce before validate if added on Triple; alternatively resolve entirely in postprocess from name + quote—prefer storing hint on Triple as optional field only if low friction; otherwise resolve in postprocess from name/evidence only + list).

**Preferred implementation detail:** keep Triple schema unchanged; resolve `access_class` in postprocess from normalized dataset name + evidence_quote + optional LLM-only path if raw JSON includes `access_hint` on the item dict before Triple validation (strip unknown keys after reading hint).

### Deterministic rules (`entity_normalize` or `dataset_access.py`)

1. Normalize dataset name (lowercase, alias map).
2. If name matches `PUBLIC_DATASET_ALIASES` → `public`.
3. Else if private cue patterns match name or evidence (`in-house`, `institutional`, `our hospital`, `private cohort`, …) → `private`.
4. Else if LLM `access_hint` present → use it (validated enum).
5. Else → `unknown`.

Seed public aliases (illustrative, extend in maintenance):  
`camelyon16`, `camelyon17`, `tcga`, `panda`, `breakhis`, `cptac`, `tulip`, `bach`, `digestpath`, `midog`, `panda challenge`, etc.

Document list maintenance in `GRANULARITY.md`.

### Persist

- `_save_triple` for `USES_DATASET`: `upsert_entity(..., access_class=resolved)`.

## Proposal / tools

### `tool_datasets_for_topic`

Return columns: `dataset`, `access_class`, `used_by_papers`.  
Order: public first, then private, then unknown (or group in description).

### Idea agent / Critic prompts

Rules (English proposals):

1. Primary cohort: Fangxin via feasibility tools; state sample size and labels.
2. Public datasets allowed for pretraining, external validation, method comparison, or supplementary experiments.
3. Any public dataset use must be labeled in the proposal (e.g. `public dataset: <name>`).
4. When Fangxin is feasible, do not use public data as the sole train/val source instead of Fangxin.
5. When Fangxin is insufficient: keep “Data Integration Limitations”; public data may carry more weight but must still be labeled, with rationale.

Critic checks: unlabeled public datasets; Fangxin-feasible proposals that omit Fangxin entirely → require revision / lower scores.

## Testing

- Unit: alias → public; private cues; precedence upgrade; migration column present.
- Tool contract: `datasets_for_topic` includes `access_class`.
- Prompt smoke (optional): critic/designer text contains Fangxin-first + labeling rules.

## Rollout

- Code + migration + tests + GRANULARITY.
- Existing DB: column defaults NULL until re-extract or a one-shot backfill script (optional; re-extract preferred for accuracy).
- Historical Dataset rows without class treated as `unknown` in tools (`COALESCE(access_class, 'unknown')`).
