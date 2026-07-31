# Repo Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Summarize pytest results, then delete approved local artifacts while keeping unit tests, main DB, raw/, and two output files.

**Architecture:** Operational cleanup only — no product code changes. Run the full unit suite first, persist a summary markdown, then delete caches / SDD scratch / test DBs / stale output per the approved spec.

**Tech Stack:** PowerShell, pytest, local filesystem under `d:\agent\prototype\build_kg_paper`

## Global Constraints

- Keep `fulltext_workflow/tests/**` (do not delete unit test sources)
- Keep `raw/`, `kg_fulltext.db`, `jcr.csv`, `.env`, `.venv`, `.conda`
- Keep `output/extraction_demo.html` and `output/updates_since_20260723.pptx`
- Do not change business logic or `.gitignore`
- Do not commit or push unless the user explicitly asks
- Spec: `docs/superpowers/specs/2026-07-30-repo-cleanup-design.md`

## File map

| Path | Role |
|------|------|
| `docs/superpowers/specs/2026-07-30-repo-cleanup-summary.md` | Create: pytest + deletion summary |
| `.pytest_cache/`, `fulltext_workflow/.pytest_cache/` | Delete |
| `__pycache__/` trees (exclude `.venv`/`.conda`) | Delete |
| `fulltext_workflow/data/test_*.db`, `_bench_reach.db*` | Delete |
| `.superpowers/` | Delete entire tree |
| `.worktrees/` | Delete if present |
| `fulltext_workflow/output/*` except two keep files | Delete |

---

### Task 1: Run pytest and write summary

**Files:**
- Create: `docs/superpowers/specs/2026-07-30-repo-cleanup-summary.md`

**Interfaces:**
- Consumes: existing `fulltext_workflow/tests/`
- Produces: summary markdown with pass/fail counts for Task 2 verification

- [ ] **Step 1: Run the full unit suite**

```powershell
cd d:\agent\prototype\build_kg_paper
python -m pytest fulltext_workflow/tests -q --tb=no
```

Expected: a final line like `N passed` or `N passed, M failed, ...` (record exact output).

- [ ] **Step 2: Write the summary file**

Create `docs/superpowers/specs/2026-07-30-repo-cleanup-summary.md` with:

```markdown
# Repo Cleanup Summary — 2026-07-30

## Pytest

Command: `python -m pytest fulltext_workflow/tests -q --tb=no`

Result: <paste exact summary line>

Notes:
- Unit test sources under `fulltext_workflow/tests/` were retained.
- Recent KG SQL focused suites previously reported green in SDD final-fix reports (historical).

## Deletions

(filled in Task 2)
```

- [ ] **Step 3: Verify summary file exists and tests directory still present**

```powershell
Test-Path docs\superpowers\specs\2026-07-30-repo-cleanup-summary.md
(Get-ChildItem fulltext_workflow\tests\test_*.py).Count
```

Expected: `True` and a positive test file count (≈40).

---

### Task 2: Delete approved local artifacts

**Files:**
- Delete: caches, test DBs, `.superpowers/`, stale `output/` files
- Modify: `docs/superpowers/specs/2026-07-30-repo-cleanup-summary.md` (append deletion list)

**Interfaces:**
- Consumes: keep-list from Task 1 / spec
- Produces: cleaned tree; updated summary Deletions section

- [ ] **Step 1: Delete pytest caches**

```powershell
cd d:\agent\prototype\build_kg_paper
Remove-Item -Recurse -Force .pytest_cache, fulltext_workflow\.pytest_cache -ErrorAction SilentlyContinue
```

- [ ] **Step 2: Delete `__pycache__` outside venvs**

```powershell
Get-ChildItem -Path . -Recurse -Directory -Filter __pycache__ |
  Where-Object { $_.FullName -notmatch '\\\.venv\\|\\\.conda\\' } |
  Remove-Item -Recurse -Force
```

- [ ] **Step 3: Delete test/bench DBs**

```powershell
Remove-Item -Force fulltext_workflow\data\test_*.db, fulltext_workflow\data\_bench_reach.db* -ErrorAction SilentlyContinue
```

- [ ] **Step 4: Delete SDD scratch and worktrees**

```powershell
Remove-Item -Recurse -Force .superpowers, .worktrees -ErrorAction SilentlyContinue
```

- [ ] **Step 5: Prune `output/` keeping two files**

```powershell
Get-ChildItem fulltext_workflow\output -File |
  Where-Object { $_.Name -notin @('extraction_demo.html','updates_since_20260723.pptx') } |
  Remove-Item -Force
```

- [ ] **Step 6: Verify keep-list intact**

```powershell
@(
  'fulltext_workflow\tests',
  'fulltext_workflow\data\kg_fulltext.db',
  'fulltext_workflow\raw',
  'fulltext_workflow\output\extraction_demo.html',
  'fulltext_workflow\output\updates_since_20260723.pptx',
  'docs\superpowers\specs',
  'docs\superpowers\plans'
) | ForEach-Object { "$_ -> $(Test-Path $_)" }
Test-Path .superpowers
(Get-ChildItem fulltext_workflow\output -File).Name
```

Expected: keep paths `True`; `.superpowers` `False`; output only the two keep files.

- [ ] **Step 7: Append deletion results to the summary file**

Update the `## Deletions` section with what was removed and confirmation that keep-list survived.

- [ ] **Step 8: Do not commit** unless the user asks.

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Run pytest before deleting caches | Task 1 |
| Write summary | Task 1 + Task 2 Step 7 |
| Delete caches / pycache / test DBs / `.superpowers` / `.worktrees` / stale output | Task 2 |
| Keep tests, raw, main DB, two output files, docs | Task 2 Step 6 |
| No commit / no business logic / no gitignore change | Global Constraints + Task 2 Step 8 |
