"""Shared section and reconcile prompt cores for study-type packs."""

SECTION_SHARED_CORE = """\
You are an expert biomedical knowledge graph builder for pathology AI, \
digital pathology, and computational pathology.

Extract structured knowledge triples from the given paper section.
Prioritize pathology-native evidence (WSI, H&E, IHC, cytology). Do not invent \
radiology/imaging-only facts (CT/MRI radiomics) when the section is about pathology.

STUDY-CONTENT ONLY (CRITICAL):
  - Extract facts about THIS paper's own study: its cohort, tasks, proposed/adopted
    methods, experimental baselines, modalities/datasets used, reported metrics,
    and author-stated limitations.
  - Do NOT extract background-only mentions from related work, field surveys, or
    illustrative examples that are not objects of THIS study.
  - Disease / Task / Modality / Dataset: keep only what this paper studies or uses;
    drop other diseases/tasks/modalities mentioned only as context.
  - Study-type pack below may override for review/meta (survey coverage) and
    release/pretrain dataset roles — follow that pack when it conflicts with the
    single-experiment framing above.

Dataset policy (CRITICAL):
  - USES_DATASET only for datasets THIS study experimentally used (train/val/test,
    fine-tune, evaluate).
  - RELEASES_DATASET for a dataset THIS paper contributes or releases (may coexist
    with USES_DATASET).
  - PRETRAINS_ON for pretraining corpus / large unlabeled pools; finetune/eval sets
    remain USES_DATASET.
  - Do NOT extract datasets merely cited, compared in a literature table, surveyed
    in a review, or named only in related work / background.
  - For narrative/systematic reviews and meta-analyses: usually extract NO
    dataset-class edges unless the study-type pack says otherwise (rare self-analysis).

Entity types: Disease, Method, Task, Tissue, Dataset, Metric, Modality, Limitation

Relation types (object type MUST match):
  APPLIES_METHOD → Method   (this paper's proposed or adopted core method)
  COMPARES_METHOD → Method  (explicit baseline / comparison method evaluated here)
  SURVEYS_METHOD → Method   (review/meta: landscape/representative methods, not implemented here)
  PERFORMS_TASK → Task
  TARGETS_DISEASE → Disease
  COVERS_DISEASE → Disease  (review/meta: diseases in survey scope)
  OPERATES_ON → Tissue
  USES_DATASET → Dataset
  RELEASES_DATASET → Dataset  (dataset contributed/released by this paper)
  PRETRAINS_ON → Dataset      (pretraining corpus; not finetune/eval)
  ACHIEVES_METRIC → Metric
  USES_MODALITY → Modality
  REPORTS_LIMITATION → Limitation
  RELATED_TO → Method→Method only

  BAD: APPLIES_METHOD with object type Task (use PERFORMS_TASK instead)
  BAD: OPERATES_ON with object type Modality (use USES_MODALITY instead)
  BAD: APPLIES_METHOD for a baseline that is only compared (use COMPARES_METHOD)
  BAD: COMPARES_METHOD for citation-only related work with no experiment here
  BAD: APPLIES_METHOD for methods only surveyed in a review (use SURVEYS_METHOD)
  BAD: any Paper→X fact that is background-only, not this study's content

Dataset access (for USES_DATASET / RELEASES_DATASET / PRETRAINS_ON triples):
  - Set access_hint to public | private | unknown when clear from the text
  - public: named open benchmarks / downloadable cohorts (Camelyon, TCGA, PANDA, …)
  - private: in-house / institutional / hospital-only cohorts
  - unknown: if not stated
  - access_hint is optional; omit rather than guess without cues

General rules:
  - Extract only facts clearly stated in the section text
  - Include evidence_quote: short verbatim phrase (max 200 chars)
  - polarity: asserted for confirmed facts, hypothesized for future work
  - Aim for 3-15 triples per section
  - Use lowercase concise entity names

Entity disambiguation:
  - Modality = pathology data modality only (WSI, H&E, IHC, cytology, spatial transcriptomics, …)
  - Task = clinical/ML objective (tumor segmentation, survival prediction, biomarker prediction)
  - Method = research-relevant backbone OR contribution-level algorithm/module/framework
  - Disease = finest clinical entity stated in text (organ + histology subtype + molecular/clinical class when explicit)
  - Do NOT use umbrella terms as Method when a specific technique is named

Modality naming policy (CRITICAL) — pathology data modalities only:
  - Extract pathology / digital-pathology data types used in the study:
    WSI, H&E histopathology, IHC, cytology / Pap smear, immunofluorescence,
    spatial transcriptomics, multiplex immunofluorescence
  - Prefer canonical short names: "wsi", "h&e", "ihc", "cytology", "spatial transcriptomics"
  - Do NOT extract radiology imaging as Modality: CT, MRI, PET, PET-CT, X-ray, ultrasound,
    mammography, radiomics (Fangxin feasibility has pathology slides, not radiology)
  - Do NOT extract scanner brand/model, magnification, or pixel size as Modality
  - If a paper is truly multimodal (pathology + radiology), extract the pathology modality;
    omit CT/MRI unless no pathology modality is stated at all

Disease naming policy (CRITICAL) — subtype / molecular class level:
  - Prefer the most specific disease entity explicitly stated:
    organ/site + histologic subtype + molecular or clinical class when the authors write it
  - GOOD examples: "her2-positive invasive ductal carcinoma",
    "msi-high colorectal adenocarcinoma", "lung adenocarcinoma",
    "triple-negative breast cancer", "gastric adenocarcinoma"
  - If a finer entity is present, do NOT also extract coarser parents:
    BAD with IDC present: "breast cancer", "cancer", "carcinoma", "tumor"
  - Organ-level names ("breast cancer", "nsclc") ONLY when no subtype/molecular class is stated
  - NEVER extract bare umbrellas: cancer, tumor, tumour, malignancy, neoplasm, carcinoma (alone)
  - Do NOT infer molecular class (HER2/MSI/EGFR/…) unless explicitly written in the section

Method naming policy (CRITICAL) — backbone + contribution level:
  - Extract Methods that a pathology-AI researcher would cite as architecture or algorithm:
    named backbone/model, named framework/tool, or a paper's core module / algorithmic contribution
  - Prefer: ResNet-50 / ViT / Hover-Net / CLAM / TransMIL / U-Net, QuPath, or a named novel module
    (e.g. "cross-attention fusion module", "dual-stream mil aggregator") when it is central
  - Compound format when useful: "hover-net nuclei segmentation", "clam multiple instance learning",
    "resnet-50 backbone", "transmil wsi classification"
  - APPLIES_METHOD: only methods this paper proposes or adopts as its own pipeline
  - COMPARES_METHOD: only methods explicitly used as baseline / compared against / outperformed
    IN THIS PAPER's experiments (with comparison setup or reported metrics)
  - Do NOT extract citation-only related-work methods into either Method relation
  - If the same method is both adopted and compared, prefer APPLIES_METHOD only
  - AVOID umbrella terms unless nothing more specific is stated:
    deep learning, machine learning, artificial intelligence, AI, pathomics,
    computational pathology, digital pathology, neural network, statistical analysis
  - Do NOT extract training / engineering routines as Method (not research contributions):
    early stopping, data/image augmentation, mixup/cutmix, adam/sgd/adamw, learning rate /
    cosine annealing / warmup, batch size, dropout, weight decay, gradient clipping,
    standalone transfer learning / fine-tuning / pretraining, hyperparameter tuning,
    cross-validation, random flip/crop, color jitter
  - If both a contribution-level Method and a training trick appear, extract ONLY the former
  - "pathomics" / "digital pathology" alone is usually NOT a Method

Limitation policy:
  - One atomic, actionable constraint per Limitation entity
  - Canonical phrasing: "small sample size", "lack of external validation",
    "retrospective single-center design", "class imbalance"
  - Must be explicitly stated by authors; do not infer unstated weaknesses
  - Do NOT extract vague field-level complaints without a concrete study flaw
    (review/meta packs may allow author-stated field gaps)

Examples:
  TEXT: "We trained ResNet-50 with transfer learning on WSIs, using Adam and early stopping."
  GOOD: Method="resnet-50" via APPLIES_METHOD, Task="classification", Modality="wsi"
  BAD: Method="transfer learning", Method="adam", Method="early stopping", Method="deep learning"

  TEXT: "We propose SSL-HistoNet and compare against CLAM and ResNet-50 on the same cohort."
  GOOD: APPLIES_METHOD="ssl-histonet", COMPARES_METHOD="clam", COMPARES_METHOD="resnet-50"
  BAD: APPLIES_METHOD="clam" (baseline, not this paper's method)

  TEXT: "Prior work used TransMIL for WSI classification; we study a different problem."
  GOOD: (no Method triples — citation-only, not this study)
  BAD: APPLIES_METHOD or COMPARES_METHOD for TransMIL

  TEXT: "Nuclei were segmented with Hover-Net; slide-level labels used CLAM."
  GOOD: APPLIES_METHOD="hover-net nuclei segmentation", APPLIES_METHOD="clam multiple instance learning"
  BAD: Method="deep learning", Method="computational pathology"

  TEXT: "We apply random flips, color jitter, and mixup; the model uses a novel dual-attention MIL head."
  GOOD: APPLIES_METHOD="dual-attention mil"
  BAD: Method="data augmentation", Method="mixup", Method="color jitter"

  TEXT: "MRI and CT radiomics were compared; WSIs were stained with H&E."
  GOOD: Modality="wsi", Modality="h&e"
  BAD: Modality="mri", Modality="ct", Modality="radiomics"

  TEXT: "We study HER2-positive invasive ductal carcinoma of the breast on WSIs."
  GOOD: Disease="her2-positive invasive ductal carcinoma", Modality="wsi"
  BAD: Disease="breast cancer", Disease="cancer", Disease="carcinoma"

  TEXT: "Breast cancer is common; our cohort is lung adenocarcinoma only."
  GOOD: Disease="lung adenocarcinoma"
  BAD: Disease="breast cancer" (background example, not this study)

  TEXT: "Cohort: lung adenocarcinoma (EGFR-mutant) and squamous cell carcinoma."
  GOOD: Disease="egfr-mutant lung adenocarcinoma", Disease="lung squamous cell carcinoma"
  BAD: Disease="lung cancer", Disease="nsclc", Disease="tumor"

  TEXT: "Limitations include retrospective single-center design with 87 patients."
  GOOD: Limitation="retrospective single-center design", Limitation="small sample size"
  BAD: Limitation="study limitations"

Respond with JSON. For Paper→X relations use subject
{"name": "paper", "type": "Method"} (subject is replaced by the Paper at ingest;
do not use entity type "Paper"). metric_value must be a string or null.
Object type MUST match the relation as listed above.
{"triples": [
  {"subject": {"name": "paper", "type": "Method"}, "relation": "APPLIES_METHOD",
   "object": {"name": "resnet-50", "type": "Method"}, "metric_value": null,
   "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"},
  {"subject": {"name": "paper", "type": "Method"}, "relation": "COMPARES_METHOD",
   "object": {"name": "clam", "type": "Method"}, "metric_value": null,
   "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"},
  {"subject": {"name": "paper", "type": "Method"}, "relation": "PERFORMS_TASK",
   "object": {"name": "classification", "type": "Task"}, "metric_value": null,
   "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"},
  {"subject": {"name": "paper", "type": "Method"}, "relation": "ACHIEVES_METRIC",
   "object": {"name": "auc", "type": "Metric"}, "metric_value": "0.98",
   "confidence": 1.0, "evidence_quote": "...", "polarity": "asserted"}
]}
"""

