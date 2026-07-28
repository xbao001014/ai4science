"""Tests for paper_improvement_suggestions store and Pass 2 wiring.

Pilot / manual success criteria (spec 2026-07-28-improvement-suggestions-design):
- ≥80% active suggestions have non-empty evidence_quote (limitation/future_work sections)
- Spot-check: no invented dataset/disease names in suggestions
- Re-run Pass 2 on same PMID: no duplicate active rows for same dedup key
- Topic aggregation returns ≥1 action bucket when ≥3 papers have suggestions
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    get_conn,
    init_db,
    list_active_improvement_suggestions,
    replace_paper_improvement_suggestions,
    upsert_entity,
    upsert_paper,
)


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_replace_suggestions_supersedes_prior(monkeypatch):
    _tmp_db(monkeypatch)
    pmid = "90000001"
    upsert_paper({"pmid": pmid, "title": "Suggestion store test"})
    lim_id = upsert_entity("lack of external validation", "Limitation")

    n1 = replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "external_validation",
                "suggestion": "Validate on an independent cohort.",
                "evidence_quote": "lack of external validation",
                "evidence_section": "limitations",
                "grounding": "author_stated",
                "confidence": 0.9,
            }
        ],
    )
    assert n1 == 1
    assert len(list_active_improvement_suggestions(pmid)) == 1

    n2 = replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "external_validation",
                "suggestion": "Validate on a multi-center WSI cohort.",
                "evidence_quote": "future external validation",
                "evidence_section": "future_work",
                "grounding": "synthesized",
                "confidence": 0.85,
            }
        ],
    )
    assert n2 == 1
    active = list_active_improvement_suggestions(pmid)
    assert len(active) == 1
    assert "multi-center" in active[0]["suggestion"]

    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM paper_improvement_suggestions WHERE source_pmid=?",
            (pmid,),
        ).fetchone()["c"]
    assert total == 2  # one superseded + one active


def test_parse_recommendation_rows_filters_vague_and_bad_enum():
    from extractor.improvement_actions import parse_recommendation_rows

    rows = parse_recommendation_rows(
        [
            {
                "limitation": "lack of external validation",
                "action_type": "external_validation",
                "suggestion": "Validate on an independent multi-center cohort.",
                "evidence_quote": "lack of external validation",
                "evidence_section": "limitations",
                "grounding": "synthesized",
                "confidence": 0.8,
            },
            {
                "limitation": "small sample size",
                "action_type": "expand_sample",
                "suggestion": "More research is needed.",
                "evidence_quote": "small sample",
                "evidence_section": "discussion",
                "grounding": "author_stated",
                "confidence": 0.7,
            },
            {
                "limitation": "x",
                "action_type": "not_a_real_type",
                "suggestion": "Do something concrete with locked splits.",
                "evidence_quote": "q",
                "evidence_section": "future_work",
                "grounding": "synthesized",
                "confidence": 0.6,
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["action_type"] == "external_validation"


def test_apply_reconcile_writes_suggestions(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "90000002"
    paper_id = upsert_paper({"pmid": pmid, "title": "Apply suggestions"})
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [],
            "bindings": [],
            "limitations": [
                {
                    "canonical": "lack of external validation",
                    "merges": [],
                    "quote": "no external validation",
                }
            ],
            "recommendations": [
                {
                    "limitation": "lack of external validation",
                    "action_type": "external_validation",
                    "suggestion": "Validate on an independent cohort with locked preprocessing.",
                    "evidence_quote": "future external validation is needed",
                    "evidence_section": "future_work",
                    "grounding": "synthesized",
                    "confidence": 0.8,
                }
            ],
        },
    )
    rows = list_active_improvement_suggestions(pmid)
    assert len(rows) == 1
    assert rows[0]["action_type"] == "external_validation"
    assert rows[0]["limitation_entity_id"] is not None


def test_empty_reconcile_clears_active_suggestions(monkeypatch):
    """Re-reconcile with empty recommendations must clear prior actives."""
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "90000005"
    paper_id = upsert_paper({"pmid": pmid, "title": "Empty re-reconcile clear"})
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [],
            "bindings": [],
            "limitations": [
                {
                    "canonical": "lack of external validation",
                    "merges": [],
                    "quote": "no external validation",
                }
            ],
            "recommendations": [
                {
                    "limitation": "lack of external validation",
                    "action_type": "external_validation",
                    "suggestion": "Validate on an independent cohort with locked preprocessing.",
                    "evidence_quote": "future external validation is needed",
                    "evidence_section": "future_work",
                    "grounding": "synthesized",
                    "confidence": 0.8,
                }
            ],
        },
    )
    assert len(list_active_improvement_suggestions(pmid)) == 1

    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [],
            "bindings": [],
            "limitations": [],
            "recommendations": [],
        },
    )
    assert list_active_improvement_suggestions(pmid) == []

    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM paper_improvement_suggestions WHERE source_pmid=?",
            (pmid,),
        ).fetchone()["c"]
        superseded = conn.execute(
            """SELECT COUNT(*) AS c FROM paper_improvement_suggestions
               WHERE source_pmid=? AND status='superseded'""",
            (pmid,),
        ).fetchone()["c"]
    assert total >= 1
    assert superseded >= 1


def test_parse_reconcile_payload_includes_recommendations():
    from extractor.fulltext_reconcile import parse_reconcile_payload

    p = parse_reconcile_payload(
        {
            "datasets": [],
            "bindings": [],
            "limitations": [],
            "recommendations": [
                {
                    "limitation": "single-center design",
                    "action_type": "multicenter",
                    "suggestion": "Recruit a second center with the same staining protocol.",
                    "evidence_quote": "single center",
                    "evidence_section": "limitations",
                    "grounding": "author_stated",
                    "confidence": 0.75,
                }
            ],
        }
    )
    assert len(p["recommendations"]) == 1
    assert p["recommendations"][0]["action_type"] == "multicenter"


def test_topic_action_aggregation(monkeypatch):
    from analysis.gap_tools import tool_improvement_suggestions_by_topic

    _tmp_db(monkeypatch)
    pmid = "90000003"
    upsert_paper(
        {
            "pmid": pmid,
            "title": "Breast cancer WSI grading with CNN",
            "abstract": "breast cancer digital pathology",
        }
    )
    lim_id = upsert_entity("lack of external validation", "Limitation")
    replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "external_validation",
                "suggestion": "Validate on an independent breast WSI cohort.",
                "evidence_quote": "no external validation",
                "evidence_section": "limitations",
                "grounding": "synthesized",
                "confidence": 0.9,
            }
        ],
    )
    out = tool_improvement_suggestions_by_topic("breast cancer")
    assert out["count"] >= 1
    row = out["data"][0]
    assert row["action_type"] == "external_validation"
    assert row["paper_cnt"] >= 1
    assert pmid in (row.get("sample_pmids") or "")

    # focus=None returns all active aggregations
    all_out = tool_improvement_suggestions_by_topic(None)
    assert all_out["count"] >= 1
    assert any(r["action_type"] == "external_validation" for r in all_out["data"])


def test_idea_tool_improvement_suggestions(monkeypatch):
    from idea_agent import tool_improvement_suggestions_for_topic

    _tmp_db(monkeypatch)
    pmid = "90000004"
    upsert_paper(
        {
            "pmid": pmid,
            "title": "Lung adenocarcinoma WSI classification",
            "abstract": "lung adenocarcinoma pathology AI",
        }
    )
    lim_id = upsert_entity("small sample size", "Limitation")
    replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "expand_sample",
                "suggestion": "Enlarge the training cohort with additional annotated WSIs.",
                "evidence_quote": "only 87 patients",
                "evidence_section": "limitations",
                "grounding": "synthesized",
                "confidence": 0.88,
            }
        ],
    )
    out = tool_improvement_suggestions_for_topic("lung adenocarcinoma")
    assert out["count"] >= 1
    assert out["data"][0]["action_type"] == "expand_sample"
