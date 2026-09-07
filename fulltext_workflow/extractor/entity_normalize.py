"""Post-processing for extracted Method / Limitation / Disease entities."""
from __future__ import annotations

import re

from extractor.dataset_access import is_literature_platform, normalize_dataset_name
from extractor.study_policy import DATASET_RELATIONS, apply_policy, get_policy
from extractor.triple_models import Triple

_GENERIC_METHODS = frozenset(
    {
        "ai",
        "artificial intelligence",
        "deep learning",
        "dl",
        "machine learning",
        "machine learning algorithms",
        "ml",
        "radiomics",
        "pathomics",
        "computational pathology",
        "digital pathology",
        "neural network",
        "neural networks",
        "statistical analysis",
        "statistical methods",
    }
)

# Training / engineering routines — never research-contribution Methods (B policy).
_LOW_VALUE_METHODS = frozenset(
    {
        "early stopping",
        "early-stopping",
        "early stop",
        "data augmentation",
        "data augmentations",
        "image augmentation",
        "image augmentations",
        "augmentation",
        "augmentations",
        "adam",
        "adam optimizer",
        "adamw",
        "adamw optimizer",
        "sgd",
        "sgd optimizer",
        "rmsprop",
        "learning rate",
        "learning rate schedule",
        "learning rate scheduling",
        "cosine annealing",
        "cosine annealing schedule",
        "warmup",
        "warm-up",
        "learning rate warmup",
        "batch size",
        "mini-batch size",
        "dropout",
        "weight decay",
        "l2 regularization",
        "l2 weight decay",
        "gradient clipping",
        "gradient clip",
        "transfer learning",
        "fine-tuning",
        "finetuning",
        "fine tuning",
        "pretraining",
        "pre-training",
        "pretrained",
        "pre-trained",
        "hyperparameter tuning",
        "hyperparameter optimization",
        "hyper-parameter tuning",
        "cross validation",
        "cross-validation",
        "k-fold cross validation",
        "k-fold cross-validation",
        "random flip",
        "random crop",
        "color jitter",
        "mixup",
        "cutmix",
        "cutout",
        "mosaic augmentation",
        "horizontal flip",
        "vertical flip",
        "rotation augmentation",
        "checkpointing",
        "model checkpointing",
        "early stopping callback",
    }
)

_LOW_VALUE_METHOD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\bearly\s*-?\s*stop",
        r"\bdata\s+augment",
        r"\bimage\s+augment",
        r"\blearning\s+rates?\b",
        r"\blr\s+schedule",
        r"\bweight\s+decay\b",
        r"\bgradient\s+clip",
        r"\bhyper[\s-]?parameters?\b",
        r"\bbatch\s+sizes?\b",
        r"\bcolor\s+jitter\b",
        r"\brandom\s+(flip|crop|rotation)s?\b",
        r"\b(adam|adamw|sgd|rmsprop)\s+optimizer\b",
    )
)

# Bare clinical umbrellas — never keep as Disease (policy C).
_GENERIC_DISEASES = frozenset(
    {
        "cancer",
        "cancers",
        "tumor",
        "tumour",
        "tumors",
        "tumours",
        "malignancy",
        "malignancies",
        "neoplasm",
        "neoplasms",
        "carcinoma",
        "carcinomas",
        "malignant tumor",
        "malignant tumour",
        "malignant neoplasm",
        "cancerous lesion",
        "solid tumor",
        "solid tumour",
    }
)

# Organ-level parents dropped when a finer same-organ Disease is present.
_ORGAN_LEVEL_DISEASES = frozenset(
    {
        "breast cancer",
        "lung cancer",
        "gastric cancer",
        "stomach cancer",
        "colorectal cancer",
        "colon cancer",
        "rectal cancer",
        "prostate cancer",
        "liver cancer",
        "hepatic cancer",
        "cervical cancer",
        "ovarian cancer",
        "pancreatic cancer",
        "thyroid cancer",
        "nasopharyngeal cancer",
        "nasopharyngeal carcinoma",
        "renal cancer",
        "kidney cancer",
        "bladder cancer",
        "endometrial cancer",
        "uterine cancer",
        "esophageal cancer",
        "oesophageal cancer",
        "nsclc",
        "non-small cell lung cancer",
        "non small cell lung cancer",
        "sclc",
        "small cell lung cancer",
        "crc",
        "hcc",
        "npc",
    }
)