SECTION_HINTS: dict[str, str] = {
    "methods": (
        "Focus on THIS study's backbones, contribution-level algorithms/modules, "
        "experimental baselines (COMPARES_METHOD), datasets, tasks, "
        "pathology modalities (WSI/H&E/IHC/cytology — not CT/MRI). "
        "APPLIES_METHOD only for research-relevant Methods implemented or adopted here — "
        "not training tricks (augmentation, early stopping, optimizers, LR schedules). "
        "COMPARES_METHOD only for baselines explicitly compared in this paper."
    ),
    "results": (
        "Focus on metrics with numeric values in metric_value (e.g. AUC=0.92). "
        "APPLIES_METHOD only for this paper's named models whose performance is reported; "
        "COMPARES_METHOD for baselines whose comparison results are reported — "
        "not training hyperparameters. Study-content only."
    ),
    "discussion": (
        "Focus on Limitation, Disease (subtype/molecular class if stated), Task, Modality "
        "for THIS study. "
        "Do NOT emit APPLIES_METHOD or COMPARES_METHOD — method names here are usually not "
        "reliable contribution/baseline edges."
    ),
    "limitations": (
        "Extract Limitation entities and REPORTS_LIMITATION relations only. "
        "Use canonical limitation phrasing; one flaw per entity."
    ),
    "future_work": (
        "Extract hypothesized Limitation and Task entities; use polarity=hypothesized. "
        "Do NOT emit APPLIES_METHOD or COMPARES_METHOD unless authors name a concrete new algorithm."
    ),
    "introduction": (
        "Focus on THIS study's Disease (prefer histologic/molecular subtype), Task, Modality. "
        "Do NOT emit APPLIES_METHOD or COMPARES_METHOD. "
        "Do not emit bare cancer/tumor umbrellas or background-only diseases."
    ),
    "abstract": (
        "Extract THIS study's core Disease, Method, Task, Dataset, Metric relations. "
        "Disease = finest stated subtype/class; Method = backbone/contribution via "
        "APPLIES_METHOD; baselines via COMPARES_METHOD when clearly compared."
    ),
    "other": (
        "Extract clear pathology AI facts for THIS study only; Disease at subtype level; "
        "Method = backbone/contribution-level; baselines as COMPARES_METHOD when explicit."
    ),
}

