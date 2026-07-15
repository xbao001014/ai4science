# Design: Shared Disease Synonym Expansion for In-DB Focus + Feasibility Mapping

**Date:** 2026-07-15  
**Status:** Approved (awaiting implementation)  
**Scope:** C — in-DB literature focus (`focus_filter` / Gap UI / Agent tools) + feasibility disease mapping (`disease_mapper`) + shared config for common disease concepts. **Out of scope:** PubMed / `search_queries.py` ingest expansion; extraction-time entity forced canonicalization.

## Problem

Gap/UI focus matching today uses substring `LIKE` plus a small `_TOKEN_SYNONYMS` map in `analysis/focus_filter.py`. Limitations:

1. **One-way token expansion** — user token `carcinoma` does not expand to `cancer` / `neoplasm` (only the key `cancer` expands to those alternatives).
2. **No disease-level phrase table** — misses `nasopharyngeal cancer`, `carcinoma of the nasopharynx`, controlled `NPC`, Chinese aliases.
3. **Duplicated / incomplete aliases** — `feasibility/disease_mapper.py` maintains separate dicts for gastric / lung / CRC / HCC / breast, with **no nasopharyngeal carcinoma**.
4. Empirical gap on current `kg_fulltext.db`: exact phrase ≈ 21 papers; recommended synonym union ≈ **25**; entity-only path differs (~27) and is a different measure.

## Goals

- Single source of truth for **disease concepts** (phrases, site tokens, histology class, abbreviations, ZH / feasibility keywords).
- `focus_sql_clause` / `focus_pmid_in_clause` / `resolve_topic_pmids` use concept expansion when the user focus resolves to a known concept.
- `disease_mapper` reads the same concepts for English/ZH alias → API search keyword (and mock legacy IDs where still needed).
- Prefer recall improvements with **bounded false positives** (phrase-first; controlled abbrev; site∧histology).
- Keep free-text fallback when no concept matches (backward compatible).

## Non-goals

- Changing PubMed query groups or re-fetching the corpus.
- Full UMLS/MeSH runtime ontology.
- Replacing KG entity names in SQLite with canonical IDs (future work).

## Approach (chosen)

**Shared disease-concept config** consumed by focus filter and disease mapper (Approach 2 from brainstorming). Rejected: token-map-only patch (insufficient); external ontology (too heavy for scope C).

## Data model

New module: `fulltext_workflow/analysis/disease_synonyms.py` (Python dicts; no YAML dependency).

### Histology classes

```text
malignant_neoplasm → carcinoma | cancer | neoplasm | neoplasms | tumor | tumour
```

(Optional later: adenocarcinoma-specific class; not required for v1.)

### Disease concept (per entry)

| Field | Purpose |
|-------|---------|
| `id` | Stable key, e.g. `nasopharyngeal_carcinoma` |
| `canonical` | Preferred English display / default phrase |
| `phrases` | Full-string aliases (lowercased match) |
| `sites` | Anatomic / site tokens |
| `histology_class` | Key into histology classes (default `malignant_neoplasm`) |
| `abbreviations` | e.g. `npc` — match with word-boundary semantics in SQL or prefilter |
| `zh` | Chinese aliases for focus resolution |
| `feasibility_keyword_zh` | Preferred keyword for Fangxin `list_diseases` search |
| `mock_disease_id` | Optional legacy mock id for `PATHOLOGY_DATA_PROVIDER=mock` |

### Initial concepts (v1)

Align with existing mapper coverage and add NPC:

- `gastric_adenocarcinoma` (胃 / 胃癌 / GC-ADC …)
- `lung_adenocarcinoma` / NSCLC-oriented aliases as today
- `colorectal_adenocarcinoma`
- `hepatocellular_carcinoma`
- `breast_carcinoma`
- `nasopharyngeal_carcinoma` (phrases + sites `nasopharyngeal`/`nasopharynx` + abbr `npc` + zh `鼻咽癌`/`鼻咽` + feasibility keyword `鼻咽` or `鼻咽癌`)

Generic anatomic token synonyms currently in `_TOKEN_SYNONYMS` (`breast`/`mammary`, `lung`/`pulmonary`, …) remain as **fallback** for non-concept focus strings, or are derived from concept `sites` where overlapping.

## Matching algorithm (`focus_filter`)

### Resolve

`resolve_disease_concept(focus: str) -> Concept | None`

1. Normalize focus (`normalize_focus`); reject placeholders.
2. Lowercase / strip; try exact / substring match against `phrases`, `canonical`, `zh`, `abbreviations` (abbrev: whole-token or bounded).
3. If multiple hit, prefer longest phrase / highest specificity (exact phrase > site-only).

