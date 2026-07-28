"""Per-study-type scholar lenses for Pass 1 section and Pass 2 reconcile prompts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StudyTypePack:
    study_type: str
    section_lens: str
    reconcile_lens: str
    prefer: tuple[str, ...]


PACKS: dict[str, StudyTypePack] = {
    "ai_algorithm": StudyTypePack(
        study_type="ai_algorithm",
        prefer=(
            "APPLIES_METHOD",
            "COMPARES_METHOD",
            "PERFORMS_TASK",
            "USES_DATASET",
            "ACHIEVES_METRIC",
        ),
        section_lens="""\
STUDY-TYPE LENS (ai_algorithm):
  Scholar focus: algorithmic contribution, target task, experimental baselines,
  train/val/test data, and reported metrics. Read methods/results as an ML paper —
  what was proposed or adopted, what was compared, on which data, with which scores.
  Prefer concrete named architectures and modules over vague "deep learning" claims.

  Emphasize:
  - APPLIES_METHOD for the paper's proposed or adopted pipeline methods only
    (backbone, framework, or named contribution-level module)
  - COMPARES_METHOD for explicit experimental baselines under the same protocol
    or with reported comparison metrics in THIS paper
  - PERFORMS_TASK for the clinical or ML objective of THIS study
  - USES_DATASET for cohorts this study actually trained/validated/tested on
  - ACHIEVES_METRIC when numeric results are stated (put value in metric_value)
  - USES_MODALITY for pathology modalities (WSI, H&E, IHC, cytology, …)

  Forbid / weaken:
  - Do NOT emit APPLIES_METHOD for background, related-work, or citation-only methods
  - Do NOT emit SURVEYS_METHOD, COVERS_DISEASE, RELEASES_DATASET, or PRETRAINS_ON
  - Do NOT treat literature-table or merely cited public sets as USES_DATASET
  - Training tricks (augmentation, optimizers, LR schedules, early stopping) are not Methods
  - Do NOT invent baselines that lack an explicit comparison setup here

  Checklist: contribution method? baselines? task? experimental datasets? metrics with values?
""",
        reconcile_lens="""\
RECONCILE LENS (ai_algorithm): dataset_mode=experimental.
  Keep only datasets this study trained/validated/tested on (role=experimental if set).
  Drop merely cited public sets, related-work tables, and bibliographic platforms
  (PubMed, PMC, Scopus, etc.). Prefer keep for named public benchmarks actually used;
  merge aliases into one canonical name from Pass 1 or known public aliases.
  Bind method–disease–dataset for the paper's own experiments when the fulltext supports it.
  No release/pretrain roles; no surveyed_methods / covered_diseases arrays.
  Limitations: keep author-stated study flaws; merge section fragments to one canonical.
""",
    ),
    "clinical_study": StudyTypePack(
        study_type="clinical_study",
        prefer=(
            "TARGETS_DISEASE",
            "PERFORMS_TASK",
            "USES_DATASET",
            "REPORTS_LIMITATION",
        ),
        section_lens="""\
STUDY-TYPE LENS (clinical_study):
  Scholar focus: cohort and disease, clinical endpoints/tasks, AI actually used in
  the study protocol, and clinical limitations. Prefer clinical framing over
  algorithm novelty. Disease at the finest stated subtype / molecular class.

  Emphasize:
  - TARGETS_DISEASE for the study cohort disease(s) — subtype/molecular class when written
  - PERFORMS_TASK for clinical or diagnostic endpoints of THIS study
  - USES_DATASET for study cohorts / evaluation sets actually used
  - REPORTS_LIMITATION for author-stated clinical constraints (sample size, single-center,
    retrospective design, lack of external validation, class imbalance, …)
  - APPLIES_METHOD only when a named method is implemented or adopted in the study
  - USES_MODALITY for pathology data types used in the cohort workflow

  Forbid / weaken:
  - Do NOT emit APPLIES_METHOD for algorithm name-dropping without study use
  - Do NOT emit SURVEYS_METHOD, COVERS_DISEASE, RELEASES_DATASET, or PRETRAINS_ON
  - Do NOT extract background epidemiology diseases unrelated to the enrolled cohort
  - Do NOT treat cited public benchmarks as USES_DATASET unless this study used them

  Checklist: disease/cohort? clinical task? AI actually used? study data? limitations?
