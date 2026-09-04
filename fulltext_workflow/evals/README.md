# Evidence-first evaluation v1

This suite separates deterministic harness reliability, live-model behavior on
synthetic evidence, and scientific quality. The last category requires expert
gold labels and is explicitly **not measured** by this release.

## Frozen protocol

- Offline: 28 targeted diagnostic cases, unchanged before/after. Real orchestration,
  scripted completions, synthetic tools, temporary database, network denied.
- Live: six cases × two independent trials per version; four critic/tool-evidence
  cases and two synthetic section-extraction cases. No production papers or patient
  records. At most 40 explicit SDK calls per version; no automatic SDK retry.
- Existing regression: 15 selected test modules, temporary DB, no network.
- Changes may be developed against this diagnostic set. It is NOT an unseen holdout.
- Critical failures are reported individually and cannot be offset by writing quality.
- API/environment errors are reported separately, not silently removed from denominators.
- Offline timing is not a measurement of live inference speed.

## Commands (from repository root)

Use a **fresh output directory** for each run:

```powershell
.\.venv\Scripts\python.exe fulltext_workflow\evals\run_eval.py --label baseline --output tmp\eval\baseline
.\.venv\Scripts\python.exe fulltext_workflow\evals\run_live_eval.py --label baseline --output tmp\eval\live-baseline
.\.venv\Scripts\python.exe fulltext_workflow\evals\run_regression.py --output tmp\eval\regression-baseline
```

Only run the live command with authority to use the configured API. It sends only
the checked-in synthetic fixtures, but incurs provider usage. API keys are never
written to the result files. Store traces locally; do not publish clinical data.

## Next scientific-quality phase

See `SCIENTIFIC_RUBRIC.md` for annotation units, split, reviewers, metric
definitions and proposed gates. `check_release.py` provides a nonzero exit code
for offline failures, missing legacy tests or regressions against a recorded
baseline. The frozen `run_eval.py` itself records failures without a nonzero exit;
use the gate for CI. `build_report.py` creates reports and the evidence bundle;
`validate_report.py` performs static artifact checks, not visual browser QA.

Known live trace limitation in v1: responses are retained per call, but the
messages list is mutable and may serialize as the final conversation. It is not
an exact per-request snapshot. Keep the frozen suite for this comparison; a next
version should deepcopy messages at call time before collecting a new baseline.

Build an expert-adjudicated paper set stratified across the eight study types,
with PMID-level train/holdout separation, evidence spans and negative/background
facts. Then add scoped gap evidence packs with supporting and refuting papers,
search cut-off date, corpus coverage, and actionable/non-actionable labels.
Measure relation precision/recall, claim support, false-gap rate, opportunity
discovery and blinded proposal usefulness. Do not treat critic self-scores or
this harness pass rate as scientific novelty/clinical efficacy measurements.
