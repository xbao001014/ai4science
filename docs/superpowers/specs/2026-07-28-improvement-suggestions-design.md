# Design: Limitation → actionable improvement suggestions

**Date:** 2026-07-28  
**Status:** Draft for user review  
**Scope:** Pass 2 fulltext reconcile, new suggestion store, gap_ui surfaces, idea-agent tool; corpus aggregation by topic × action_type

## Problem

The pipeline extracts atomic **Limitation** phrases (e.g. `small sample size`, `lack of external validation`). Downstream gap/hotspot/idea views mostly surface those short strings. Alone they are weak for decisions: readers still need “what to do next” grounded in the paper’s methods, cohort, and future-work wording.

## Goals

1. **Paper-level:** For each fulltext paper, produce structured improvement suggestions tied to canonical limitations when possible.
2. **Grounding policy B:** Anchor on author-stated limitations / future work; lightly synthesize with methods/results/modality context into executable one-liners. Do not invent unstated datasets, metrics, diseases, or numbers.
3. **Structured rows:** Each suggestion has `action_type` + `suggestion` + `evidence_quote` (+ section, grounding, confidence).
4. **Corpus-level:** Aggregate by **topic × action_type** for hotspot/gap pages (after paper-level works).
5. Keep Limitation entities and existing temporal/impact analytics unchanged; suggestions are a **sidecar** store, not new KG entity types.

## Non-goals

- New `Direction` / `Suggestion` entity types or `SUGGESTS_*` relations in the main KG graph.
- Changing Fangxin feasibility APIs or implementation-difficulty formulas.
- Long multi-paragraph proposals in extract (idea-agent remains the long-form writer).
- Abstract-only / no-fulltext papers: no suggestion pass (same gate as Pass 2 `skipped_no_ft`).
- Replacing author limitations with suggestions in ranking signals (`limitation_temporal`, impact rank stay limitation-based).

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Delivery order | Paper-level first, then topic × action aggregation (user D) |
| Grounding | Author-anchored + light synthesis (user B) |
| Row shape | Structured: action_type + suggestion + evidence (user B) |
| Corpus view | Topic × action_type (user C) |
| Architecture | Extend Pass 2 reconcile JSON + new table (approach 1) |
| Graph impact | Sidecar table; do not pollute Limitation entity stats |

## Approaches considered

| Approach | Summary | Verdict |
|----------|---------|---------|
| 1. Pass 2 + sidecar table | Same reconcile call emits `recommendations[]`; store outside `entities` | **Chosen** |
| 2. New Direction entity + relation | Uniform graph queries | Rejected: merges/normalization conflict with Limitation; pollutes gap stats |
| 3. Separate third LLM pass | Decoupled from extract | Rejected: extra cost; easy desync from canonical limitations |

## Schema

### Table `paper_improvement_suggestions`

| Column | Type | Meaning |
|--------|------|---------|
| `id` | INTEGER PK | |
| `source_pmid` | TEXT NOT NULL | Paper |
| `limitation_entity_id` | INTEGER NULL | FK-like to `entities.id` (type Limitation); NULL if only future-work with no alignable limitation |
| `action_type` | TEXT NOT NULL | Controlled enum (below) |
| `suggestion` | TEXT NOT NULL | One executable sentence |
| `evidence_quote` | TEXT | Supporting span from limitation or future work |
| `evidence_section` | TEXT | e.g. `discussion`, `limitations`, `future_work` |
| `grounding` | TEXT NOT NULL | `author_stated` \| `synthesized` |
| `confidence` | REAL | 0–1 |
| `status` | TEXT DEFAULT `'active'` | `active` \| `superseded` |
| `extraction_pass` | TEXT DEFAULT `'fulltext_reconcile'` | Provenance |
| `created_at` | TIMESTAMP | |

**Indexes:** `(source_pmid)`, `(action_type)`, `(limitation_entity_id)`, `(status)`.

**Dedup key (logical):** same `source_pmid` + `action_type` + `limitation_entity_id` (NULL treated as distinct bucket) → keep highest confidence / latest write; supersede or replace prior active row on re-run.

### `action_type` enum

