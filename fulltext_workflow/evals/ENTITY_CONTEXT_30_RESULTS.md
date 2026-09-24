# Entity context pilot: 30-paper result

## Sample and reproducibility

- Fixed PMIDs: `entity_context_30_pmids.txt` (8 AI algorithm, 8 clinical study,
  7 meta-analysis, 7 review papers).
- The source text hash for every paper matched before and after extraction.
- One originally selected review (PMID 41331191) timed out on a 10,480-character
  Methods section, including a separate 180-second retry. It was replaced by
  PMID 41516254, a review with 3,539 core-section characters. This makes the
  pilot more feasible but biases it toward shorter source sections.
- Baseline and after-run databases are separate SQLite backups. The production
  database and active Method-family release were not changed.
- All final 30 papers completed extraction; final-sample audits contain no
  `exception` or `unresolved_empty` outcomes.

## Descriptive result

| Entity type | Before | After | Added | Removed |
|---|---:|---:|---:|---:|
| Method | 398 | 322 | 61 | 137 |
| Disease | 88 | 78 | 19 | 29 |
| Dataset | 58 | 35 | 12 | 35 |
| Metric | 97 | 86 | 41 | 52 |
| Task | 119 | 88 | 29 | 60 |
| Limitation | 189 | 196 | 153 | 146 |
| Modality | 56 | 38 | 8 | 26 |
| Tissue | 1 | 3 | 3 | 1 |
| **All relations** | **1,006** | **846** | **326** | **486** |

Of the original relations, 520 retained the same PMID, relation type, entity
type, normalized name and metric value. These counts are **not accuracy
measurements**: the baseline was generated earlier, and a fresh LLM extraction
can change names and omissions even without a contextual schema change.

## Context result

- An offline pass over the unchanged old entities located source context for
  804 of 1,006 relations (79.9%). Unmatched old quotes were left unfilled.
- The fresh extraction saved context on 779 of 846 active relations (92.1%).
  Pass-2 reconcile relations account for much of the remaining gap.
- Eight fresh relations contain a source-grounded Method long form. Examples:
  GCN → graph convolutional network; HIPT → Hierarchical image pyramid
  transformer. An absent or conflicting definition remains unknown.
- This establishes improved **traceability and contextual completeness** for
  the sampled records. It does not establish better Method-family accuracy or
  better entity precision/recall.

## Review before wider rollout

Use `../tmp/entity_context_30/online-final-comparison/changes_only.csv`
(from `fulltext_workflow/`) for added and removed entities, `short_methods.csv`
for abbreviation review, and `papers.csv` to identify the
papers with the most changes. In particular, check whether removed named
Methods and Datasets are true false positives or recall regressions. Some
new Method names are generic, so a count-based acceptance rule would be unsafe.
Record correctness and notes in `entity_diff.csv`; the columns are ready for
expert labels.

Keep production re-extraction and the active taxonomy release unchanged until
the changed entities have been reviewed. The next schema stage should connect
Metric values to the evaluated Method, Dataset and Task, and preserve Disease
qualifiers and Dataset role per paper mention.
