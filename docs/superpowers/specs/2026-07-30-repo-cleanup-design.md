# Repo Cleanup Design — 2026-07-30

## Goal

全面梳理仓库，**保留项目主体**；对测试相关本地副产物先汇总结果再删除；清理无用产出，不触碰业务代码与单元测试源码。

## Decisions (approved)

| Topic | Choice |
|-------|--------|
| Unit tests (`fulltext_workflow/tests/`) | **Keep** |
| Local data (`raw/`, `kg_fulltext.db`, `jcr.csv`) | **Keep** |
| `output/` retention | Keep only `extraction_demo.html` and `updates_since_20260723.pptx` |
| Approach | Local sweep only (no `.gitignore` changes, no delete of raw/main DB) |

## Keep (project body)

- All application code under `fulltext_workflow/` and root helpers (`search_queries.py`, `llm_utils.py`, etc.)
- `fulltext_workflow/tests/**` (unit tests)
- `docs/superpowers/specs/**` and `docs/superpowers/plans/**`
- `fulltext_workflow/raw/`, `fulltext_workflow/data/kg_fulltext.db`, `jcr.csv`, `demo_extraction_pmids.txt`, `.gitkeep` files
- Runtime env: `.env`, `.venv`, `.conda` (do not touch)
- `output/extraction_demo.html`, `output/updates_since_20260723.pptx`

## Delete (local artifacts)

1. `.pytest_cache/` at repo root and under `fulltext_workflow/`
2. All `__pycache__/` directories under the repo (excluding `.venv` / `.conda` if present)
3. `fulltext_workflow/data/test_*.db` and `fulltext_workflow/data/_bench_reach.db*`
4. Entire `.superpowers/` tree (SDD scratch: reports, diffs, briefs) — formal docs live under `docs/superpowers/`
5. `.worktrees/` if present and only scratch
6. Everything in `fulltext_workflow/output/` except the two keep files above

## Process

1. Run `pytest fulltext_workflow/tests -q` and record pass/fail summary.
2. Write a short cleanup summary note (test results + what was deleted) into this cleanup track — either as a section appended below after execution, or a sibling file `2026-07-30-repo-cleanup-summary.md`.
3. Execute deletions per the delete list.
4. Do **not** commit or push unless the user explicitly requests it.
5. Do **not** change business logic or delete unit test source files.

## Out of scope

- Deleting or rewriting unit tests
- Removing `raw/` or the main SQLite DB
- Changing `.gitignore`
- Committing/pushing
- Touching secrets or virtualenvs

## Success criteria

- Unit test suite still present and runnable
- Pytest summary captured before cache deletion
- Listed local artifacts removed; keep list intact
- No tracked product code deleted
