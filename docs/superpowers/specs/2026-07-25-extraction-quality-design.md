# Extraction Quality & Fulltext Reconcile Design

**Date:** 2026-07-25  
**Status:** Approved for implementation planning  
**Scope:** Phase 0–1 (data cleaning + two-pass extraction). Phase 2 (hotspot / combo actionability) is interface-only.

## Problem summary

Four recurring issues in `fulltext_workflow/`:

1. **Hotspots lack actionable guidance** — weekly scores emphasize volume/velocity, not “what to do next.”
2. **Combo / limitations are weak** — Method×Disease is a cartesian grid; limitation strings are fragmented.
3. **Section-only extraction misses global facts** — datasets, cross-entity bindings, and paper-level limitations need full-text judgment.
4. **Public datasets polluted by literature platforms** — e.g. PubMed/GEO extracted as `Dataset` with `access_class=public`.

**Delivery order (user choice B):** fix data quality and extraction first; improve hotspot/combo later on a cleaner graph.

## Goals

- Keep **section extraction as the evidence base** (Pass 1).
- Add a **narrow full-text reconcile pass** (Pass 2) for: Dataset cleanup, Method–Disease–Dataset bindings, Limitation merge.
- **Merge** section limitation fragments into canonical entities (`superseded`), not dual parallel stores.
- **Full re-extract** (Pass 1+2) after a **small pilot** (20–50 PMIDs) passes QA gates.
- Leave clear hooks so Phase 2 hotspots/combos can consume `active` entities and bindings.

## Non-goals (this design)

- Reworking gap UI layout or feasibility vendor APIs.
- Changing PubMed query groups / ingest sources.
- Implementing new hotspot scoring or combo-gap logic (Phase 2 only defines inputs).
- Replacing section extraction with full-text-only extraction.

## Approaches considered

| Approach | Summary | Verdict |
|----------|---------|---------|
| 1. Rules-only postprocess | Blacklist + stricter access + alias expansion | Too weak for bindings / limitation synthesis |
| 2. Structured Pass 2 | Section base + fulltext reconcile LLM + schema | **Chosen** |
| 3. Unified fulltext agent | Replace section pipeline | Too disruptive; weak evidence locality |

## Architecture

### Per-paper flow

```text
fulltext/abstract ready
  → Pass 1: section LLM extraction (existing)
  → Rule layer: platform blacklist, access tighten, aliases
  → if substantive fulltext:
       Pass 2: fulltext reconcile LLM
         → dataset keep|merge|drop
         → method–disease–dataset bindings
         → limitation canonicalization + supersede section edges
  → else: reconcile_status = skipped_no_ft
  → mark extraction / reconcile done
```

### Pass responsibilities

| Pass | Input | Output |
|------|--------|--------|
| Pass 1 | Per-section text | Triples with `evidence_section` / `evidence_quote`; `extraction_pass=section` |
| Rules | Pass 1 Dataset triples | **Before insert:** reject platform blacklist hits (no Dataset entity / no `USES_DATASET`); set `public` only if alias-listed, else demote hint to `unknown` |
| Pass 2 | Concatenated fulltext (truncated) + Pass 1 entity summary | Dataset actions, bindings rows, canonical limitations; catch anything rules missed |

Abstract-only papers: Pass 1 + rules only; no Pass 2.

## Schema changes

### `relations` (ALTER)

| Column | Type | Meaning |
|--------|------|---------|
| `status` | TEXT DEFAULT `'active'` | `active` \| `superseded` |
| `superseded_by` | INTEGER NULL | Canonical `entities.id` for merged limitations / dropped datasets |
| `extraction_pass` | TEXT DEFAULT `'section'` | `section` \| `fulltext_reconcile` |

Downstream reads for limitations, datasets, and hotspots **default to `status = 'active'`**.

### `paper_entity_bindings` (CREATE)

```text
id INTEGER PK
source_pmid TEXT NOT NULL
method_entity_id INTEGER NULL
disease_entity_id INTEGER NULL
dataset_entity_id INTEGER NULL
confidence REAL DEFAULT 1.0
evidence_quote TEXT
created_at TIMESTAMP
```

One row = one claimed binding in the paper. Entity IDs must exist in `entities` (Pass 2 may create Dataset names after normalization; prefer Pass 1 canonical names).

### `papers` (ALTER)

| Column | Meaning |
|--------|---------|
| `reconcile_status` | `pending` \| `done` \| `skipped_no_ft` \| `failed` |
| `reconcile_at` | Timestamp of last reconcile attempt |

### Unchanged

- `entities.access_class` remains the dataset access field.
- Platform blacklist and public aliases live in `extractor/dataset_access.py`.

## Pass 2 LLM contract

JSON shape (illustrative):

