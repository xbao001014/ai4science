"""Tests for LLM triple coercion / validation."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor.triple_models import ExtractionResult, Triple  # noqa: E402


def test_coerce_subject_type_paper():
    t = Triple.model_validate(
        {
            "subject": {"name": "paper", "type": "Paper"},
            "relation": "APPLIES_METHOD",
            "object": {"name": "ssl-histonet", "type": "Method"},
            "metric_value": None,
            "confidence": 1.0,
            "evidence_quote": "we introduce SSL-HistoNet",
            "polarity": "asserted",
        }
    )
    assert t.subject.type == "Method"
    assert t.subject.name == "paper"
    assert t.object.name == "ssl-histonet"


def test_coerce_metric_value_float():
    t = Triple.model_validate(
        {
            "subject": {"name": "paper", "type": "Paper"},
            "relation": "ACHIEVES_METRIC",
            "object": {"name": "auc", "type": "Metric"},
            "metric_value": 0.98,
            "confidence": 1.0,
            "evidence_quote": "AUC of 0.98",
            "polarity": "asserted",
        }
    )
    assert t.metric_value == "0.98"


def test_extraction_result_accepts_paper_subjects():
    raw = {
        "triples": [
            {
                "subject": {"name": "paper", "type": "Paper"},
                "relation": "TARGETS_DISEASE",
                "object": {"name": "amyotrophic lateral sclerosis", "type": "Disease"},
                "metric_value": None,
                "confidence": 1.0,
                "evidence_quote": "ALS",
                "polarity": "asserted",
            },
            {
                "subject": {"name": "paper", "type": "Paper"},
                "relation": "ACHIEVES_METRIC",
                "object": {"name": "precision", "type": "Metric"},
                "metric_value": 0.98,
                "confidence": 1.0,
                "evidence_quote": "precision of 0.98",
                "polarity": "asserted",
            },
        ]
    }
    result = ExtractionResult.model_validate(raw)
    assert len(result.triples) == 2
    assert result.triples[1].metric_value == "0.98"


def test_compares_method_relation_validates():
    t = Triple.model_validate(
        {
            "subject": {"name": "paper", "type": "Method"},
            "relation": "COMPARES_METHOD",
            "object": {"name": "clam", "type": "Method"},
            "metric_value": None,
            "confidence": 1.0,
            "evidence_quote": "compare against CLAM",
            "polarity": "asserted",
        }
    )
    assert t.relation == "COMPARES_METHOD"