_ORGAN_HINTS: dict[str, tuple[str, ...]] = {
    "breast": ("breast",),
    "lung": ("lung", "nsclc", "sclc", "pulmonary"),
    "colorectal": ("colorectal", "colon", "rectal", "crc"),
    "gastric": ("gastric", "stomach"),
    "prostate": ("prostate",),
    "liver": ("liver", "hepatic", "hcc", "hepatocellular"),
    "cervical": ("cervical", "cervix"),
    "ovarian": ("ovarian", "ovary"),
    "pancreatic": ("pancreatic", "pancreas"),
    "thyroid": ("thyroid",),
    "nasopharyngeal": ("nasopharyngeal", "npc"),
    "renal": ("renal", "kidney"),
    "bladder": ("bladder", "urothelial"),
    "endometrial": ("endometrial", "uterine"),
    "esophageal": ("esophageal", "oesophageal"),
    "melanoma": ("melanoma",),
}

# Histology phrases that imply an organ when the organ word is omitted.
_HISTOLOGY_TO_ORGAN: dict[str, str] = {
    "invasive ductal carcinoma": "breast",
    "invasive lobular carcinoma": "breast",
    "ductal carcinoma in situ": "breast",
    "lobular carcinoma in situ": "breast",
    "invasive ductal": "breast",
    "invasive lobular": "breast",
}

_SUBTYPE_MARKERS = re.compile(
    r"\b("
    r"adenocarcinoma|squamous|ductal|lobular|mucinous|papillary|clear[\s-]?cell|"
    r"invasive|in\s+situ|sarcoma|lymphoma|melanoma|"
    r"her2|msi|mmr|egfr|alk|kras|braf|ros1|ntrk|"
    r"triple[\s-]?negative|er[\s-]?positive|pr[\s-]?positive|"
    r"pd[\s-]?l1|tmb|mutant|mutation|positive|negative|"
    r"grade\s*[123]|poorly\s+differentiated|well\s+differentiated"
    r")\b",
    re.I,
)

_ORGAN_LEVEL_PATTERN = re.compile(
    r"^(?:non[\s-]?small[\s-]?cell\s+)?[\w\s-]+?\s+"
    r"(?:cancer|carcinoma|tumor|tumour)$",
    re.I,
)

# Radiology / non-pathology modalities — drop (Fangxin has pathology slides only).
_RADIOLOGY_MODALITIES = frozenset(
    {
        "ct",
        "computed tomography",
        "mri",
        "magnetic resonance imaging",
        "pet",
        "pet-ct",
        "pet/ct",
        "positron emission tomography",
        "x-ray",
        "xray",
        "radiograph",
        "radiography",
        "ultrasound",
        "us",
        "mammography",
        "mammogram",
        "radiomics",
        "medical imaging",
        "imaging",
        "radiology",
    }
)

_RADIOLOGY_MODALITY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\bcomputed\s+tomograph",
        r"\bmagnetic\s+resonance\b",
        r"\bpet[\s\-/]?ct\b",
        r"\bmammograph",
        r"\bradiomics?\b",
        r"\bradiolog",
    )
)

# Radiology / imaging Methods — always drop (same Fangxin pathology-only policy).
_RADIOLOGY_METHODS = frozenset(
    set(_RADIOLOGY_MODALITIES)
    | {
        "pyradiomics",
        "optical coherence tomography",
        "endoscopy",
        "endoscope",
        "cbct",
        "oct",
    }
)

_RADIOLOGY_METHOD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\bradiomics?\b",
        r"\bpyradiomics\b",
        r"\bct\b",
        r"\bmri\b",
        r"\bpet\b",
        r"\bcbct\b",
        r"\boct\b",
        r"\bultrasound\b",
        r"\bsonograph",
        r"\bendoscop",
        r"\bmammograph",
        r"\btomograph",
        r"\bx[\s-]?ray\b",
        r"\bpet[\s\-/]?ct\b",
        r"\bradiolog",
        r"\boptical\s+coherence\s+tomograph",
        # MRI sequence / plane labels (not bare \baxial\b — avoids "axial attention")
        r"\bsagittal\b",
        r"\bcoronal\b",
        r"\bflair\b",
        r"\bdwi\b",
        r"\bdiffusion[\s\-]?weighted\b",
        r"\bt[12][\s\-]?weighted\b",
        r"\bt[12]\s+(sagittal|axial|coronal)\b",
        r"\b(axial|coronal|sagittal)\s+(t[12]|mri|ct|view|plane|slice|image|model)\b",
    )
)

