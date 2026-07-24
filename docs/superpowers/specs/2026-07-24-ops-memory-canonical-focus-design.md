# Design: Ops Memory Canonical Focus Key (ZH–EN Synonym Lane)

**Date:** 2026-07-24  
**Status:** Approved  
**Related:** [`2026-07-15-ops-memory-design.md`](2026-07-15-ops-memory-design.md), [`2026-07-15-zh-en-focus-synonyms-design.md`](2026-07-15-zh-en-focus-synonyms-design.md)  
**Scope:** Make ops memory look up / persist / clear by **disease-concept canonical** `focus_key` so Chinese and English synonyms share one memory lane. No change to corpus SQL expansion, gap fingerprints, or proposal content.

## Problem

Corpus focus already uses `resolve_disease_concept` (e.g. `乳腺癌` / `breast cancer` → concept `breast_carcinoma`, canonical `breast carcinoma`). Ops memory does **not**:

- `normalize_focus_key` only strip + lowercase.
- `ops_runs.focus_key` stores the literal user string (`breast cancer` vs `乳腺癌`).
- Gap UI expander calls `load_recent_gaps(focus_input)` → exact `focus_key` match → **empty** when language differs.

Empirical: run with `breast cancer` stores gaps; later focus `乳腺癌` shows “暂无记忆”.

## Goals

- Same disease concept → **one** ops memory lane regardless of ZH / EN / phrase alias.
- Keep `focus_raw` as the operator’s typed string for audit.
- Migrate existing `ops_runs.focus_key` values that resolve to a concept onto that concept’s canonical.
- `clear_ops_memory --focus "乳腺癌"` clears the same lane as `--focus "breast cancer"`.

## Non-goals

- Expanding the disease dictionary itself (reuse `DISEASE_CONCEPTS`).
- Changing corpus `focus_filter` / SQL matching.
- Embedding-based focus matching for unknown strings.
- Renaming or merging gap fingerprints across concepts.
- UI redesign beyond correct memory listing under synonym focus.

## Decisions

| Topic | Choice |
|-------|--------|
| Key strategy | **A** — store `concept.canonical` (lowercased) when resolve succeeds |
| Unresolved focus | Keep literal normalized string (unchanged) |
| History | **Migrate** existing `ops_runs.focus_key` to canonical on DB migrate |
| Read path | No long-lived alias `IN (...)` query; single key after migrate + canonical writes |
| Empty / no focus | Still `__all__` |

Rejected:

1. **Alias-aware read only** — dual path forever; clear/load must know every synonym spelling.  
2. **Lazy rewrite on read** — side effects on read; surprising for dry-run tooling.  
3. **concept `id` as key** — more opaque in SQL/debug vs canonical English label already shown in UI.

## Behavior

### `normalize_focus_key(focus)`

1. `None` / blank → `__all__`.
2. Strip + collapse whitespace + lowercase (current behavior).
3. If `resolve_disease_concept(normalized)` returns a concept → return `concept.canonical` lowercased / whitespace-normalized the same way.
4. Else → return the literal normalized string.

Call sites already funnel through this helper for create / load / clear; no separate UI branch required beyond existing caption.

### Persist

- `create_ops_run(focus_raw, ...)`: `focus_raw` unchanged; `focus_key = normalize_focus_key(focus_raw)`.
- Example: input `乳腺癌` → `focus_raw="乳腺癌"`, `focus_key="breast carcinoma"`.

### Load / clear

- `load_recent_gaps("乳腺癌")` and `load_recent_gaps("breast cancer")` both query `focus_key='breast carcinoma'`.
- `clear_ops_memory.py --focus "乳腺癌"` uses the same normalization before DELETE.

### Migration

In `_migrate_db` (or a dedicated ops migrate step invoked from `init_db`):

1. `SELECT run_id, focus_key FROM ops_runs WHERE focus_key != '__all__'`.
2. For each row, compute `canonical = normalize_focus_key(focus_key)` (after the new semantics).
3. If `canonical != focus_key`, `UPDATE ops_runs SET focus_key=? WHERE run_id=?`.

Idempotent. Multiple historical spellings for one concept collapse onto one lane (multiple `run_id`s allowed; no unique constraint on `focus_key` alone).

Examples after migrate:

| Before | After |
|--------|--------|
| `breast cancer` | `breast carcinoma` |
| `乳腺癌` | `breast carcinoma` |
| `肠息肉` | `colorectal polyp` |
| `radiomics` | `radiomics` (unresolved) |

## Components

| Unit | Change |
|------|--------|
| `analysis/ops_memory.py` | `normalize_focus_key` calls `resolve_disease_concept` |
| `db/schema.py` | One-time (idempotent) migrate of `ops_runs.focus_key` |
| `tests/test_ops_memory.py` | Canonical ZH/EN equality; load after legacy key migrate |
| Docs (`PIPELINE.md` / `SCRIPTS.md`) | One-line note that ops `focus_key` is concept canonical when known |

No schema column changes.

## Error handling / edge cases

- Resolve failure → literal key (same as today).
- Ambiguous substring matches follow existing `resolve_disease_concept` ranking (no new policy).
- `__all__` never rewritten.
- Migration failures should not abort unrelated migrate steps; log and continue or fail loudly in tests — prefer **fail the migrate step** if UPDATE errors (SQLite local DB).

## Testing

- `normalize_focus_key("乳腺癌") == normalize_focus_key("breast cancer") == "breast carcinoma"`.
- `normalize_focus_key("Breast Cancer")` same.
- Unresolved: `normalize_focus_key("  Foo Bar ") == "foo bar"`.
- Persist under `breast cancer`, then `load_recent_gaps("乳腺癌")` returns those items (with migrate applied or insert via create after new normalize).
- `clear` scope with ZH focus counts the EN-canonical lane.

## Acceptance

1. Gap UI: after a `breast cancer` run exists, focus `乳腺癌` expander lists those gaps (post-migrate / new writes).
2. New persist with `乳腺癌` writes `focus_key=breast carcinoma`.
3. `clear_ops_memory.py --focus "乳腺癌" --yes` removes that lane’s runs/gaps/proposals.
4. Existing unit tests for empty/`__all__` still pass.
