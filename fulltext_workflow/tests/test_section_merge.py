"""Tests for section merging before extraction."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor.section_utils import merge_sections_by_type  # noqa: E402


def test_merge_other_fragments_into_one_job():
    sections = [
        {"section_type": "other", "title": "chunk1", "content": "part A"},
        {"section_type": "other", "title": "chunk2", "content": "part B"},
        {"section_type": "methods", "title": "Methods", "content": "we used resnet"},
    ]
    merged = merge_sections_by_type(sections)
    assert len(merged) == 2
    by_type = {m["section_type"]: m["content"] for m in merged}
    assert "part A" in by_type["other"] and "part B" in by_type["other"]
    assert by_type["methods"] == "we used resnet"


def test_skip_empty_sections():
    sections = [
        {"section_type": "other", "title": "", "content": "   "},
        {"section_type": "results", "title": "Results", "content": "auc 0.9"},
    ]
    merged = merge_sections_by_type(sections)
    assert len(merged) == 1
    assert merged[0]["section_type"] == "results"