# Commercial / general-purpose foundation LLM product names — not research Methods.
# Word boundaries keep histogpt / seggpt / cellama.
_FOUNDATION_LLM_METHODS = frozenset(
    {
        "chatgpt",
        "chat gpt",
        "chat-gpt",
        "gpt",
        "claude",
        "gemini",
        "deepseek",
        "llama",
        "qwen",
        "openai",
        "bard",
        "copilot",
        "microsoft copilot",
        "grok",
        "mistral",
        "mixtral",
    }
)

_FOUNDATION_LLM_METHOD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\bchat[\s-]?gpt\b",
        r"\bgpt-?\d",  # gpt-4, gpt5, gpt-4o, gpt-5.2, gpt-5-nano
        r"\bclaude\b",
        r"\bgemini\b",
        r"\bdeepseek\b",
        r"\bllama\d*",  # llama / llama3 / llama3.1:70b
        r"\bqwen\d*",  # qwen / qwen2:72b
        r"\bopenai\b",
        r"\bbard\b",
        r"\bcopilot\b",
        r"\bgrok\b",
        r"\bmistral\b",
        r"\bmixtral\b",
        r"\bphi-?\d",
    )
)

# Vague AI umbrella phrases — always drop (unlike _GENERIC_METHODS which may keep alone).
_UMBRELLA_AI_METHODS = frozenset(
    {
        "ai model",
        "ai models",
        "ml model",
        "ml models",
        "dl model",
        "dl models",
        "deep learning model",
        "deep learning models",
        "machine learning model",
        "machine learning models",
        "deep learning-based model",
        "deep learning based model",
        "machine learning-based model",
        "machine learning based model",
        "artificial neural network",
        "artificial neural networks",
        "deep neural network",
        "deep neural networks",
        "deep convolutional neural network",
        "deep convolutional neural networks",
        "graph neural network",
        "graph neural networks",
        "integrative machine learning",
    }
)

_UMBRELLA_AI_METHOD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"^(ai|ml|dl)\s+models?$",
        r"\b(deep|machine)\s+learning([\s-]+based)?\s+models?\b",
        r"\bartificial\s+intelligence\s+models?\b",
        r"^artificial\s+neural\s+networks?$",
        r"^deep\s+(convolutional\s+)?neural\s+networks?$",
        r"^graph\s+neural\s+networks?$",
        r"\b(deep|machine)\s+learning\s+algorithms?\b",
        r"^multimodal\s+(deep|machine)\s+learning(\s+models?)?$",
    )
)

_MODALITY_ALIASES: dict[str, str] = {
    "whole slide image": "wsi",
    "whole-slide image": "wsi",
    "whole slide images": "wsi",
    "whole-slide images": "wsi",
    "whole slide imaging": "wsi",
    "digital whole slide image": "wsi",
    "h&e histopathology": "h&e",
    "h and e": "h&e",
    "hematoxylin and eosin": "h&e",
    "haematoxylin and eosin": "h&e",
    "he staining": "h&e",
    "h&e staining": "h&e",
    "immunohistochemistry": "ihc",
    "immunohistochemical": "ihc",
    "immunohistochemical staining": "ihc",
    "cytopathology": "cytology",
    "pap smear": "cytology",
    "pap test": "cytology",
    "liquid-based cytology": "cytology",
    "spatial omics": "spatial transcriptomics",
}

# Sections where Paper→Method contribution/baseline edges are unreliable (background).
_NO_PAPER_METHOD_SECTIONS = frozenset({"discussion", "future_work", "introduction"})
# Back-compat alias
_NO_APPLIES_METHOD_SECTIONS = _NO_PAPER_METHOD_SECTIONS

_PAPER_METHOD_RELATIONS = frozenset({"APPLIES_METHOD", "COMPARES_METHOD"})