```json
{
  "datasets": [
    {
      "name": "camelyon16",
      "access": "public",
      "action": "keep|merge|drop",
      "reason": "..."
    }
  ],
  "bindings": [
    {
      "method": "...",
      "disease": "...",
      "dataset": "...",
      "quote": "..."
    }
  ],
  "limitations": [
    {
      "canonical": "small sample size",
      "merges": ["limited cohort", "small n"],
      "quote": "..."
    }
  ]
}
```

**Write rules:**

- `keep`: retain / confirm Dataset; optionally refresh `access_class` from Pass 2 `access` when consistent with alias rules (Pass 2 cannot promote unlisted names to `public`).
- `merge`: rename/collapse to a canonical dataset name already in aliases or Pass 1; supersede old `USES_DATASET` edge(s), insert active edge to canonical entity.
- `drop` (platform / not a dataset): mark matching `USES_DATASET` edges for that PMID as `status=superseded` (prefer supersede over hard delete during pilot for rollback).
- Limitation `merges`: matching section `REPORTS_LIMITATION` edges → `status=superseded`, `superseded_by=<canonical entity id>`; insert one active `REPORTS_LIMITATION` with `extraction_pass=fulltext_reconcile`.
- `bindings`: upsert into `paper_entity_bindings`; resolve names via existing normalizers when possible. Empty `dataset` is allowed when the paper states method–disease without a named public set.

## Module touchpoints

| Module | Change |
|--------|--------|
| `extractor/dataset_access.py` | Platform blacklist; do not trust unlisted LLM `public`; expand pathology public aliases |
| `extractor/entity_normalize.py` | Invoke blacklist on Dataset triples; optional limitation alias growth |
| `extractor/fulltext_reconcile.py` | **New** — assemble text, call LLM, parse JSON, persist |
| `extractor/section_extractor.py` | Hook Pass 2 at end of `_process_paper`; support PMID-list / limit re-extract |
| `db/schema.py` | Migrations for columns + `paper_entity_bindings` |
| `config.py` | `RECONCILE_ENABLED`, `RECONCILE_MAX_CHARS`, blacklist toggle, pilot helpers |
| `main.py` | `extract --pmid-list` / `--limit`; optional `reconcile` (Pass 2 only) |
| Downstream (minimal Phase 1) | Filter `status='active'` in limitation/dataset queries used by gap tools, weekly hotspot, V-03, idea agent |

## Idempotency and errors

- Re-extracting a PMID: delete that PMID’s `relations` and `paper_entity_bindings`, then Pass 1+2.
- Pass 2 failure: set `reconcile_status=failed`; keep Pass 1 results; allow `reconcile` re-run.
- No fulltext: `reconcile_status=skipped_no_ft`.

## Phase 0 — pilot (required before full re-extract)

1. Select **20–50** PMIDs with PMC/MinerU fulltext where possible; include known dirty cases (PubMed/GEO mentioned as “data”).
2. Store list in `fulltext_workflow/data/pilot_pmids.txt` (or equivalent).
3. Run `extract --pmid-list ...` (clear → Pass 1 → rules → Pass 2).
4. Manual QA checklist:
   - No literature platforms as active Dataset
   - Unlisted “public” demoted to `unknown`
   - Bindings have quotes and match prose
   - Section limitations reasonably superseded; canonicals readable
5. Suggested gates (tunable): platform false-positive rate = 0 on sample; public precision ≥ 90%; obvious limitation-merge errors ≤ 10%.
6. Only after gates pass: full-corpus Pass 1+2 re-extract.

Optional helper: `scripts/pilot_reconcile_qa.py` exporting CSV for review.

## Phase 2 interfaces (specify only; do not implement here)

Future hotspot/combo work should consume:

- Active Dataset + trustworthy `access_class`
- `paper_entity_bindings` (instead of pure Top-N Method × Disease cartesian gaps)
- Active canonical Limitations

Intended narrative shift: from “what is rising” to “rising × binding gap × public data feasible.”

## Testing

- Unit: blacklist matching; tightened `resolve_dataset_access`; supersede write path.
- Integration: 1–2 fixture papers through Pass 2 JSON → DB.
- Human: pilot QA table / CSV.

## Success criteria (Phase 1)

- Pilot gates met on the chosen PMID set.
- Active Dataset list free of configured platform names in pilot (and spot-check on full run).
- Every successfully reconciled fulltext paper has `reconcile_status=done` and either bindings and/or merged limitations when the paper states them.
- Downstream limitation/dataset reads use `status='active'` without breaking existing CLI/UI entry points.

## Open parameters (defaults)

| Parameter | Default |
|-----------|---------|
| Pilot size | 20–50 PMIDs |
| `RECONCILE_ENABLED` | true after pilot tooling lands |
| `RECONCILE_MAX_CHARS` | `32000` (truncate with head+tail preference for methods/discussion/limitations sections when assembling) |
| Drop vs supersede for bad datasets | supersede during pilot |
