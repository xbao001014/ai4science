"""P0 diagnostic cases; silver labels, created before the P0 candidate run.

These cases exercise the evidence-support contract and recall-routing logic. They
are visible development fixtures, not an expert-adjudicated hidden holdout.
"""


def evidence_case(cid, relation, object_name, quote, expected, metric_value=None):
    object_type = {
        "APPLIES_METHOD": "Method",
        "COMPARES_METHOD": "Method",
        "SURVEYS_METHOD": "Method",
        "USES_DATASET": "Dataset",
        "RELEASES_DATASET": "Dataset",
        "PRETRAINS_ON": "Dataset",
        "ACHIEVES_METRIC": "Metric",
        "TARGETS_DISEASE": "Disease",
        "REPORTS_LIMITATION": "Limitation",
    }[relation]
    return {
        "id": cid,
        "triple": {
            "subject": {"name": "paper", "type": "Method"},
            "relation": relation,
            "object": {"name": object_name, "type": object_type},
            "metric_value": metric_value,
            "evidence_quote": quote,
        },
        "quote": quote,
        "expected": expected,
    }


EVIDENCE_SUPPORT = [
    evidence_case("S01", "APPLIES_METHOD", "clam", "We use CLAM for slide classification.", "supported"),
    evidence_case("S02", "COMPARES_METHOD", "transmil", "We compare CedarMIL against TransMIL.", "supported"),
    evidence_case("S03", "SURVEYS_METHOD", "clam", "This review surveys CLAM and TransMIL.", "supported"),
    evidence_case("S04", "USES_DATASET", "camelyon16", "We evaluate the model on CAMELYON16.", "supported"),
    evidence_case("S05", "RELEASES_DATASET", "oakslides", "We release the OakSlides dataset.", "supported"),
    evidence_case("S06", "PRETRAINS_ON", "histologyatlas", "We pretrain on HistologyAtlas.", "supported"),
    evidence_case("S07", "ACHIEVES_METRIC", "auc", "CedarMIL achieved AUC 0.81.", "supported", "0.81"),
    evidence_case("S08", "TARGETS_DISEASE", "lung adenocarcinoma", "The cohort enrolled patients with lung adenocarcinoma.", "supported"),
    evidence_case("S09", "REPORTS_LIMITATION", "retrospective design", "A limitation is the retrospective design.", "supported"),
    evidence_case("S10", "APPLIES_METHOD", "clam", "Prior literature used CLAM.", "mentioned_only"),
    evidence_case("S11", "USES_DATASET", "panda", "PANDA is mentioned only as historical context.", "mentioned_only"),
    evidence_case("S12", "ACHIEVES_METRIC", "auc", "Previous work reported AUC 0.99.", "mentioned_only", "0.99"),
    evidence_case("S13", "APPLIES_METHOD", "clam", "We did not use CLAM.", "contradicted"),
    evidence_case("S14", "USES_DATASET", "camelyon16", "CAMELYON16 was not used in this study.", "contradicted"),
    evidence_case("S15", "TARGETS_DISEASE", "breast cancer", "No patient with breast cancer was enrolled.", "contradicted"),
    evidence_case("S16", "APPLIES_METHOD", "clam", "CLAM is an attention-based method.", "unclear"),
    evidence_case("S17", "APPLIES_METHOD", "cedarmil", "This section discusses CedarMIL.", "unclear"),
    evidence_case("S18", "ACHIEVES_METRIC", "auc", "The AUC was considered strong.", "unclear", "0.81"),
]


EMPTY_ROUTING = [
    {
        "id": "Q01",
        "study_type": "review",
        "text": "This review surveys CLAM and TransMIL in lung pathology.",
        "phase2": None,
        "p0": "explicit_review_scope",
    },
    {
        "id": "Q02",
        "study_type": "meta_analysis",
        "text": "Our meta-analysis estimated pooled AUC 0.81.",
        "phase2": None,
        "p0": "explicit_meta_synthesis",
    },
    {
        "id": "Q03",
        "study_type": "ai_algorithm",
        "text": "We propose CedarMIL for tumor classification.",
        "phase2": "explicit_author_experiment",
        "p0": "explicit_author_experiment",
    },
    {
        "id": "Q04",
        "study_type": "other",
        "text": "Acknowledgments: We thank the study coordinators.",
        "phase2": None,
        "p0": None,
    },
]
