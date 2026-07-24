"""Unit tests for extraction skip rules."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor.skip_rules import (  # noqa: E402
    skip_extraction_reason,
    skip_nonsubstantive_fulltext,
)


def test_skip_editorial():
    reason = skip_extraction_reason(
        "Spatial omics and AI for clinically actionable cancer biomarkers.",
        "Integrating spatial omics with artificial intelligence is likely to advance biomarker research.",
        ["Journal Article", "Editorial"],
    )
    assert reason and "editorial" in reason


def test_skip_special_issue_title():
    reason = skip_extraction_reason(
        "Special issue European Journal of Physiology: Artificial intelligence in physiology",
        "This special issue introduces invited papers on AI in physiology.",
        ["Journal Article"],
    )
    assert reason and "special issue" in reason


def test_skip_workshop_report_title():
    reason = skip_extraction_reason(
        "Challenges and advances in drug resistance: a workshop report",
        "Therapeutic resistance remains the principal barrier " * 5,
        ["Journal Article", "Review"],
    )
    assert reason and "workshop" in reason


def test_skip_meeting_summary_abstract():
    reason = skip_extraction_reason(
        "Challenges and advances in drug resistance and tolerance in cancer.",
        "Therapeutic resistance remains the principal barrier. "
        "This meeting brought together leading experts to dissect resistance mechanisms.",
        ["Journal Article", "Review"],
    )
    assert reason and "meeting" in reason


def test_skip_thin_commentary():
    reason = skip_extraction_reason(
        "Generative AI for thyroid FNA: are we there yet?",
        "Generative artificial intelligence represents a fascinating force. "
        "Anecdotal experience with ChatGPT confirms both its appeal and limitations.",
        ["Journal Article"],
    )
    assert reason and "commentary" in reason


def test_keep_substantive_review():
    reason = skip_extraction_reason(
        "What's new in digital and computational pathology 2026",
        "Digital and computational pathology are expanding rapidly worldwide, "
        "driven by advances in whole-slide imaging, AI algorithms, multimodal data "
        "integration, and improved digital infrastructure. Adoption continues to "
        "accelerate with professional guidelines and clinical integration pathways.",
        ["Journal Article"],
    )
    assert reason is None


def test_skip_nonsubstantive_fulltext():
    reason = skip_nonsubstantive_fulltext(
        "Short abstract about AI. Anecdotal notes.",
        [
            {"section_type": "abstract", "content": "Short abstract about AI."},
            {"section_type": "other", "content": "The authors declare no conflicts of interest."},
        ],
    )
    assert reason and "non-substantive" in reason


def test_keep_long_other_body():
    reason = skip_nonsubstantive_fulltext(
        "Abstract on digital pathology standards and AI adoption.",
        [
            {"section_type": "abstract", "content": "Abstract on digital pathology."},
            {"section_type": "other", "content": "x" * 2000},
        ],
    )
    assert reason is None


if __name__ == "__main__":
    test_skip_editorial()
    test_skip_special_issue_title()
    test_skip_workshop_report_title()
    test_skip_meeting_summary_abstract()
    test_skip_thin_commentary()
    test_keep_substantive_review()
    test_skip_nonsubstantive_fulltext()
    test_keep_long_other_body()
    print("all ok")
