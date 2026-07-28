"""Per-study-type policy matrix for relation allow/deny/remap."""
from __future__ import annotations

from dataclasses import dataclass

from extractor.triple_models import Triple

DATASET_RELATIONS: frozenset[str] = frozenset(
    {"USES_DATASET", "RELEASES_DATASET", "PRETRAINS_ON"}
)
NEW_RELATIONS: frozenset[str] = frozenset(
    {"SURVEYS_METHOD", "COVERS_DISEASE", "RELEASES_DATASET", "PRETRAINS_ON"}
)


@dataclass(frozen=True)
class StudyPolicy:
    deny: frozenset[str]
    remap: dict[str, str]
    prefer: tuple[str, ...]
    dataset_mode: str
    enable_new: frozenset[str]


_EMPTY: frozenset[str] = frozenset()
_REVIEW_ENABLE: frozenset[str] = frozenset({"SURVEYS_METHOD", "COVERS_DISEASE"})
_REVIEW_REMAP: dict[str, str] = {
    "APPLIES_METHOD": "SURVEYS_METHOD",
    "TARGETS_DISEASE": "COVERS_DISEASE",
}

_POLICIES: dict[str, StudyPolicy] = {
    "ai_algorithm": StudyPolicy(
        deny=_EMPTY,
        remap={},
        prefer=(
            "APPLIES_METHOD",
            "COMPARES_METHOD",
            "PERFORMS_TASK",
            "USES_DATASET",
            "ACHIEVES_METRIC",
        ),
        dataset_mode="experimental",
        enable_new=_EMPTY,
    ),
    "clinical_study": StudyPolicy(
        deny=_EMPTY,
        remap={},
        prefer=(
            "TARGETS_DISEASE",
            "PERFORMS_TASK",
            "USES_DATASET",
            "REPORTS_LIMITATION",
        ),
        dataset_mode="experimental",
        enable_new=_EMPTY,
    ),
    "review": StudyPolicy(
        deny=DATASET_RELATIONS,
        remap=dict(_REVIEW_REMAP),
        prefer=("COVERS_DISEASE", "SURVEYS_METHOD", "REPORTS_LIMITATION"),
        dataset_mode="none",
        enable_new=_REVIEW_ENABLE,
    ),
    "meta_analysis": StudyPolicy(
        deny=DATASET_RELATIONS,
        remap=dict(_REVIEW_REMAP),
        prefer=("COVERS_DISEASE", "SURVEYS_METHOD", "REPORTS_LIMITATION"),
        dataset_mode="none",
        enable_new=_REVIEW_ENABLE,
    ),
    "dataset_benchmark": StudyPolicy(
        deny=_EMPTY,
        remap={},
        prefer=(
            "RELEASES_DATASET",
            "PERFORMS_TASK",
            "COMPARES_METHOD",
            "ACHIEVES_METRIC",
        ),
        dataset_mode="release_ok",
        enable_new=frozenset({"RELEASES_DATASET"}),
    ),
    "foundation_model": StudyPolicy(
        deny=_EMPTY,
        remap={},
        prefer=("APPLIES_METHOD", "PRETRAINS_ON", "PERFORMS_TASK", "USES_DATASET"),
        dataset_mode="pretrain_ok",
        enable_new=frozenset({"PRETRAINS_ON"}),
    ),
    "multimodal": StudyPolicy(
        deny=_EMPTY,
        remap={},
        prefer=("USES_MODALITY", "APPLIES_METHOD", "PERFORMS_TASK", "USES_DATASET"),
        dataset_mode="experimental",
        enable_new=_EMPTY,
    ),
    "other": StudyPolicy(
        deny=NEW_RELATIONS,
        remap={},
        prefer=(),
        dataset_mode="experimental",
        enable_new=_EMPTY,
    ),
}


def get_policy(study_type: str | None) -> StudyPolicy:
    if study_type is None or study_type not in _POLICIES:
        return _POLICIES["other"]
    return _POLICIES[study_type]


def apply_policy(triples: list[Triple], study_type: str | None) -> list[Triple]:
    import config

    if not config.STUDY_POLICY_ENABLED:
        return list(triples)
    policy = get_policy(study_type)
    out: list[Triple] = []
    for t in triples:
        rel = t.relation
        if rel in policy.deny:
            continue
        if policy.dataset_mode == "none" and rel in DATASET_RELATIONS:
            continue
        if rel in policy.remap:
            if rel == "TARGETS_DISEASE":
                q = (t.evidence_quote or "").strip()
                if not q:
                    continue
            rel = policy.remap[rel]
            t = t.model_copy(update={"relation": rel})
        if rel in NEW_RELATIONS and rel not in policy.enable_new:
            continue
        if rel in policy.deny:
            continue
        out.append(t)
    return out