# Paper→X relations: object type must match. Mismatches are repaired by remapping relation.
_RELATION_EXPECTED_OBJECT: dict[str, str] = {
    "APPLIES_METHOD": "Method",
    "COMPARES_METHOD": "Method",
    "TARGETS_DISEASE": "Disease",
    "OPERATES_ON": "Tissue",
    "PERFORMS_TASK": "Task",
    "USES_DATASET": "Dataset",
    "ACHIEVES_METRIC": "Metric",
    "REPORTS_LIMITATION": "Limitation",
    "USES_MODALITY": "Modality",
    "SURVEYS_METHOD": "Method",
    "COVERS_DISEASE": "Disease",
    "RELEASES_DATASET": "Dataset",
    "PRETRAINS_ON": "Dataset",
}

_OBJECT_CANONICAL_RELATION: dict[str, str] = {
    "Method": "APPLIES_METHOD",
    "Disease": "TARGETS_DISEASE",
    "Tissue": "OPERATES_ON",
    "Task": "PERFORMS_TASK",
    "Dataset": "USES_DATASET",
    "Metric": "ACHIEVES_METRIC",
    "Limitation": "REPORTS_LIMITATION",
    "Modality": "USES_MODALITY",
}

_LIMITATION_ALIASES: dict[str, str] = {
    "limited sample size": "small sample size",
    "small dataset size": "small sample size",
    "limited dataset size": "small sample size",
    "small cohort size": "small sample size",
    "small sample sizes": "small sample size",
    "retrospective study design": "retrospective design",
    "retrospective nature": "retrospective design",
    "retrospective single-center design": "retrospective single-center design",
    "retrospective single-center study": "retrospective single-center design",
    "single-center retrospective design": "retrospective single-center design",
    "need for external validation": "lack of external validation",
    "need for prospective validation": "lack of prospective validation",
    "need for further validation in larger cohorts": "lack of external validation",
    "limited generalizability": "limited generalizability",
    "limited interpretability": "lack of interpretability",
    "lack of interpretability": "lack of interpretability",
}

_GENERIC_TASKS = frozenset(
    {
        "classification",
        "segmentation",
        "detection",
        "prediction",
        "diagnosis",
        "prognosis",
        "analysis",
        "identification",
        "grading",
        "staging",
    }
)

_TASK_NARRATIVE_MARKERS = (
    "workshop",
    "report",
    "improving ",
    "developing ",
    "integrating ",
)

_TASK_SYNONYMS: dict[str, str] = {
    "prognostic prediction": "prognosis prediction",
    "prognosis prediction": "prognosis prediction",
    "pathological classification": "pathology classification",
}

_TASK_MAX_LEN = 80


def _norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def is_generic_method(name: str) -> bool:
    return _norm_key(name) in _GENERIC_METHODS


def is_low_value_method(name: str) -> bool:
    """True for training routines, radiology, foundation LLMs, or AI umbrella phrases."""
    key = _norm_key(name)
    if key in _LOW_VALUE_METHODS:
        return True
    if any(p.search(key) for p in _LOW_VALUE_METHOD_PATTERNS):
        return True
    if is_radiology_method(name):
        return True
    if is_foundation_llm_product(name):
        return True
    return is_umbrella_ai_method(name)


def is_generic_disease(name: str) -> bool:
    return _norm_key(name) in _GENERIC_DISEASES


def is_organ_level_disease(name: str) -> bool:
    """True for organ/system-level parents (kept only when no finer Disease exists)."""
    key = _norm_key(name)
    if key in _GENERIC_DISEASES:
        return False
    if key in _ORGAN_LEVEL_DISEASES:
        return True
    if _SUBTYPE_MARKERS.search(key):
        return False
    return bool(_ORGAN_LEVEL_PATTERN.match(key))


def _organ_keys(name: str) -> set[str]:
    key = _norm_key(name)
    found = {
        organ
        for organ, hints in _ORGAN_HINTS.items()
        if any(h in key for h in hints)
    }
    for phrase, organ in _HISTOLOGY_TO_ORGAN.items():
        if phrase in key:
            found.add(organ)
    return found