| Value | Typical trigger |
|-------|-----------------|
| `external_validation` | No external / independent test set |
| `expand_sample` | Small N / underpowered cohort |
| `multicenter` | Single-center |
| `prospective_design` | Retrospective-only |
| `multimodal` | Missing modality the authors flag |
| `method_refinement` | Algorithm / architecture follow-ups authors suggest |
| `dataset_enrichment` | Labels, stains, annotations, public benchmark add-ons authors suggest |
| `other` | Concrete but uncategorizable; avoid when a specific type fits |

Vague phrases (“more research is needed”) → **drop**, do not store as `other`.

## Pass 2 contract

Extend existing fulltext reconcile LLM JSON:

```json
{
  "datasets": [ /* existing */ ],
  "bindings": [ /* existing */ ],
  "limitations": [ /* existing canonical merge */ ],
  "recommendations": [
    {
      "limitation": "lack of external validation",
      "action_type": "external_validation",
      "suggestion": "Validate on an independent multi-center WSI cohort with locked preprocessing.",
      "evidence_quote": "...",
      "evidence_section": "future_work",
      "grounding": "synthesized",
      "confidence": 0.8
    }
  ]
}
```

### Generation rules

1. Every recommendation must cite an author limitation or future-work span in `evidence_quote`.
2. Synthesis may add **how** (e.g. multi-center, locked pipeline) only when implied by study context already in the assemble text; never invent named external datasets or numeric targets not in text.
3. Prefer linking `limitation` to a canonical name from this pass’s `limitations` list or existing active `REPORTS_LIMITATION` for the PMID.
4. If future work is clear but no limitation aligns → `limitation` empty / null entity id; `grounding` usually `author_stated`.
5. Cap per paper: soft max **8** recommendations; prefer coverage of distinct `action_type`s over duplicates.

### Write path

1. Run after limitation merge for the PMID so canonical names exist.
2. Resolve `limitation` via `normalize_entity_name(..., "Limitation")` → entity id.
3. On re-reconcile: mark prior `active` rows for that PMID as `superseded`, then insert new `active` rows (same rollback-friendly pattern as relation supersede).
4. Abstract-only / `skipped_no_ft`: leave suggestions empty; do not invent from abstract alone.

## Downstream consumption

### gap_ui (paper-level)

- Where limitations are listed: show linked suggestions (`action_type` chip + `suggestion`; expand quote).
- Mark `synthesized` vs `author_stated` so users do not treat synthesis as verbatim author text.

### gap_ui / hotspot (corpus-level)

- Query helper: given topic keyword → PMIDs in focus → group by `action_type`:
  - `paper_cnt`, representative `suggestion` (max confidence then newest), sample PMIDs.
- Hotspot “局限” tab may show top action buckets; **do not** change weekly hotspot scoring formulas in this design.

### idea_agent

- New tool `improvement_suggestions_for_topic(keyword)` → rows: limitation, action_type, suggestion, evidence_quote, source_pmid, grounding.
- Prompt guidance: use suggestions for “what to do next”; keep `author_limitations_for_topic` as problem statement fallback when suggestions are sparse.

## Module touchpoints (implementation sketch)

| Area | Touch |
|------|--------|
| `db/schema.py` | Create table + migrate |
| Pass 2 prompt / parse / apply | `recommendations` field; write helper |
| `idea_agent.py` | Tool + prompt line |
| `gap_ui.py` | Paper-level display; topic × action table |
| Tests | Fixture JSON → rows; aggregation smoke; grounding drop rules |

## Success criteria

1. Pilot (reuse existing fulltext pilot PMIDs): ≥80% of stored suggestions have non-empty `evidence_quote` aligned to limitation/future_work sections.
2. Manual spot-check: invented dataset/disease names in suggestions ≈ 0 on pilot set.
3. Re-run Pass 2 on same PMID does not leave duplicate `active` rows for the same dedup key.
4. Topic aggregation returns at least one action bucket when ≥3 papers in focus have suggestions.

## Delivery order

1. Schema + Pass 2 emit/write + unit tests  
2. gap_ui paper-level  
3. Topic × action aggregation + idea-agent tool  
4. Optional: hotspot tab enrichment  

## Relation to prior specs

Builds on Pass 2 limitation merge in `docs/superpowers/specs/2026-07-25-extraction-quality-design.md`. Does not reopen dataset access or study-type policy.
