# Final Review Fix Report

## Fixed findings

- Canonical method×disease hotspot combinations now aggregate distinct recent and
  prior PMID sets before scoring and persistence.  Alias rows therefore produce
  one stable snapshot key.
- Parenthetical method names now collapse only when the inner term is the
  head's acronym or an explicit curated synonym.  Unrelated architecture/base
  model names such as `unet++ (resnet-50)` remain unchanged.
- The method-cluster audit precomputes normalized data, skeletons, tokens, and
  resolved names, then compares only names sharing a skeleton token.  It ranks
  the suggested canonical by paper frequency before length, and excludes
  established/generic umbrella targets.
- Non-Method top-PMID lookup retains a SQL name predicate, and empty method
  metric buckets cannot divide by zero.

## Verification

- Required pytest command: 20 passed in 5.14s.
- Timed real-data smoke used a read-only SQLite backup of
  `fulltext_workflow/data/kg_fulltext.db`; the source database was not opened
  for writes.  The audit processed 6,670 Method entities and returned 50
  candidates in 6.021s.

# Final Whole-Branch Review Fixes

## Fix notes

- Added a UI and Markdown-report note that the first method-board WoW transition after novelty gating can reclassify established methods as `Cooled`, without indicating a true decline.
- Documented `HOTSPOT_ESTABLISHED_MIN_PAPERS=10` in `.env.example` and `PIPELINE.md`, and refreshed the opportunity-score formula with context novelty, maturity penalty, nascent bonus, and the actionability bump.
- Added frequency-tier integration coverage: a method with ten `APPLIES_METHOD` papers is retained in `active_methods` as established but excluded from `emerging_methods`; a recent niche method remains emerging.
- Omitted the established-method appendix heading when it has no rows, lazily load corpus counts only for unannotated hot-method rows, and added a maturity-ranking note to the hot-combo UI tab.

## Test results

```text
D:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_method_maturity.py fulltext_workflow/tests/test_weekly_hotspot_maturity.py fulltext_workflow/tests/test_transferable_opportunities.py fulltext_workflow/tests/test_weekly_hotspot.py -v
17 passed in 2.90s
```
