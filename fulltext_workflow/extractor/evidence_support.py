"""Conservative, auditable support signals for located extraction evidence.

This module does not claim to replace expert entailment review.  It marks obvious
support failures (negation and background-only mentions) and leaves ambiguous
cases visible instead of deleting them from the graph.
"""
from __future__ import annotations

import re

from extractor.triple_models import Triple


_OWN_STUDY_RELATIONS = frozenset(
    {
        "APPLIES_METHOD",
        "COMPARES_METHOD",
        "USES_DATASET",
        "RELEASES_DATASET",
        "PRETRAINS_ON",
        "ACHIEVES_METRIC",
        "TARGETS_DISEASE",
        "PERFORMS_TASK",
        "USES_MODALITY",
        "OPERATES_ON",
    }
)

_RELATION_CUES: dict[str, tuple[str, ...]] = {
    "APPLIES_METHOD": (r"\bpropos\w*\b", r"\bintroduc\w*\b", r"\buse[sd]?\b", r"\badopt\w*\b", r"\bemploy\w*\b", r"\bdevelop\w*\b", r"\bpresent\w*\b"),
    "COMPARES_METHOD": (r"\bcompar\w*\b", r"\bbaseline\b", r"\bagainst\b", r"\bversus\b", r"\bvs\.?\b", r"\boutperform\w*\b"),
    "SURVEYS_METHOD": (r"\breview\w*\b", r"\bsurvey\w*\b", r"\bsummar\w*\b", r"\blandscape\b", r"\bcover\w*\b"),
    "USES_DATASET": (r"\buse[sd]?\b", r"\btrain\w*\b", r"\bevaluat\w*\b", r"\btest\w*\b", r"\bvalidat\w*\b", r"\bon\b", r"\bover\b"),
    "RELEASES_DATASET": (r"\breleas\w*\b", r"\bcontribut\w*\b", r"\bpublish\w*\b", r"\bmake available\b"),
    "PRETRAINS_ON": (r"\bpre[- ]?train\w*\b",),
    "ACHIEVES_METRIC": (r"\bachiev\w*\b", r"\breport\w*\b", r"\bauc\b", r"\baccuracy\b", r"\bf1\b", r"\bsensitivity\b", r"\bspecificity\b"),
    "REPORTS_LIMITATION": (r"\blimit\w*\b", r"\bretrospective\b", r"\black\w*\b", r"\bsmall sample\b", r"\bsingle[- ]center\b"),
    "TARGETS_DISEASE": (r"\bpatient\w*\b", r"\bcohort\b", r"\bcase\w*\b", r"\bstud\w*\b", r"\benroll\w*\b"),
    "COVERS_DISEASE": (r"\breview\w*\b", r"\bsurvey\w*\b", r"\bcover\w*\b", r"\bscope\b"),
    "PERFORMS_TASK": (r"\bclassif\w*\b", r"\bsegment\w*\b", r"\bpredict\w*\b", r"\bdetect\w*\b", r"\bdiagnos\w*\b"),
    "USES_MODALITY": (r"\buse[sd]?\b", r"\bimage\w*\b", r"\bslide\w*\b", r"\bstain\w*\b"),
    "OPERATES_ON": (r"\btissue\b", r"\bspecimen\w*\b", r"\bbiops\w*\b", r"\bslide\w*\b"),
    "RELATED_TO": (r"\brelat\w*\b", r"\bcombin\w*\b", r"\bmodule\b", r"\bbackbone\b"),
}

_NEGATION = re.compile(
    r"\b(?:not|never|no|without|did\s+not|does\s+not|do\s+not|was\s+not|were\s+not|is\s+not|are\s+not|neither)\b",
    re.I,
)
_BACKGROUND = re.compile(
    r"\b(?:prior|previous|earlier|related\s+work|historical\s+context|cited\s+only|literature)\b",
    re.I,
)
_GENERIC_TOKENS = frozenset(
    {"the", "a", "an", "of", "and", "or", "for", "to", "on", "in", "with", "method", "model", "dataset", "task", "disease", "metric"}
)


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", (value or "").lower()).strip()


def _object_mentioned(triple: Triple, quote: str) -> bool:
    obj = _norm(triple.object.name)
    text = _norm(quote)
    if not obj:
        return False
    if re.search(r"(?<!\w)" + re.escape(obj) + r"(?!\w)", text):
        return True
    tokens = [t for t in obj.split() if len(t) > 2 and t not in _GENERIC_TOKENS]
    return bool(tokens) and all(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text) for t in tokens)


def _metric_value_mentioned(triple: Triple, quote: str) -> bool:
    if triple.relation != "ACHIEVES_METRIC" or not triple.metric_value:
        return True
    expected = str(triple.metric_value).strip().lower()
    text = str(quote).strip().lower()
    if expected and expected in text:
        return True
    match = re.fullmatch(r"(\d+(?:\.\d+)?)%?", expected)
    if not match:
        return False
    value = float(match.group(1))
    alternatives = {f"{value:g}", f"{value * 100:g}", f"{value / 100:g}"}
    return any(re.search(r"(?<![\d.])" + re.escape(v) + r"%?(?![\d.])", text) for v in alternatives)


def assess_evidence_support(triple: Triple, quote: str | None = None) -> tuple[str, str]:
    """Return an advisory status and machine-readable reason for a located quote."""
    text = (quote if quote is not None else triple.evidence_quote) or ""
    if not text.strip():
        return "unclear", "missing_quote"
    mentioned = _object_mentioned(triple, text)
    if _NEGATION.search(text) and mentioned and triple.relation not in {"REPORTS_LIMITATION"}:
        return "contradicted", "negated_relation"
    if _BACKGROUND.search(text) and triple.relation in _OWN_STUDY_RELATIONS:
        return "mentioned_only", "background_context"
    if not mentioned:
        return "unclear", "object_not_in_quote"
    if not _metric_value_mentioned(triple, text):
        return "unclear", "metric_value_not_in_quote"
    cues = _RELATION_CUES.get(triple.relation, ())
    if cues and not any(re.search(cue, text, re.I) for cue in cues):
        return "unclear", "relation_cue_not_in_quote"
    return "supported", "object_and_relation_cue"


def annotate_evidence_support(triple: Triple) -> Triple:
    status, reason = assess_evidence_support(triple)
    return triple.model_copy(
        update={"evidence_support_status": status, "evidence_support_reason": reason}
    )
