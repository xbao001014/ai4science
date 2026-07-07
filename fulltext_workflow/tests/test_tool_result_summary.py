from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.tool_result_summary import (
    extract_corpus_focus_metrics,
    format_tool_result_summary,
)
from gap_ui import compute_stats


def test_corpus_focus_coverage_shows_focus_and_global_papers():
    message = format_tool_result_summary(
        "corpus_focus_coverage",
        {
            "focus_subset": {"papers": 25},
            "global": {"papers": 9280},
        },
    )
    assert message == "focus subset: 25 papers / global: 9280"


def test_list_results_keep_records_wording():
    message = format_tool_result_summary(
        "hotspot_entities",
        {"data": [{"name": "a"}, {"name": "b"}]},
    )
    assert message == "2 records"


def test_compute_stats_separates_records_from_summary_results():
    stats = compute_stats([
        {"type": "tool_call", "name": "corpus_focus_coverage"},
        {
            "type": "tool_result",
            "name": "corpus_focus_coverage",
            "result": {
                "focus_subset": {"papers": 25},
                "global": {"papers": 9280},
            },
        },
        {"type": "tool_call", "name": "hotspot_entities"},
        {
            "type": "tool_result",
            "name": "hotspot_entities",
            "result": {"data": [{"x": 1}, {"x": 2}]},
        },
    ])
    assert stats["tools_called"] == 2
    assert stats["records_retrieved"] == 2
    assert stats["summary_results"] == 1


def test_extract_corpus_focus_metrics_returns_card_fields():
    metrics = extract_corpus_focus_metrics({
        "focus": "nasopharyngeal carcinoma",
        "coverage_ratio": 0.0027,
        "analysis_ready": False,
        "global": {"papers": 9280, "extracted": 9171, "fulltext_available": 5257},
        "focus_subset": {
            "papers": 25,
            "extracted": 24,
            "limitation_relations": 65,
            "method_entities": 30,
        },
        "warnings": ["low confidence"],
    })
    assert metrics["focus"] == "nasopharyngeal carcinoma"
    assert metrics["focus_papers"] == 25
    assert metrics["global_papers"] == 9280
    assert metrics["coverage_ratio"] == 0.0027
    assert metrics["warnings"] == ["low confidence"]
