# Final Fix Report — weekly new_methods (C1)

**Date:** 2026-09-07  
**Status:** PASS

## C1 (Critical) — pre-slice dropped nascent methods

**Root cause:** `compute_new_methods` passed `HOTSPOT_NEW_METHODS_MAX` into `compute_emerging_entities`, which sorts by `emerging_score` DESC and slices before the nascent maturity filter. At wide windows or low caps, high-heat non-nascent methods consumed the pool and lowest-corpus nascent rows never reached the board.

**Fix:** Use `_NEW_METHODS_POOL_UNCAPPED = 1_000_000` for the emerging-entity fetch; apply `nascent[: HOTSPOT_NEW_METHODS_MAX]` only after nascent filter + corpus-paper sort.

## Minor

- Added `st.subheader("新苗头")` above the 新苗头 caption in `gap_ui.py` tab_m.
- Added `test_report_empty_new_methods_shows_none` for report "None" placeholder.

## Tests

```powershell
cd fulltext_workflow
python -m pytest tests/test_weekly_hotspot_new_methods.py tests/test_weekly_hotspot_maturity.py tests/test_weekly_hotspot_method_role.py -v
```

**Result:** 15 passed in 11.28s

**TDD (C1 regression):**

- RED (buggy code): `test_new_methods_max_applied_after_nascent_sort_not_emerging_pool` → `assert 0 == 1` (LLM filled limit=1 slot; nascent filter yielded `[]`).
- GREEN (fix applied): same test PASSED; retained row is `one-paper-nascent` with `corpus_paper_cnt=1`.

## Files changed

- `fulltext_workflow/analysis/weekly_hotspot.py`
- `fulltext_workflow/tests/test_weekly_hotspot_new_methods.py`
- `fulltext_workflow/gap_ui.py`

## Concerns

- Uncapped pool (1M) is a sentinel, not unbounded SQL; performance unchanged vs prior 500 cap on typical corpora. Very large method sets could still benefit from a DB-side nascent query later (out of scope).