### SQL expansion (when concept resolved)

For column `C` (already used as `LOWER(C) LIKE …`):

```text
(
  OR over phrases: LOWER(C) LIKE '%{phrase}%'
  OR (
    (OR over sites) AND (OR over histology tokens)
  )
  OR (abbrev patterns — see below)
)
```

**Abbreviation rule (NPC, etc.):**

- SQL `LIKE '%npc%'` is too loose; prefer:

  - `LIKE '% npc %'` / leading/trailing variants, **or** application-side pmid set for abbrev path; and
  - require **also** a site token **or** a histology token in the same column/blob for metadata-wide search.

For `focus_pmid_in_clause`, continue disease-entity ∪ title paths, but both use the expanded clause (or expanded pmid set).

### Fallback (no concept)

Keep current behavior:

- Full phrase `LIKE`
- Multi-token AND of per-token `_TOKEN_SYNONYMS` (improve **bidirectional histology**: map `carcinoma`/`cancer`/`neoplasm`/`tumor`/`tumour` to the same alt list so one-way bug is fixed even for free text)

### `resolve_topic_pmids`

When concept resolves, match title **and** related entity names against expanded phrases / site∧histology (same semantics as focus), then fall back to existing full_phrase → token_score → bigrams.

## `disease_mapper` integration

- Build `DISEASE_SEARCH_KEYWORDS` / search alias list from concepts (`phrases` + `zh` + `sites` + `abbreviations` → `feasibility_keyword_zh`).
- Build mock `DISEASE_ALIASES` from `mock_disease_id` where set.
- Keep `DISEASE_NAMES` display map; add NPC entry when mock id exists, or rely on live API only for NPC if no mock id (document choice: add `NPC` mock id optional for tests).
- Prefer importing helpers from `disease_synonyms` rather than duplicating string tables.

## Public helpers (for UI / one-off counts)

- `expand_focus_terms(focus) -> dict` (phrases, sites, histology, abbrevs) for debugging / gap_ui hint.
- Optional thin `count_papers_for_focus(focus)` not required in v1 if tools already cover it.

## Files to touch

| File | Change |
|------|--------|
| `analysis/disease_synonyms.py` | **New** — concepts + histology + resolve/expand helpers |
| `analysis/focus_filter.py` | Consume concepts; bidirectional histology fallback; keep API signatures |
| `feasibility/disease_mapper.py` | Consume concepts; add NPC; reduce duplicated dicts |
| `tests/test_focus_filter.py` | Extend with cancer vs carcinoma / NPC synonym cases |
| `tests/test_disease_synonyms.py` | **New** — resolve + expand unit tests (no DB or tiny fixtures) |
| `tests/test_feasibility.py` | Ensure mapper still maps gastric etc.; add NPC alias if mock |

Docs: short note in `fulltext_workflow/PIPELINE.md` or `gap_ui_guide.md` that focus supports disease synonyms — optional, light.

## Acceptance criteria

1. Focus `nasopharyngeal carcinoma` and `nasopharyngeal cancer` produce overlapping SQL/pmid semantics (cancer not dropped when user typed carcinoma).
2. Focus `NPC` (with site/histology cue rules) intersects the NPC paper set; does not broadly match unrelated `npc` substrings inside longer tokens if avoidable.
3. On current production DB, synonym literature metadata union for NPC is about **25** (± edge FP from site∧histology); document that Disease-entity count may differ.
4. `disease_mapper` resolves NPC-oriented English/ZH text to a Fangxin search keyword (live) or mock id (tests).
5. Existing focus/gap tests still pass; new synonym unit tests green.
6. No changes to `search_queries.py` or fetch pipeline.

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| site∧histology false positives (e.g. head-and-neck CT mentioning nasopharynx + cancer) | Phrase-first in ranking/tools; document; optionally prefer title/entity over abstract for pmid clause in a follow-up |
| Abbreviation collision | Bounded match + require site or histology co-occurrence |
| Config drift if someone edits mapper only | Mapper generated from / imports synonyms module; tests fail if gastric/breast regress |
| SQL injection via focus | Keep existing `_escape_sql_like` / quoting discipline |

## Implementation notes

- Prefer **TDD**: write synonym resolve/expand tests first, then wire `focus_sql_clause`.
- Do not commit secrets or `*.db` artifacts.
- Spec approval does not imply git commit of this file unless the user requests it.

## Open follow-ups (explicitly deferred)

- Extraction-time canonicalize Disease entities to `canonical`.
- PubMed disease-augmented query groups.
- MeSH ID join tables.
