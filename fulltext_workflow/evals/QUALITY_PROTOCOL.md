# Phase 2: measurable extraction and research judgments

## Frozen design

- 16 extraction cases × 3 trials: 12 controlled synthetic cases spanning all eight
  study types; 4 short original public-paper abstract excerpts. These are NOT full
  papers and do not sample the production distribution.
- 12 closed-evidence research cases × 3 trials: 3 scoped supported opportunities,
  3 direct counterexamples, 6 insufficient-evidence cases. All packs are synthetic.
- Labels and grader are created before baseline, then reused unchanged. Source,
  fixture and runner hashes are recorded per version, along with immutable request
  messages and raw model responses. This is a diagnostic development set, not an
  unseen holdout. No expert adjudication has occurred: label tier = silver.
- Configured extraction/agent models are preserved. Temperature 0.1 / 0.3,
  output cap 2400 tokens, 3 workers, randomized task order using fixed seed,
  retries disabled; maximum 120 SDK requests per run. Error cases remain in results.
- Only synthetic or explicitly cited public snippets go to model APIs. SQLite
  connections are restricted to a temporary directory; no clinical API is called.

The final candidate adds a bounded second extraction pass ONLY for an empty
structured output in an experimental study type with an explicit first-person
experiment cue. Errors/parse failures are not semantically retried. Both calls
count against the same request cap. This trades possible extra usage for recall;
the cap is not a guarantee of identical per-case spend across versions.

## Extraction grading

Each example declares the relation families under evaluation and exhaustive gold
facts for those families. Every output in those families counts, including unknown
names (false positives). Other relation families are retained in traces but not
scored. This is **targeted relation precision/recall**, not full-KG precision.

Normalize punctuation/case; compare predeclared aliases as whole phrases. Metrics
compare numeric values, treating e.g. 93.09% and 0.9309 as equivalent. Deduplicate
identical facts; one gold fact can produce at most one true positive. Report TP,
FP, FN, micro P/R/F1, and results separately for source excerpts vs synthetic data.

Evidence location checks whether the stated quote is a contiguous substring of
the supplied section after whitespace normalization. Paraphrases or spliced
ellipsis quotes fail. This verifies location, NOT entailment. Grounded precision
and recall require BOTH gold-fact match AND quote location. Empty output is not
rewarded for positive examples because recall falls. Track empty-negative cases
and errors separately; no invented value for undefined denominators.

## Research grading

The question is whether the **scientific gap claim is established in the supplied
scope**, not whether the wording is rhetorically sound:

- supported -> verified_gaps: direct evidence supports a still-open, scoped
  opportunity, with no in-scope pre-cutoff counterexample. Not proof of global novelty.
- refuted -> false_gaps: a direct same-disease/task empirical counterexample, or
  a directly contradicted factual claim.
- insufficient -> weak_evidence_gaps: unknown search coverage, failed query,
  unrelated evidence, missing temporal coverage, or an unsupported universal claim.
  An invalid inference alone is not proof that the underlying topic is already solved.

Each input has exactly ONE candidate. It must appear in exactly one bucket. A
rewritten weaker proposal must not be emitted as a second candidate; a mixed
classification is invalid under this output contract. This is important when
interpreting baseline mixed-bucket failures: several contain reasonable prose but
do not provide a unique machine-readable judgment.

Measure 3-class accuracy/macro F1/confusion matrix, required evidence-ID coverage,
unknown cited IDs, false-supported rate, supported-opportunity recall, and correct
abstention. Citation-ID correctness does NOT alone prove semantic support. Gold
decision labels provide a separate, limited semantic reference.

## Interpretation

Baseline and improved runs are sequential, not randomized version A/B. Three
repeats do not create three independent scientific topics. Report paired deltas
and optional bootstrap intervals resampling case IDs (all trials stay grouped).
Do not claim statistical significance, deployment accuracy, independent scholarly
novelty or clinical utility from this small development set.

Next external validation: domain reviewers audit/edit silver labels with reasons;
collect real full-paper sections and evidence packs with date/scope coverage;
seal a new paper-level holdout that is not used for prompt revisions. The original
SCIENTIFIC_RUBRIC.md describes this larger expert phase.
