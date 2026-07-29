# Design: ZH–EN Focus Synonyms + Offline UMLS Alignment

**Date:** 2026-07-15  
**Status:** Approved (awaiting implementation)  
**Parent / merge-into:** [`2026-07-15-disease-synonyms-design.md`](2026-07-15-disease-synonyms-design.md)  
**Scope:** Fix Chinese focus (e.g. `肠息肉`) returning 0 papers against an English PubMed-backed KG by local concept expansion; optional offline UMLS CUI as stable ID. **Single implementation** with the disease-synonyms work — not a parallel dictionary.

## Problem

Corpus titles and Disease entities are almost entirely English. `focus_filter` today does literal `LIKE '%{focus}%'` (plus English token synonym expansion for multi-word Latin strings).

Empirical on current `kg_fulltext.db` (~9417 papers):

| Focus | Approx. `focus_subset.papers` |
|-------|-------------------------------|
| `colorectal polyp` | ~33 |
| `肠息肉` | **0** |

Chinese focus never expands to English aliases, so Gap UI / agents report empty coverage and refuse useful analysis.

## Goals

- Resolve common **Chinese (and English) disease aliases** to one local concept.
- Expand SQL / pmid focus matching via **English phrases** (and controlled site∧token rules), not Chinese substrings alone.
- Store optional **`umls_cui`** for audit / future enrichment; **UMLS is offline-only (Approach A)** — no runtime API.
- Reject runtime vector search for v1; defer as optional fallback if needed later.
- Satisfy parental disease-synonyms acceptance (NPC, cancer↔carcinoma, mapper) **plus** colorectal polyp / 肠息肉.

## Non-goals

- Online UMLS / NLM API during Gap Debate or Streamlit.
- Embedding / FAISS / Chromadb focus retrieval.
- Changing PubMed ingest queries.
- Rewriting all KG entity names to CUIs.

## Decisions

| Topic | Choice |
|-------|--------|
| ZH↔EN | Local concept table (`zh` + `phrases`) |
| UMLS | Offline CUI field; optional enrich script later |
| Vector | Deferred |
| Module | Extend `analysis/disease_synonyms.py` (same as parent spec) |

## Data model additions (parent fields remain)

| Field | Purpose |
|-------|---------|
| `umls_cui` | Optional stable ID, e.g. curated CUI for colorectal polyp concept |

### New initial concept (required for this bug)

**`colorectal_polyp`**

- `canonical`: `colorectal polyp`
- `umls_cui`: optional (document chosen CUI when curated; empty OK for first ship)
- `phrases` (minimum): `colorectal polyp`, `colorectal polyps`, `colonic polyp`, `colon polyp`, `intestinal polyp`, `colorectal adenoma` (adenoma co-listed for recall; document FP risk vs nasal/gallbladder polyps — prefer phrase + colorectal site)
- `zh` (minimum): `肠息肉`, `结肠息肉`, `直肠息肉`, `结直肠息肉`
- `sites`: `colon`, `colorectal`, `rectal`, `intestinal` (as needed for site∧token path)
- Tokens for polyp class: prefer **phrase-first**; optional site ∧ (`polyp`|`adenoma`) with **site restricted to colorectal/colonic/colon/rectal** to avoid nasal/gallbladder polyps
- `feasibility_keyword_zh`: e.g. `肠息肉` or Fangxin-appropriate colorectal keyword if catalog supports it

Parent v1 cancers (gastric, lung, CRC adenocarcinoma, HCC, breast, NPC) stay; ensure each has useful `zh` entries where already listed.

## Matching (delta vs parent)

Same resolve / expand / fallback as parent, with emphasis:

1. **Chinese single-phrase focus** (no spaces): match against `zh` list (exact or full-string equality after strip); do not rely on English `split()` token path.
2. When concept resolves, SQL expansion uses **English `phrases` ∪ `canonical`** (and site∧rules). Do **not** require the Chinese string to appear in title/abstract.
3. UI may show resolved English label + optional CUI + approximate paper count from existing coverage tool.

## Gap UI

- On focus change / before debate: if concept resolves, show English caption e.g.  
  `Resolved: colorectal polyp · N papers` (optional CUI suffix).
- If focus contains CJK and resolve fails:  
  `No synonym mapping — try an English disease name`.
- No new UI dependencies.

## Offline UMLS (optional tooling)

- Non-blocking for v1 ship: CUIs may be blank.
- Optional later: `scripts/umls_enrich_concepts.py` (UTS key in env) that, given `phrases`/`zh`, suggests CUI + synonym strings for human review into `disease_synonyms.py`.
- Never call UMLS from `focus_filter` / agents.

## Files to touch (delta / merged list)

Same as parent, plus:

| File | Change |
|------|--------|
| `analysis/disease_synonyms.py` | Concepts incl. `colorectal_polyp` + `umls_cui` |
| `analysis/focus_filter.py` | Consume resolve/expand; ZH path |
| `gap_ui.py` | Resolve caption for focus |
| `tests/test_disease_synonyms.py` | Resolve `肠息肉` → `colorectal_polyp`; expand contains english polyp phrases |
| `tests/test_focus_filter.py` | SQL/pmid semantics: Chinese focus not empty-expansion vs English baseline |
| Parent doc | Cross-link this extension |

## Acceptance criteria

1. **Primary:** Focus `肠息肉` yields `focus_subset.papers` in the same order of magnitude as Focus `colorectal polyp` on current DB (~30+, **not 0**). Exact equality not required if controlled FP filtering differs slightly.
2. Focus `结肠息肉` / `结直肠息肉` resolve to the same concept.
3. English `colorectal polyp` does not regress vs pre-change behavior.
4. Unrelated `鼻息肉` / `gallbladder polyps` style noise is **bounded** (phrase-first; no bare `%polyp%` over full corpus).
5. Parent disease-synonyms acceptance criteria still hold.
6. No runtime UMLS; no vector index in v1.

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Adenoma phrases over-broaden into carcinoma-heavy CRC | Prefer `colorectal polyp` phrases first; adenoma as secondary; measure paper count before ship |
| Nasal / gallbladder / endometrial polyps | Site constraint + phrase-first; unit tests that bare `polyp` without colorectal site is not used alone |
| Focus key for ops memory still Chinese while English run is different lane | Document: ops memory keyed by user input string; optional future normalize to `concept_id` |
| CUI wrong/outdated | Optional field; never block resolve |

## Implementation notes

- Implement **once** with parent disease-synonyms plan (do not duplicate modules).
- TDD: ZH resolve + expand before wiring SQL.
- Prefer extending existing synonym plan tasks rather than a second parallel plan if both land together.

## Open follow-ups

- Vector fallback for unmapped free-text ZH.
- Runtime optional UMLS (rejected for ops cadence).
- Normalize `ops_runs.focus_key` to `concept_id`.