""",
        reconcile_lens="""\
RECONCILE LENS (clinical_study): dataset_mode=experimental.
  Keep study cohorts / evaluation sets actually used (role=experimental if set).
  Prefer empty release/pretrain. Drop literature-only citations and platforms.
  Bindings should reflect clinical cohort claims (method–disease–dataset when stated);
  dataset may be empty when no named set is given.
  No surveyed_methods / covered_diseases arrays.
  Prefer keep for institutional or public cohorts the study clearly used; merge aliases.
  Limitations: canonical clinical phrasing; merge duplicate fragments.
""",
    ),
    "review": StudyTypePack(
        study_type="review",
        prefer=("COVERS_DISEASE", "SURVEYS_METHOD", "REPORTS_LIMITATION"),
        section_lens="""\
STUDY-TYPE LENS (review):
  Scholar focus: coverage of the disease/method landscape and field gaps — not a
  single experiment. Read as a survey: which diseases and methods are in scope,
  what the authors synthesize, and what gaps they state. Pack overrides the
  single-experiment framing in shared core for survey coverage.

  Emphasize:
  - COVERS_DISEASE for diseases in the survey scope (not a single-study primary target)
  - SURVEYS_METHOD for landscape / representative methods discussed (not implemented here)
  - REPORTS_LIMITATION for author-stated field-level gaps when concrete and actionable
  - PERFORMS_TASK only if the review itself frames a clear synthesis objective

  Forbid / weaken (CRITICAL — pack wins over experimental section hints):
  - Do NOT emit USES_DATASET, RELEASES_DATASET, or PRETRAINS_ON
  - Do NOT emit APPLIES_METHOD for methods only discussed or tabulated; use SURVEYS_METHOD
  - Do NOT emit TARGETS_DISEASE for survey-scope diseases; use COVERS_DISEASE
  - Do NOT emit COMPARES_METHOD for literature comparisons that are not this paper's experiment
  - Literature-table datasets are never this paper's USES_DATASET
  - Do NOT invent a primary cohort for a narrative/systematic review

  Checklist: covered diseases? surveyed methods? field gaps? zero dataset-class edges?
""",
        reconcile_lens="""\
RECONCILE LENS (review): dataset_mode=none.
  Prefer empty datasets[]; never keep literature-table or constituent-study datasets.
  Drop all dataset-class edges unless somehow present from Pass 1 — clear them.
  Map surveyed methods / covered diseases via surveyed_methods[] and covered_diseases[]
  with short evidence quotes. No bindings that attach datasets to this review paper.
  No release/pretrain roles. Limitations may be field-level gaps stated by authors
  (canonical phrases); merge overlapping fragments.
""",
    ),
    "meta_analysis": StudyTypePack(
        study_type="meta_analysis",
        prefer=("COVERS_DISEASE", "SURVEYS_METHOD", "REPORTS_LIMITATION"),
        section_lens="""\
