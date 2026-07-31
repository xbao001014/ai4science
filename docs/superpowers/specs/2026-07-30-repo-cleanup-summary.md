# Repo Cleanup Summary — 2026-07-30

## Pytest

Command: `.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests -q --tb=line`

Result: **288 passed in 26.81s**

Notes:
- Unit test sources under `fulltext_workflow/tests/` were retained (41 `test_*.py` files).
- System Anaconda Python failed collection on `test_parse_date.py` (`ModuleNotFoundError: Bio`); the project `.venv` is the correct runner.
- Recent KG SQL focused suites previously reported green in SDD final-fix reports (historical context before deleting `.superpowers/sdd/`).

## Deletions

Removed **80** local artifact paths/trees:

| Category | Removed |
|----------|---------|
| Pytest cache | `.pytest_cache/`, `fulltext_workflow/.pytest_cache/` |
| `__pycache__` | Root + `fulltext_workflow/**` (13 trees; venvs untouched) |
| Test / bench DBs | `test_*.db` (7), `_bench_reach.db*` (3) |
| SDD scratch | Entire `.superpowers/` |
| Worktrees | Entire `.worktrees/` |
| Stale `output/` | Reports, pilot CSV/logs, ops_proposal_*, KG HTML/GEXF/CSV, weekly hotspot (53 files) |

## Kept (verified)

- `fulltext_workflow/tests/` → True
- `fulltext_workflow/data/kg_fulltext.db` → True
- `fulltext_workflow/raw/` → True
- `fulltext_workflow/output/extraction_demo.html` → True
- `fulltext_workflow/output/updates_since_20260723.pptx` → True
- `docs/superpowers/specs/`, `docs/superpowers/plans/` → True
- `.superpowers` / `.worktrees` → absent
- Remaining `test_*.db` / non-venv `__pycache__` → 0

## Not done (by design)

- No commit / push
- No `.gitignore` changes
- No deletion of unit test sources, `raw/`, or main DB
