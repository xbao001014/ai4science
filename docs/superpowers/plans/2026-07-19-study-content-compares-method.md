# Study-content + COMPARES_METHOD Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** Prefer this paper’s study content for Paper→X extraction, and split Method into `APPLIES_METHOD` (contribution) vs `COMPARES_METHOD` (experimental baselines).

**Architecture:** Prompt policy in `section_extractor.py`; relation schema in `triple_models.py`; deterministic filters/conflict rules in `entity_normalize.py`; docs + quality script.

**Tech Stack:** Python, Pydantic, pytest, existing SQLite relations table (no migration).

**Spec:** `docs/superpowers/specs/2026-07-19-study-content-compares-method-design.md`

## Global Constraints

- No DB migration; `relations.relation` is free text.
- Object-type repair maps Method → `APPLIES_METHOD` only (never auto `COMPARES_METHOD`).
- Same Method under both relations → keep `APPLIES_METHOD`, drop `COMPARES_METHOD`.
- Ban `COMPARES_METHOD` in introduction/discussion/future_work (same as APPLIES).
- Do not commit unless the user asks.

---

### Task 1: Relation schema + postprocess rules

**Files:**
- Modify: `fulltext_workflow/extractor/triple_models.py`
- Modify: `fulltext_workflow/extractor/entity_normalize.py`
- Modify: `fulltext_workflow/tests/test_entity_normalize.py`
- Modify: `fulltext_workflow/tests/test_triple_models.py`

- [ ] Add `COMPARES_METHOD` to `RelationLiteral` and `_RELATION_EXPECTED_OBJECT`
- [ ] Apply Method filters + section ban to `COMPARES_METHOD`
- [ ] Prefer `APPLIES_METHOD` over `COMPARES_METHOD` for same method name
- [ ] Tests covering the above

### Task 2: Prompt study-content policy

**Files:**
- Modify: `fulltext_workflow/extractor/section_extractor.py`
- Modify: `fulltext_workflow/extractor/GRANULARITY.md`

- [ ] Global study-content rules + `COMPARES_METHOD` in relation list/examples/section hints
- [ ] Document in GRANULARITY.md

### Task 3: Quality script

**Files:**
- Modify: `fulltext_workflow/scripts/compare_extraction_quality.py`

- [ ] Print/count both Method relation columns

### Task 4: Verify

- [ ] `pytest tests/test_triple_models.py tests/test_entity_normalize.py -q`