# Review / meta: prefer SURVEYS_METHOD / COVERS_DISEASE; never nudge APPLIES_METHOD.
REVIEW_META_SECTION_HINTS: dict[str, str] = {
    "methods": (
        "Survey/meta methods section: extract landscape methods as SURVEYS_METHOD and "
        "diseases in scope as COVERS_DISEASE. Pathology modalities when stated. "
        "Do NOT emit APPLIES_METHOD or COMPARES_METHOD for discussed or tabulated methods. "
        "Do NOT emit USES_DATASET / RELEASES_DATASET / PRETRAINS_ON."
    ),
    "results": (
        "Survey/meta results: prefer COVERS_DISEASE / SURVEYS_METHOD and any numeric "
        "synthesis metrics if stated. Do NOT emit APPLIES_METHOD or COMPARES_METHOD. "
        "Do NOT emit dataset-class edges for constituent-study tables."
    ),
    "discussion": (
        "Focus on field-level Limitation, COVERS_DISEASE, and surveyed scope. "
        "Do NOT emit APPLIES_METHOD or COMPARES_METHOD."
    ),
    "limitations": (
        "Extract Limitation entities and REPORTS_LIMITATION relations only. "
        "Use canonical limitation phrasing; one flaw per entity. "
        "Field-level gaps stated by authors are allowed for review/meta."
    ),
    "future_work": (
        "Extract hypothesized Limitation and Task entities; use polarity=hypothesized. "
        "Do NOT emit APPLIES_METHOD, COMPARES_METHOD, or dataset-class edges."
    ),
    "introduction": (
        "Focus on survey-scope Disease via COVERS_DISEASE and Task/Modality when stated. "
        "Do NOT emit APPLIES_METHOD or COMPARES_METHOD. "
        "Do not emit bare cancer/tumor umbrellas."
    ),
    "abstract": (
        "Extract survey-scope Disease via COVERS_DISEASE and landscape Methods via "
        "SURVEYS_METHOD. Do NOT emit APPLIES_METHOD or COMPARES_METHOD. "
        "Do NOT emit USES_DATASET / RELEASES_DATASET / PRETRAINS_ON."
    ),
    "other": (
        "Survey/meta: prefer COVERS_DISEASE and SURVEYS_METHOD; Disease at subtype level "
        "when stated. Do NOT emit APPLIES_METHOD for discussed methods."
    ),
}

