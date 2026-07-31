# Radiology Method postprocess filter

**Date:** 2026-07-31  
**Status:** approved  
**Scope:** Drop radiology / non-pathology imaging Methods in extraction postprocess (aggressive).

## Problem

Fangxin feasibility is pathology-slide only. Radiology terms are already dropped when typed as **Modality**, but extractors often label the same concepts as **Method** (`pyradiomics`, `radiomics model`, `ai-assisted cbct`, CT/MRI/PET/ultrasound/OCT/endoscopy models). Those Methods pollute weekly hotspots and transferable boards.

## Decision

**Aggressive Method drop** via postprocess (option A): any Method name that hits imaging / radiomics cues is treated as low-value and discarded from `APPLIES_METHOD` / `COMPARES_METHOD` (and Method-typed objects elsewhere in `postprocess_triples`).

Out of scope for this change:

- Deleting or rewriting already-stored KG rows (no DB migration).
- Hotspot-only display filters (optional follow-up if legacy rows remain noisy).
- Prompt-only fixes without postprocess (postprocess is the source of truth for this policy).

## Design

### API

Add `is_radiology_method(name: str) -> bool` in `fulltext_workflow/extractor/entity_normalize.py`.

Wire it inside `is_low_value_method` so existing drop paths keep working without duplicating call sites:

```text
is_low_value_method(name)
  → exact _LOW_VALUE_METHODS
  → _LOW_VALUE_METHOD_PATTERNS
  → is_radiology_method(name)   # NEW
```

### Match rules (normalized lowercase key)

1. **Exact set** `_RADIOLOGY_METHODS` — include at least: aliases already in `_RADIOLOGY_MODALITIES` that make sense as Method labels, plus `pyradiomics`.
2. **Patterns** `_RADIOLOGY_METHOD_PATTERNS` — word-boundary / stem matches, including:
   - `\bradiomics?\b`, `\bpyradiomics\b`
   - `\bct\b`, `\bmri\b`, `\bpet\b`, `\bcbct\b`, `\boct\b`
   - `\bultrasound\b`, `\bsonograph`, `\bendoscop`
   - `\bmammograph`, `\btomograph`, `\bx[\s-]?ray\b`
   - `\bpet[\s\-/]?ct\b`, `\bradiolog`
3. Short tokens (`ct`, `mri`, `pet`, `oct`) **must** use word boundaries to avoid naive substring false positives where practical.

Multimodal names that mention radiology **and** pathology (e.g. “ct and pathology fusion”) **are dropped** under this policy.

### Keep

Pathology / computational-pathology methods without radiology cues: e.g. `hover-net`, `clam`, `resnet-50`, WSI-only names without `\bct\b`/`mri`/… hits.

### Docs / tests

- Document maintenance row in `fulltext_workflow/extractor/GRANULARITY.md` (Method section or radiomics cross-link).
- Tests in `tests/test_entity_normalize.py`: drop positives above; keep `hover-net` / `clam` / `dual-attention mil`.

## Success criteria

- New extractions do not persist radiology Method triples through `postprocess_triples`.
- `pytest fulltext_workflow/tests/test_entity_normalize.py` passes.
- Existing DB may still show legacy radiology Methods until re-extract or a later cleanup pass.
