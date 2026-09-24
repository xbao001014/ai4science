# Entity context pilot: 30 original papers

## Purpose

Compare extraction before and after retaining source-grounded, paper-local
entity context. This is a descriptive paired pilot, not a blinded accuracy
estimate. The same 30 stored original full texts are used on both sides;
`entity_context_30.py compare` refuses a source-text hash mismatch.

## Stages

1. Freeze 30 papers and their current active entity relations before editing.
   Select across available study types, prioritizing papers with short Method
   names and limiting core extraction text to 1,000–12,000 characters per
   paper so the model trial can finish within request limits. Keep the baseline
   JSON unchanged.
2. In an isolated SQLite backup, run the updated extractor for those PMIDs.
   Each located evidence quote gains its source sentence. Explicit method
   `long form (SHORT)` definitions are collected within the same paper. An
   unmatched or ambiguous abbreviation stays unknown.
3. Produce a paired CSV with added, removed and retained entity relations.
   Keep original and new quotes and the new context side by side.
4. Have an expert review changes, including false merges, missing entities,
   wrong relation roles, unsupported facts, and whether the saved context
   disambiguates short Method names. Fill `expert_correct_before` and
   `expert_correct_after`; do not infer quality from row-count changes alone.
5. Only after the pilot review, extend structured context to Metric evaluation
   results, Disease qualifiers and Dataset roles. Keep the active taxonomy
   release unchanged until an independent Method classification evaluation.

## Pilot commands

Run from `fulltext_workflow/` with project Python. `pilot.db` must be an
SQLite backup of `data/kg_fulltext.db` made *before* re-extraction. Point
`config.DB_PATH` to that backup when calling `run_extraction` for the 30 PMIDs.

```powershell
..\.venv\Scripts\python.exe evals\entity_context_30.py freeze `
  --db data\kg_fulltext.db --output ..\tmp\entity_context_30\before.json

..\.venv\Scripts\python.exe evals\entity_context_30.py compare `
  --before ..\tmp\entity_context_30\before.json `
  --after-db ..\tmp\entity_context_30\pilot.db `
  --output ..\tmp\entity_context_30\comparison
```

## Review criteria

- Entity and relation correctness by type, before versus after.
- Method long-form correctness and percentage of short names with an explicit
  source-grounded expansion.
- Evidence support: the quote and context must refer to the same paper and
  actually support the claimed relation.
- No unsupported expansion, subtype, numeric metric or dataset access claim.
- New entities count as gains only when expert-reviewed as correct; removed
  entities count as gains only when the previous entity was incorrect.

Keep this pilot isolated from the production database. A new embedding input
format changes cache hashes; classify in shadow mode and evaluate independently
before considering an active release update.
