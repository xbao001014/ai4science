# Scientific evaluation protocol (proposed; not scored in v1)

## Unit and split

Use the project's eight study types as strata. Start with 64 legally accessible,
de-identified papers (8 per type); split 32 development / 32 held-out by paper ID,
not by paragraph. Keep related versions in the same split. Record corpus snapshot,
retrieval date and extraction prompt/model hashes. Add 24 gap evidence packs:
8 supported opportunities, 8 refuted by existing work, 8 insufficient-coverage
cases. These counts are proposed starting budgets, not a statistical power claim.

Each paper annotation includes study type, normalized triples, supporting section
and exact evidence spans, and negative/background/baseline facts. Each gap pack
includes scope, search cut-off date, coverage counts, positive and refuting papers,
and the correct epistemic label. A negative search is not proof of global absence.

## Independent adjudication

Two domain reviewers annotate independently; resolve disagreements with a third
reviewer and retain both original labels. Report agreement by criterion. Do not
let the same model generate and certify its own truth labels. A model judge can
assist only after calibration against expert decisions; randomize A/B order and
blind system version. Generated examples must be marked synthetic, never gold.

## Metrics (separate; no single weighted score)

1. Extraction: normalized exact triple precision/recall/F1, macro F1 by relation
   and study type; evidence-span support; background-to-own-method confusion.
2. Retrieval: recall@k against judged relevant papers; citation-ID validity;
   exact disease/task scope adherence. Recall is relative to the judged pool.
3. Gap reasoning: false-gap fraction among claimed supported gaps, opportunity
   recall among supported gold opportunities, appropriate abstention rate on
   insufficient evidence, refutation incorporation, temporal cut-off compliance.
4. Proposal: evidence-linked claim precision, experimental falsifiability,
   baseline/ablation clarity, feasible data/annotation requirements, practical
   usefulness and diversity. Human 1–5 scores with explicit anchors:
   1 = generic/unverifiable or infeasible; 3 = relevant but missing a key design
   decision; 5 = testable, evidence-linked and implementable with stated resources.
5. System: tool execution/argument/scope fidelity, unverified acceptance count,
   errors, retries, final-output validity, tokens, latency and calls per task.

Report critical failures as vetoes. Better prose cannot offset invented cohort
sizes or false claims of completed verification. Also report coverage/abstention,
so a system that refuses everything cannot win by reducing false acceptance.

## Proposed gates and cadence

- Every change: all critical offline cases pass; no new selected-regression
  failure relative to recorded baseline. Existing failures remain visible.
- Prompt/model release: same pinned evidence packs and model settings; >=3 trials
  per live case; preserve every error in the denominator and store traces.
- Scientific pilot: proposed citation-ID validity 100%, evidence precision >=95%,
  false-gap rate <=10%, and no deterioration in opportunity recall or blinded
  proposal utility. Domain owners must approve these thresholds after first gold
  annotation; they are not already achieved results.
- Use paired bootstrap intervals at paper/pack level, not treating repeated
  trials of one pack as independent papers. Small samples cannot establish
  equivalence or statistical significance. No significance claim for v1.
- Weekly: review failures and new real-world edge cases; add only to development
  set. Rotate a sealed holdout after a release, never tune on its failures and
  continue calling it unseen. Track model/provider drift as a separate factor.

## Gold JSONL record template

```json
{"id":"PAPER-001","split":"holdout","is_synthetic":false,
 "paper_id":"REPLACE_WITH_VERIFIED_ID","study_type":"REPLACE_WITH_PROJECT_ENUM",
 "corpus_snapshot":"REQUIRED","search_cutoff":"YYYY-MM-DD",
 "input_path":"LOCAL_APPROVED_TEXT","expected_triples":[],
 "forbidden_claims":[],"evidence_spans":[],
 "reviewers":[],"adjudication_status":"pending"}
```

Empty/pending records are annotation work items, not scored examples. Do not
upload private clinical data to a judge or model without explicit authorization.
