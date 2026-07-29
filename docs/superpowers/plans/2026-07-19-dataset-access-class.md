# Dataset access_class Implementation Plan

> **For agentic workers:** Implement task-by-task.

**Goal:** Label Dataset entities `public|private|unknown` (alias list first), expose in tools, Fangxin-first proposal rules.

**Spec:** `docs/superpowers/specs/2026-07-19-dataset-access-class-design.md`

**Tech:** Python, SQLite, pydantic, pytest

## Global Constraints

- Keep `USES_DATASET`; add `entities.access_class` only.
- Precedence: public > private > unknown.
- Do not commit unless user asks.

---

### Task 1: `resolve_dataset_access` + tests

**Files:** Create `fulltext_workflow/extractor/dataset_access.py`; tests in `tests/test_dataset_access.py`

### Task 2: Schema + upsert_entity

**Files:** `db/schema.py` — migrate column; upsert with upgrade

### Task 3: Wire extract save path

**Files:** `section_extractor.py`, `entity_normalize.py` (optional normalize name), `GRANULARITY.md`

### Task 4: Idea agent tools + prompts

**Files:** `idea_agent.py` (+ gap_agent if same tool)

### Task 5: Verify pytest
