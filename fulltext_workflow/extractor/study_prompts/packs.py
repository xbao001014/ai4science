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
  Read for algorithmic contribution, task, baselines, experimental data, and metrics.
  Prefer APPLIES_METHOD, COMPARES_METHOD, PERFORMS_TASK, USES_DATASET, ACHIEVES_METRIC.
  Do NOT emit APPLIES_METHOD for background / related-work methods — only proposed or
  adopted pipeline methods. Baselines → COMPARES_METHOD. Do NOT emit SURVEYS_METHOD,
  COVERS_DISEASE, RELEASES_DATASET, or PRETRAINS_ON.
""",
        reconcile_lens="""\
RECONCILE LENS (ai_algorithm): dataset_mode=experimental.
  Keep only datasets this study trained/validated/tested on. Bind method–disease–dataset
  for the paper's own experiments. No release/pretrain roles; no survey/cover arrays.
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
  Read for cohort/disease, clinical endpoints/tasks, AI actually used in the study,
  and clinical limitations.
  Prefer TARGETS_DISEASE, PERFORMS_TASK, USES_DATASET, REPORTS_LIMITATION.
  Do NOT emit APPLIES_METHOD for algorithm name-dropping without study use.
  Do NOT emit SURVEYS_METHOD, COVERS_DISEASE, RELEASES_DATASET, or PRETRAINS_ON.
""",
        reconcile_lens="""\
RECONCILE LENS (clinical_study): dataset_mode=experimental.
  Keep study cohorts / evaluation sets actually used. Prefer empty release/pretrain.
  Bindings should reflect clinical cohort claims; no survey/cover arrays.
""",
    ),
    "review": StudyTypePack(
        study_type="review",
        prefer=("COVERS_DISEASE", "SURVEYS_METHOD", "REPORTS_LIMITATION"),
        section_lens="""\
STUDY-TYPE LENS (review):
  Read as a survey: coverage of diseases/methods and field gaps — not a single experiment.
  Prefer COVERS_DISEASE and SURVEYS_METHOD. Do NOT emit USES_DATASET / RELEASES_DATASET /
  PRETRAINS_ON. Do NOT emit APPLIES_METHOD for methods only discussed; use SURVEYS_METHOD.
  Limitations may be field-level gaps stated by authors.
""",
        reconcile_lens="""\
RECONCILE LENS (review): prefer empty datasets; map surveyed methods/diseases via
surveyed_methods / covered_diseases arrays. Never keep literature-table datasets.
""",
    ),
    "meta_analysis": StudyTypePack(
        study_type="meta_analysis",
        prefer=("COVERS_DISEASE", "SURVEYS_METHOD", "REPORTS_LIMITATION"),
        section_lens="""\
STUDY-TYPE LENS (meta_analysis):
  Read for inclusion criteria, pooled endpoints, and heterogeneity — survey family with
  stricter quantitative framing.
  Prefer COVERS_DISEASE and SURVEYS_METHOD; field/study limitations via REPORTS_LIMITATION.
  Default: do NOT emit USES_DATASET / RELEASES_DATASET / PRETRAINS_ON for constituent-study
  datasets. Do NOT emit APPLIES_METHOD for surveyed methods; use SURVEYS_METHOD.
""",
        reconcile_lens="""\
RECONCILE LENS (meta_analysis): dataset_mode=none by default — empty datasets.
  Use surveyed_methods / covered_diseases. Only keep a dataset if authors ran their own
  pooled/self-analysis on a named cohort (action=keep, role=experimental, reason contains
  "self-analysis" or "pooled analysis by the authors"). Never keep constituent-study tables.
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
  Read for released data, protocol, benchmark tasks, and baselines.
  Prefer RELEASES_DATASET, PERFORMS_TASK, COMPARES_METHOD, ACHIEVES_METRIC.
  USES_DATASET only for sets this paper experimentally uses (not auto-remap from release).
  Do NOT confuse cited public sets with the released set. Do NOT emit SURVEYS_METHOD,
  COVERS_DISEASE, or PRETRAINS_ON.
""",
        reconcile_lens="""\
RECONCILE LENS (dataset_benchmark): dataset_mode=release_ok.
  Mark released contribution with role=release → RELEASES_DATASET; experimental use →
  role=experimental → USES_DATASET. Do not keep merely cited public sets as this paper's
  release. No survey/cover arrays; no pretrain role.
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
  Read for pretrain data, model contribution, and transfer/downstream tasks.
  Prefer APPLIES_METHOD, PRETRAINS_ON, PERFORMS_TASK, USES_DATASET (finetune/eval).
  Do NOT mark all downstream methods as APPLIES_METHOD — only the foundation model /
  pipeline proposed or adopted here. Do NOT emit SURVEYS_METHOD, COVERS_DISEASE, or
  RELEASES_DATASET unless the paper clearly releases a dataset.
""",
        reconcile_lens="""\
RECONCILE LENS (foundation_model): dataset_mode=pretrain_ok.
  Pretraining corpora → role=pretrain → PRETRAINS_ON; finetune/eval → role=experimental →
  USES_DATASET. Do not conflate pretrain pools with eval sets. No survey/cover arrays.
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
  Read for modality set, fusion method, and per-modality data/tasks.
  Prefer multiple USES_MODALITY edges, APPLIES_METHOD, PERFORMS_TASK, USES_DATASET.
  Avoid single-modality under-extraction. Keep pathology modality preference from shared
  core (do not promote radiology-as-primary when pathology is present).
  Do NOT emit SURVEYS_METHOD, COVERS_DISEASE, RELEASES_DATASET, or PRETRAINS_ON.
""",
        reconcile_lens="""\
RECONCILE LENS (multimodal): dataset_mode=experimental.
  Keep per-modality experimental datasets; ensure bindings cover fusion claims when stated.
  No release/pretrain roles; no survey/cover arrays.
""",
    ),
    "other": StudyTypePack(
        study_type="other",
        prefer=(),
        section_lens="""\
STUDY-TYPE LENS (other):
  Extract only clearly stated study facts; prefer sparse triples when uncertain — omit.
  Use shared-core relations only. Do NOT emit SURVEYS_METHOD, COVERS_DISEASE,
  RELEASES_DATASET, or PRETRAINS_ON.
""",
        reconcile_lens="""\
RECONCILE LENS (other): dataset_mode=experimental; prefer conservative keep/drop.
  No survey/cover arrays; no release/pretrain roles unless evidence is unambiguous
  (default: omit new roles).
""",
    ),
}