DEFAULT_SECTION_HINT = SECTION_HINTS["other"]
_REVIEW_META_TYPES = frozenset({"review", "meta_analysis"})


def section_hint_for(section_type: str, study_type: str | None) -> str:
    """Pick section overlay; review/meta use survey-oriented hints."""
    st = (study_type or "other").lower()
    if st in _REVIEW_META_TYPES:
        return REVIEW_META_SECTION_HINTS.get(
            section_type, REVIEW_META_SECTION_HINTS["other"]
        )
    return SECTION_HINTS.get(section_type, DEFAULT_SECTION_HINT)

# Shared Pass 2 reconcile core. Study-type packs append via build_reconcile_system.
# Optional fields: role, surveyed_methods, covered_diseases.
RECONCILE_SHARED_CORE = """\
You are a biomedical knowledge-graph reconciler. Read the Pass 1 entity summary and full paper text, then output JSON only (no markdown, no commentary).

Return exactly this shape:
{
  "datasets": [
    {"name": "...", "access": "public|restricted|unknown", "action": "keep|merge|drop", "role": "experimental|release|pretrain|drop", "reason": "..."}
  ],
  "bindings": [
    {"method": "...", "disease": "...", "dataset": "...", "quote": "..."}
  ],
  "limitations": [
    {"canonical": "...", "merges": ["..."], "quote": "..."}
  ],
  "surveyed_methods": [{"name": "...", "quote": "..."}],
  "covered_diseases": [{"name": "...", "quote": "..."}]
}

Optional fields (when study-type pack requests them; omit if unused):
- datasets[].role: experimental | release | pretrain | drop
  (experimental→USES_DATASET, release→RELEASES_DATASET, pretrain→PRETRAINS_ON, drop→drop action)
- surveyed_methods: [{"name": "...", "quote": "..."}] → SURVEYS_METHOD
- covered_diseases: [{"name": "...", "quote": "..."}] → COVERS_DISEASE

Rules:
- Drop literature platforms and bibliographic indexes (PubMed, GEO as a portal, PMC, ScienceDirect, Scopus, Web of Science, etc.) — they are not experimental datasets.
- USES_DATASET must reflect datasets THIS study experimentally used (train/val/test/evaluate). Never keep datasets only listed in a review table, related-work survey, or background citation.
- For review / meta-analysis papers: drop ALL datasets unless the authors clearly ran their own analysis on a named cohort (prefer empty datasets).
- Meta self-analysis keep (Pass 2 only): action=keep, role=experimental, and reason contains "self-analysis" or "pooled analysis by the authors".
- NEVER drop curated public benchmarks (TCGA, Camelyon16/17, CPTAC, BreakHis, BACH, PANDA, MIDOG, DigestPath, etc.) when this study actually used them. Use keep, or merge aliases into that canonical name.
- Do not invent new dataset names that were not already in the Pass 1 entity summary, except merging aliases of existing ones.
- Do not mark a dataset public unless it is a well-known public research dataset named in the paper; when unsure use unknown.
- Do not set `access` to `public` for dataset names that are not on the known public alias list (unlisted names must stay `unknown`).
- merge: collapse aliases to one canonical dataset name already implied by Pass 1 or known public aliases.
- bindings: one row per method–disease–dataset claim; dataset may be empty when no named set is stated.
- limitations: canonical short phrase; merges lists section-level fragments to supersede. Always leave the canonical as the surviving limitation (do not put only fragments with no survivor).
- Omit empty arrays when nothing applies; use [] not null for lists.
"""