def has_more_specific_disease(name: str, cohort: set[str]) -> bool:
    """True if cohort contains a finer same-organ (or containing) Disease than name."""
    key = _norm_key(name)
    organs = _organ_keys(key)
    for other in cohort:
        if other == key:
            continue
        if key in other and key != other:
            return True
        if not organs:
            continue
        if not (_organ_keys(other) & organs):
            continue
        if is_organ_level_disease(key) and not is_organ_level_disease(other):
            return True
        if is_organ_level_disease(key) and len(other) > len(key) + 3:
            return True
    return False


def should_drop_disease(name: str, cohort: set[str]) -> bool:
    """Drop bare umbrellas always; drop organ-level when a finer Disease exists."""
    key = _norm_key(name)
    if is_generic_disease(key):
        return True
    if is_organ_level_disease(key) and has_more_specific_disease(key, cohort):
        return True
    return False


def is_radiology_modality(name: str) -> bool:
    """True for CT/MRI/PET/etc. — not pathology data modalities."""
    key = _norm_key(name)
    if key in _RADIOLOGY_MODALITIES:
        return True
    return any(p.search(key) for p in _RADIOLOGY_MODALITY_PATTERNS)


def is_radiology_method(name: str) -> bool:
    """True for radiology/imaging Methods (Fangxin has pathology slides only)."""
    key = _norm_key(name)
    if key in _RADIOLOGY_METHODS:
        return True
    return any(p.search(key) for p in _RADIOLOGY_METHOD_PATTERNS)


def is_foundation_llm_product(name: str) -> bool:
    """True for commercial/general foundation LLM product names (not research Methods)."""
    key = _norm_key(name)
    if key in _FOUNDATION_LLM_METHODS:
        return True
    return any(p.search(key) for p in _FOUNDATION_LLM_METHOD_PATTERNS)


def is_umbrella_ai_method(name: str) -> bool:
    """True for vague AI/ML/DL umbrella phrases that are not contribution Methods."""
    key = _norm_key(name)
    if key in _UMBRELLA_AI_METHODS:
        return True
    return any(p.search(key) for p in _UMBRELLA_AI_METHOD_PATTERNS)


def is_generic_task(name: str) -> bool:
    return _norm_key(name) in _GENERIC_TASKS


def is_narrative_task(name: str) -> bool:
    key = _norm_key(name)
    if any(m in key for m in _TASK_NARRATIVE_MARKERS):
        return True
    if len(key) > _TASK_MAX_LEN:
        return True
    return False


def is_reject_task(name: str) -> bool:
    return is_generic_task(name) or is_narrative_task(name)


def normalize_entity_name(name: str, entity_type: str) -> str:
    key = _norm_key(name)
    if entity_type == "Method":
        # Local import avoids an import cycle: method_synonyms uses _norm_key.
        from analysis.method_synonyms import resolve_method_entity_canonical

        return resolve_method_entity_canonical(key)
    if entity_type == "Disease":
        from analysis.disease_synonyms import resolve_disease_canonical

        # Exact curated aliases only. Broad focus matching would erase subtype,
        # mutation and metastasis qualifiers from extracted disease entities.
        return resolve_disease_canonical(key) or key
    if entity_type == "Limitation":
        return _LIMITATION_ALIASES.get(key, key)
    if entity_type == "Modality":
        return _MODALITY_ALIASES.get(key, key)
    if entity_type == "Task":
        return _TASK_SYNONYMS.get(key, key)
    return key


def _disease_cohort(triples: list[Triple]) -> set[str]:
    names: set[str] = set()
    for t in triples:
        if t.object.type == "Disease":
            names.add(_norm_key(t.object.name))
        if t.subject.type == "Disease":
            names.add(_norm_key(t.subject.name))
    return names


def repair_triple_relation(triple: Triple) -> Triple | None:
    """Force relation↔object-type consistency; drop invalid RELATED_TO.

    Prefer remapping the relation to match object.type (entity labels are usually
    more reliable than relation names when the LLM confuses APPLIES_METHOD/PERFORMS_TASK).
    """
    if triple.relation == "RELATED_TO":
        if triple.subject.type == "Method" and triple.object.type == "Method":
            return triple
        return None

    expected = _RELATION_EXPECTED_OBJECT.get(triple.relation)
    if expected is None:
        return None
    if triple.object.type == expected:
        return triple

    new_rel = _OBJECT_CANONICAL_RELATION.get(triple.object.type)
    if not new_rel:
        return None
    return triple.model_copy(update={"relation": new_rel})


