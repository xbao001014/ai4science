# Method abbreviation prompt: 30-paper pilot

## Change under test

The section extraction prompt now receives explicit `long form (SHORT)`
definitions found in the same paper, restricted to abbreviations appearing in
the current section. The system prompt says they may clarify a Method acronym
but cannot establish a relation, replace current-section evidence, or justify
an inferred expansion. Grounded Method names still retain their separate
source context and explicit long form from the preceding stage.

## Paired run

The baseline is the completed 30-paper context pilot database
(`tmp/entity_context_30/pilot_short.db`), before this prompt change. The new
run used `evals/run_prompt_context_30.py` and a separate SQLite backup. All
30 PMIDs and source-text SHA-256 hashes matched. No production database or
active Method-family release was changed. The new run finished without
`exception` or `unresolved_empty` section outcomes. There were six ordinary
model-empty section outcomes.

| Entity type | Before | After | Added | Removed |
|---|---:|---:|---:|---:|
| Method | 322 | 343 | 82 | 61 |
| Disease | 78 | 71 | 7 | 14 |
| Dataset | 35 | 31 | 10 | 14 |
| Metric | 86 | 80 | 17 | 23 |
| Task | 88 | 67 | 24 | 45 |
| Limitation | 196 | 182 | 105 | 119 |
| Modality | 38 | 51 | 18 | 5 |
| Tissue | 3 | 4 | 3 | 2 |
| **All** | **846** | **829** | **266** | **283** |

563 relations retained the same PMID, relation, type, normalized name and
metric value. Of the short single-token Method rows, 41 were added and 18
removed. Source-grounded Method long forms remained at eight after extraction.
The generated comparison is in
`tmp/entity_context_30/prompt-context-30/comparison/`; `changes_only.csv`
and `short_methods.csv` are the main review files.

## Observations requiring review

- A deterministic reconstruction of the prompt payload finds 132 distinct
  paper-abbreviation pairs exposed across 29 papers. Many are not Methods
  (for example AI, CT, AUC, NPV, and WHO). This is too broad for a
  Method-specific disambiguation aid.
- Some new names are less precise than their previous counterparts:
  PMID 34914727 changed `cytology triage` and `via triage` to bare
  `cytology` and `via`; PMID 35098562 changed `endoscopist diagnosis` to
  `endoscopists`. PMID 41529075 added `quadas-2` as a surveyed Method,
  although its quote describes a quality/risk-of-bias assessment tool.
- PMID 38243703 moved GCN, TAG, GATv2, SAGE, SuperGAT and UniMP from
  `APPLIES_METHOD` to `COMPARES_METHOD`. The old quote describes them as
  recommended graph networks, so this role change needs full-paper review.
- PMID 42434758 added Grad-CAM variants as applied Methods, but its results
  section rejected 14 of 16 candidates because the proposed evidence quotes
  could not be located. Similar quote-location losses occurred in PMID
  41028908 Methods (10 rejected) and PMID 41945805 Methods (7 rejected).

## Decision

This run shows that the prompt changes extraction behavior, but it does not
establish better entity precision or recall. Some reviewed examples are clear
quality regressions, and repeated LLM extraction can vary even at temperature
zero. The prompt is gated by `EXTRACT_METHOD_CONTEXT_PROMPT`, which defaults to
false; the evaluation runner enabled it only in the isolated run. Before rollout,
restrict the supplemental glossary to plausible Method definitions and obtain
expert labels for changed rows, especially short names, relation roles and
false Method types. Then rerun the same fixed sample with that single change.
