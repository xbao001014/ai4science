# Task 1 Report: Config + Schema + Pure Fingerprint Helpers

**Date:** 2026-07-15  
**Status:** DONE  
**Scope:** Task 1 only (no Task 2+ APIs)

---

## Summary

Implemented weekly ops memory foundations:

- Four `OPS_MEMORY_*` config knobs in `config.py`
- Pure fingerprint helpers in `analysis/ops_memory.py`
- `ops_runs`, `ops_gap_items`, `ops_proposals` DDL in `SCHEMA_SQL` and `_migrate_db`
- Five unit tests in `tests/test_ops_memory.py`

All helper tests pass (5/5). Schema smoke check confirmed all three `ops_*` tables are created on `init_db()`.

---

## Files Changed

| File | Action |
|------|--------|
| `fulltext_workflow/config.py` | Modified — added `OPS_MEMORY_*` knobs after hotspot section |
| `fulltext_workflow/db/schema.py` | Modified — appended `ops_*` DDL to `SCHEMA_SQL` and `_migrate_db` executescript |
| `fulltext_workflow/analysis/ops_memory.py` | Created — pure helpers only |
| `fulltext_workflow/tests/test_ops_memory.py` | Created — 5 unit tests |

**Not changed (per scope):** `gap_agent.py`, `gap_ui.py`, `pipeline.py`, CRUD helpers, persist/load API (Task 2+).

---

## Interfaces Delivered

### Config (`config.py`)

- `OPS_MEMORY_ENABLED: bool` (default on; env `OPS_MEMORY_ENABLED`)
- `OPS_MEMORY_LOOKBACK_RUNS: int` (default 4)
- `OPS_MEMORY_JACCARD_THRESHOLD: float` (default 0.55)
- `OPS_MEMORY_SECTION_MAX_CHARS: int` (default 8192)

### Pure helpers (`analysis/ops_memory.py`)

- `normalize_focus_key(focus: str | None) -> str`
- `tokenize_for_fingerprint(text: str) -> list[str]`
- `fingerprint_gap_title(title: str) -> str`
- `jaccard_overlap(a: str, b: str) -> float`

### Schema (`db/schema.py`)

Tables and indexes per plan:

- `ops_runs` + `idx_ops_runs_focus_finished`, `idx_ops_runs_week`
- `ops_gap_items` + `idx_ops_gap_run`, `idx_ops_gap_fp`
- `ops_proposals` + `idx_ops_prop_run`

---

## TDD Evidence

### RED — failing tests before implementation

**Command:**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

**Output (after tests written, before `ops_memory.py` existed):**

```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.1.1, pluggy-1.6.0
collecting ... collected 0 items / 1 error

=================================== ERRORS ====================================
__________________ ERROR collecting tests/test_ops_memory.py __________________
ImportError while importing test module '...\tests\test_ops_memory.py'.
tests\test_ops_memory.py:16: in <module>
    from analysis.ops_memory import (
E   ModuleNotFoundError: No module named 'analysis.ops_memory'
=========================== short test summary info ===========================
ERROR tests/test_ops_memory.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.82s ===============================
```

**Failure reason:** Expected — module `analysis.ops_memory` did not exist yet.

**Note:** `pytest` was not installed in `.venv`; installed via `pip install pytest` before RED run (not in `requirements.txt`).

---

### GREEN — all tests pass after implementation

**Command:**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

**Output:**

```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.1.1, pluggy-1.6.0
collecting ... collected 5 items

tests/test_ops_memory.py::test_normalize_focus_key_empty_is_all PASSED   [ 20%]
tests/test_ops_memory.py::test_normalize_focus_key_lower_strip PASSED    [ 40%]
tests/test_ops_memory.py::test_fingerprint_stable_and_order_invariant PASSED [ 60%]
tests/test_ops_memory.py::test_jaccard_identical_high PASSED             [ 80%]
tests/test_ops_memory.py::test_jaccard_unrelated_low PASSED              [100%]

============================== 5 passed in 0.12s ==============================
```

---

### Schema verification (manual smoke)

Verified `init_db()` creates `ops_gap_items`, `ops_proposals`, `ops_runs` on a fresh test DB (`data/test_ops_memory_schema.db`). Import order matters: set `config.DB_PATH` before `from db.schema import init_db` because `db.schema.DB_PATH` is bound at import time.

---

## Test Summary

| Test | Result |
|------|--------|
| `test_normalize_focus_key_empty_is_all` | PASS |
| `test_normalize_focus_key_lower_strip` | PASS |
| `test_fingerprint_stable_and_order_invariant` | PASS |
| `test_jaccard_identical_high` | PASS |
| `test_jaccard_unrelated_low` | PASS |

**Total: 5 passed, 0 failed**

---

## Concerns

1. **pytest not in `requirements.txt`** — Had to `pip install pytest` in `.venv` to run tests as specified. Consider adding `pytest` to dev dependencies for reproducibility.

2. **`db.schema.DB_PATH` import-time binding** — Tests that need a custom DB must set `config.DB_PATH` *before* importing `db.schema` (pattern already used in `test_gap_lifecycle.py`). Task 2 persist/load tests will need the same discipline.

3. **No automated schema DDL test in pytest suite** — Task 1 tests cover pure helpers only; schema DDL was verified manually. Task 2 tests will exercise schema via CRUD.

---

## Git

No commit performed (user did not request). Test DB files under `data/test_ops_memory*.db` were created locally and should not be committed.