def postprocess_triples(
    triples: list[Triple],
    section_type: str,
    *,
    study_type: str | None = None,
) -> list[Triple]:
    """Repair relations, filter low-value methods / coarse diseases / radiology modalities."""
    normalized: list[Triple] = []
    for triple in triples:
        obj_name = triple.object.name
        obj_type = triple.object.type
        if obj_type in ("Method", "Limitation", "Disease", "Modality", "Task"):
            obj_name = normalize_entity_name(obj_name, obj_type)
        subj = triple.subject
        if triple.relation == "RELATED_TO" and subj.type == "Method":
            subj = subj.model_copy(
                update={"name": normalize_entity_name(subj.name, "Method")}
            )
        obj = triple.object.model_copy(update={"name": obj_name})
        repaired = repair_triple_relation(
            triple.model_copy(update={"subject": subj, "object": obj})
        )
        if repaired is not None:
            normalized.append(repaired)

    import config

    normalized = apply_policy(normalized, study_type)
    # Kill-switch: skip matrix dataset_mode; keep legacy review/meta drop only.
    if config.STUDY_POLICY_ENABLED:
        drop_datasets = get_policy(study_type).dataset_mode == "none"
    else:
        drop_datasets = (study_type or "").lower() in ("review", "meta_analysis")

    specific_methods = {
        _norm_key(t.object.name)
        for t in normalized
        if t.relation in _PAPER_METHOD_RELATIONS
        and t.object.type == "Method"
        and not is_generic_method(t.object.name)
        and not is_low_value_method(t.object.name)
    }
    disease_cohort = _disease_cohort(normalized)

    out: list[Triple] = []
    for triple in normalized:
        if (
            triple.relation in _PAPER_METHOD_RELATIONS
            and section_type in _NO_PAPER_METHOD_SECTIONS
        ):
            continue

        obj_name = triple.object.name
        obj_type = triple.object.type
        subj = triple.subject

        if triple.relation == "RELATED_TO" and subj.type == "Method":
            if is_low_value_method(subj.name) or (
                obj_type == "Method" and is_low_value_method(obj_name)
            ):
                continue

        if obj_type == "Method" and is_low_value_method(obj_name):
            if triple.relation in ("APPLIES_METHOD", "COMPARES_METHOD", "RELATED_TO"):
                continue

        if obj_type == "Disease" and should_drop_disease(obj_name, disease_cohort):
            continue
        if subj.type == "Disease" and should_drop_disease(
            normalize_entity_name(subj.name, "Disease"), disease_cohort
        ):
            continue

        if obj_type == "Modality" and is_radiology_modality(obj_name):
            continue

        if obj_type == "Task" and is_reject_task(obj_name):
            continue

        if (
            triple.relation in DATASET_RELATIONS
            or obj_type == "Dataset"
        ):
            if drop_datasets:
                continue
            canon = normalize_dataset_name(obj_name)
            if is_literature_platform(obj_name) or is_literature_platform(canon):
                continue
            if canon != obj_name:
                triple = triple.model_copy(
                    update={"object": triple.object.model_copy(update={"name": canon})}
                )
                obj_name = canon

        if (
            triple.relation in _PAPER_METHOD_RELATIONS
            and obj_type == "Method"
            and specific_methods
            and is_generic_method(obj_name)
        ):
            continue

        confidence = triple.confidence
        if (
            triple.relation in _PAPER_METHOD_RELATIONS
            and obj_type == "Method"
            and is_generic_method(obj_name)
        ):
            confidence = min(confidence, 0.5)

        out.append(triple.model_copy(update={"confidence": confidence}))

    # Same Method as both contribution and baseline → keep contribution only.
    applies_names = {
        _norm_key(t.object.name)
        for t in out
        if t.relation == "APPLIES_METHOD" and t.object.type == "Method"
    }
    if applies_names:
        out = [
            t
            for t in out
            if not (
                t.relation == "COMPARES_METHOD"
                and t.object.type == "Method"
                and _norm_key(t.object.name) in applies_names
            )
        ]
    return out