STUDY-TYPE LENS (meta_analysis):
  Scholar focus: inclusion criteria, pooled endpoints, heterogeneity — same survey
  family as review with stricter quantitative framing. Prefer synthesis relations
  over experiment relations. Pack overrides experimental section framing.

  Emphasize:
  - COVERS_DISEASE for diseases in the inclusion / synthesis scope
  - SURVEYS_METHOD for methods appearing across included studies (not this paper's pipeline)
  - REPORTS_LIMITATION for heterogeneity, inclusion bias, or author-stated synthesis limits
  - Pooled endpoints as PERFORMS_TASK when clearly this meta-analysis's objective
  - ACHIEVES_METRIC only for pooled / summary estimates stated by the authors

  Forbid / weaken (CRITICAL — pack wins over experimental section hints):
  - Default: do NOT emit USES_DATASET / RELEASES_DATASET / PRETRAINS_ON for
    constituent-study datasets listed in tables or forest plots
  - Do NOT emit APPLIES_METHOD for surveyed methods; use SURVEYS_METHOD
  - Do NOT emit TARGETS_DISEASE for scope diseases; use COVERS_DISEASE
  - Do NOT treat included-study cohorts as this paper's USES_DATASET by default
  - Do NOT emit COMPARES_METHOD for cross-study literature contrasts

  Checklist: inclusion scope diseases? surveyed methods? pooled task? no constituent datasets?
""",
        reconcile_lens="""\
RECONCILE LENS (meta_analysis): dataset_mode=none by default — empty datasets.
  Use surveyed_methods / covered_diseases with quotes. Never keep constituent-study tables.
  Only keep a dataset if authors ran their own pooled/self-analysis on a named cohort:
  action=keep, role=experimental, and reason contains "self-analysis" or
  "pooled analysis by the authors". Otherwise drop all datasets.
  No release/pretrain roles. No method–disease–dataset bindings that imply experimental use
  of constituent cohorts. Limitations: heterogeneity / inclusion limits when stated.
""",
    ),
    "dataset_benchmark": StudyTypePack(
        study_type="dataset_benchmark",
        prefer=(
            "RELEASES_DATASET",
            "PERFORMS_TASK",
            "COMPARES_METHOD",
            "ACHIEVES_METRIC",
        ),
        section_lens="""\
STUDY-TYPE LENS (dataset_benchmark):
  Scholar focus: released data contribution, annotation/protocol, benchmark tasks,
  and baseline comparisons on the released (or evaluation) set. Distinguish the
  dataset THIS paper contributes from prior public sets it merely cites.

  Emphasize:
  - RELEASES_DATASET for the dataset THIS paper contributes or releases
  - PERFORMS_TASK for benchmark tasks defined or evaluated here
  - COMPARES_METHOD for baselines run on the benchmark
  - ACHIEVES_METRIC for reported scores (metric_value when numeric)
  - USES_DATASET only for sets this paper experimentally uses (not auto-remap from release;
    release and use may coexist when both are true)
  - APPLIES_METHOD only if authors also propose a method evaluated on the benchmark

  Forbid / weaken:
  - Do NOT confuse merely cited public sets with the released contribution
  - Do NOT emit SURVEYS_METHOD, COVERS_DISEASE, or PRETRAINS_ON
  - Do NOT emit RELEASES_DATASET for datasets only mentioned as prior work
  - Do NOT emit USES_DATASET for sets that appear only in related-work citations

  Checklist: what was released? protocol/tasks? baselines? metrics? cited-only vs released?
""",
        reconcile_lens="""\
RECONCILE LENS (dataset_benchmark): dataset_mode=release_ok.
  Mark released contribution with role=release → RELEASES_DATASET.
  Experimental use → role=experimental → USES_DATASET.
  Do not keep merely cited public sets as this paper's release; drop or leave unknown
  only when they were experimental use with clear evidence.
  Merge aliases of the released set when Pass 1 fragmented names.
  No surveyed_methods / covered_diseases; no pretrain role.
  Bindings may link method–disease–released/eval dataset when stated in fulltext.
""",
    ),
    "foundation_model": StudyTypePack(
        study_type="foundation_model",
        prefer=(
            "APPLIES_METHOD",
            "PRETRAINS_ON",
            "PERFORMS_TASK",
            "USES_DATASET",
        ),
        section_lens="""\
STUDY-TYPE LENS (foundation_model):
  Scholar focus: pretraining corpus, model contribution, and transfer / downstream
  tasks. Separate pretrain pools from finetune/eval sets. Policy enables PRETRAINS_ON
  as the only new relation for this type (not RELEASES_DATASET).

  Emphasize:
  - APPLIES_METHOD for the foundation model / pipeline proposed or adopted here
  - PRETRAINS_ON for pretraining corpora / large unlabeled pools
  - PERFORMS_TASK for pretrain objectives and downstream transfer tasks
  - USES_DATASET for finetune / evaluation sets (not the pretrain pool)
  - COMPARES_METHOD for baselines compared on downstream tasks
  - ACHIEVES_METRIC when downstream or pretrain metrics are reported

  Forbid / weaken:
  - Do NOT mark all downstream or cited methods as APPLIES_METHOD — only the model /
    pipeline proposed or adopted in THIS paper; baselines → COMPARES_METHOD
  - Do NOT emit SURVEYS_METHOD or COVERS_DISEASE
  - Do NOT emit RELEASES_DATASET (enable_new is PRETRAINS_ON only; dataset papers use
    dataset_benchmark). Even if a corpus is named, prefer PRETRAINS_ON / USES_DATASET
  - Do NOT label pretrain corpora as USES_DATASET or eval sets as PRETRAINS_ON

  Checklist: pretrain data (PRETRAINS_ON)? model APPLIES? downstream tasks? eval USES?
""",
        reconcile_lens="""\
RECONCILE LENS (foundation_model): dataset_mode=pretrain_ok.
  Pretraining corpora → role=pretrain → PRETRAINS_ON.
  Finetune/eval → role=experimental → USES_DATASET.
  Do not conflate pretrain pools with eval sets; do not use role=release.
  No surveyed_methods / covered_diseases. No RELEASES_DATASET.
  Merge aliases within pretrain vs eval groups separately when possible.
  Bindings: method–disease–eval dataset when transfer experiments are stated; avoid
  binding the pretrain pool as an experimental USES_DATASET.
""",
    ),
    "multimodal": StudyTypePack(
        study_type="multimodal",
        prefer=(
            "USES_MODALITY",
            "APPLIES_METHOD",
            "PERFORMS_TASK",
            "USES_DATASET",
        ),
        section_lens="""\
STUDY-TYPE LENS (multimodal):
  Scholar focus: modality set, fusion / cross-modal method, and per-modality data
  and tasks. Prefer extracting multiple modalities when the study is truly multimodal.
  Keep pathology modality preference from shared core (do not promote radiology-as-
  primary when pathology is present).

  Emphasize:
  - Multiple USES_MODALITY edges for each pathology (or stated) modality used
    (e.g. WSI + IHC, H&E + spatial transcriptomics)
  - APPLIES_METHOD for fusion / multimodal pipeline methods adopted or proposed
  - PERFORMS_TASK for tasks tied to the multimodal study
  - USES_DATASET for experimental datasets (possibly per-modality cohorts)
  - COMPARES_METHOD for baselines compared in THIS paper's multimodal experiments
  - ACHIEVES_METRIC when multimodal results are reported

  Forbid / weaken:
  - Avoid single-modality under-extraction when several modalities are stated
  - Do NOT emit SURVEYS_METHOD, COVERS_DISEASE, RELEASES_DATASET, or PRETRAINS_ON
  - Do NOT invent modalities not stated in the section
  - Do NOT extract CT/MRI as primary Modality when pathology modalities are present

  Checklist: all modalities? fusion method? per-modality datasets/tasks? metrics?
""",
        reconcile_lens="""\
RECONCILE LENS (multimodal): dataset_mode=experimental.
  Keep per-modality experimental datasets; ensure bindings cover fusion claims when stated.
  Prefer keep for named public sets actually used; drop citation-only and platforms.
  No release/pretrain roles; no surveyed_methods / covered_diseases arrays.
  Merge aliases; do not invent modality-specific dataset names absent from Pass 1.
  Limitations: author-stated multimodal constraints (missing modality, unpaired data, …).
""",
    ),
    "other": StudyTypePack(
        study_type="other",
        prefer=(),
        section_lens="""\
STUDY-TYPE LENS (other):
  Scholar focus: only clearly stated study facts. Prefer sparse triples; when
  uncertain, omit. No rich genre-specific semantics — shared core only.

  Emphasize:
  - Shared-core relations only when evidence is explicit in the section
  - Disease / Task / Method / Dataset / Limitation / Modality when unambiguously
    THIS study's content
  - Prefer finest stated disease subtype; prefer named Methods over umbrellas

  Forbid / weaken:
  - Do NOT emit SURVEYS_METHOD, COVERS_DISEASE, RELEASES_DATASET, or PRETRAINS_ON
    (all four new relations denied for other)
  - Do NOT invent contribution edges from vague or background wording
  - Prefer omit over guess for borderline related-work mentions
  - Do NOT force an experimental narrative if the paper genre is unclear

  Checklist: is the fact clearly this study's content? If not, omit.
""",
        reconcile_lens="""\
RECONCILE LENS (other): dataset_mode=experimental; prefer conservative keep/drop.
  No surveyed_methods / covered_diseases; no release/pretrain roles unless evidence
  is unambiguous (default: omit new roles). Drop uncertain datasets rather than keep.
  Bindings only when method–disease–dataset is explicit. Merge aliases carefully;
  do not invent names. Limitations: only author-stated concrete flaws.
""",
    ),
}
