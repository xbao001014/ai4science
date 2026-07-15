# Task 1: Config + schema + pure fingerprint helpers

**Files:**
- Modify: `fulltext_workflow/config.py`
- Modify: `fulltext_workflow/db/schema.py` (SCHEMA_SQL + `_migrate_db`)
- Create: `fulltext_workflow/analysis/ops_memory.py` (pure helpers first)
- Create: `fulltext_workflow/tests/test_ops_memory.py`

**Interfaces to produce:**
- `config.OPS_MEMORY_ENABLED: bool`
- `config.OPS_MEMORY_LOOKBACK_RUNS: int` (default 4)
- `config.OPS_MEMORY_JACCARD_THRESHOLD: float` (default 0.55)
- `config.OPS_MEMORY_SECTION_MAX_CHARS: int` (default 8192)
- `normalize_focus_key(focus: str | None) -> str`
- `tokenize_for_fingerprint(text: str) -> list[str]`
- `fingerprint_gap_title(title: str) -> str`
- `jaccard_overlap(a: str, b: str) -> float`

## Step 1: Write failing tests

Create `fulltext_workflow/tests/test_ops_memory.py` with tests for normalize_focus_key, fingerprint_gap_title, jaccard_overlap as in plan.

Set `config.DB_PATH = str(_ROOT / "data" / "test_ops_memory.db")` before imports.

## Step 2: Run tests — expect FAIL

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

## Step 3: Add config knobs after hotspot knobs in config.py

```python
# Weekly ops memory (gap soft-dedup + persist)
OPS_MEMORY_ENABLED: bool = os.getenv("OPS_MEMORY_ENABLED", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
OPS_MEMORY_LOOKBACK_RUNS: int = int(os.getenv("OPS_MEMORY_LOOKBACK_RUNS", "4"))
OPS_MEMORY_JACCARD_THRESHOLD: float = float(
    os.getenv("OPS_MEMORY_JACCARD_THRESHOLD", "0.55")
)
OPS_MEMORY_SECTION_MAX_CHARS: int = int(
    os.getenv("OPS_MEMORY_SECTION_MAX_CHARS", "8192")
)
```

## Step 4: Implement pure helpers in ops_memory.py (see plan for full code)

## Step 5: Add ops_* DDL to SCHEMA_SQL AND inside _migrate_db executescript block

Tables: ops_runs, ops_gap_items, ops_proposals with indexes as in plan.

## Step 6: Re-run tests — all PASS

## DO NOT git commit (user did not request commits)

Write full report to `.superpowers/sdd/task-1-report.md`
