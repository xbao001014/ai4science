"""Study-type downstream: covered channel + survey secondary sort helpers."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
import analysis.gap_tools as gap_tools  # noqa: E402
from analysis.weekly_hotspot import (  # noqa: E402
    compute_emerging_gap_opportunities,
    compute_weekly_hotspots,
)
from analysis.study_type_signals import (  # noqa: E402
    annotate_study_type_rows,
    build_covered_gap_rows,
    count_covers_by_disease,
    count_surveys_by_method,
)
from analysis.gap_tools import (  # noqa: E402
    tool_literature_impact_priority_matrix,
    tool_method_disease_combo_gap,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def _edge(pmid: str, paper_id: int, relation: str, name: str, etype: str) -> None:
    eid = upsert_entity(name, etype)
    insert_relation(
        "Paper", paper_id, relation, etype, eid, source_pmid=pmid, status="active",
    )


def test_count_surveys_and_covers(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "s1", "title": "t", "year": 2024})
    p2 = upsert_paper({"pmid": "s2", "title": "u", "year": 2023})
    _edge("s1", p1, "SURVEYS_METHOD", "method-a", "Method")
    _edge("s2", p2, "SURVEYS_METHOD", "method-a", "Method")
    _edge("s1", p1, "COVERS_DISEASE", "disease-x", "Disease")
    assert count_surveys_by_method()["method-a"] == 2
    assert count_covers_by_disease()["disease-x"] == 1


def test_annotate_study_type_rows(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "a1", "title": "t", "year": 2024})
    _edge("a1", p1, "SURVEYS_METHOD", "m1", "Method")
    _edge("a1", p1, "COVERS_DISEASE", "d1", "Disease")
    rows = [{"method": "m1", "disease": "d1"}, {"method": "m2", "disease": "d2"}]
    out = annotate_study_type_rows(rows)
    assert out[0]["surveys_method_paper_cnt"] == 1
    assert out[0]["covers_disease_paper_cnt"] == 1
    assert out[1]["surveys_method_paper_cnt"] == 0
    assert out[1]["covers_disease_paper_cnt"] == 0


def test_build_covered_skips_applied_cooccur(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "c1", "title": "t", "year": 2024})
    _edge("c1", p1, "COVERS_DISEASE", "d-cover", "Disease")
    _edge("c1", p1, "SURVEYS_METHOD", "hot-m", "Method")
    applied_cooccur = {("hot-m", "d-applied"): 1}
    covered = build_covered_gap_rows(
        method_names=["hot-m"],
        cover_disease_names=["d-cover", "d-applied"],
        applied_cooccur={("hot-m", "d-cover"): 0, ("hot-m", "d-applied"): 3},
        applied_pair_set={("hot-m", "d-applied")},
    )
    pairs = {(r["method"], r["disease"]) for r in covered}
    assert ("hot-m", "d-cover") in pairs
    assert ("hot-m", "d-applied") not in pairs
    row = next(r for r in covered if r["disease"] == "d-cover")
    assert row["gap_kind"] == "covered"
    assert row["gap"] == "unexplored"
    assert row["paper_cnt"] == 0
    assert row["covers_disease_paper_cnt"] >= 1


def test_combo_dual_channel_applied_and_covered(monkeypatch):
    _tmp_db(monkeypatch)
    for i in range(3):
        pid = upsert_paper({"pmid": f"ap{i}", "title": f"t{i}", "year": 2024})
        _edge(f"ap{i}", pid, "APPLIES_METHOD", "hot-method", "Method")
        _edge(f"ap{i}", pid, "TARGETS_DISEASE", "hot-disease", "Disease")
    # Include a target-only disease so the applied channel has an unexplored pair.
    cold_pid = upsert_paper({"pmid": "cold", "title": "cold", "year": 2024})
    _edge("cold", cold_pid, "TARGETS_DISEASE", "cold-disease", "Disease")
    # Cover-only disease (no APPLIES×TARGETS with hot-method).
    for i in range(3):
        pid = upsert_paper({"pmid": f"cv{i}", "title": f"c{i}", "year": 2024})
        _edge(f"cv{i}", pid, "COVERS_DISEASE", "cover-disease", "Disease")
        _edge(f"cv{i}", pid, "SURVEYS_METHOD", "hot-method", "Method")

    gaps = tool_method_disease_combo_gap().get("gaps") or []
    by_kind = {}
    for gap in gaps:
        by_kind.setdefault(gap.get("gap_kind"), []).append(gap)
        assert "surveys_method_paper_cnt" in gap
        assert "covers_disease_paper_cnt" in gap
    assert by_kind.get("applied")
    covered_pairs = {(gap["method"], gap["disease"]) for gap in by_kind.get("covered", [])}
    assert ("hot-method", "cover-disease") in covered_pairs
    for gap in by_kind.get("covered", []):
        assert not (gap["method"] == "hot-method" and gap["disease"] == "hot-disease")


def test_combo_applied_order_follows_method_disease_heat(monkeypatch):
    """Survey counts annotate applied gaps but must not reorder their heat order."""
    _tmp_db(monkeypatch)
    for index in range(4):
        pmid = f"low-{index}"
        paper_id = upsert_paper({"pmid": pmid, "title": pmid, "year": 2024})
        _edge(pmid, paper_id, "APPLIES_METHOD", "method-low-survey", "Method")
        _edge(pmid, paper_id, "TARGETS_DISEASE", "disease-first", "Disease")
    for index in range(3):
        pmid = f"high-{index}"
        paper_id = upsert_paper({"pmid": pmid, "title": pmid, "year": 2024})
        _edge(pmid, paper_id, "APPLIES_METHOD", "method-high-survey", "Method")
        _edge(pmid, paper_id, "TARGETS_DISEASE", "disease-second", "Disease")
    for index in range(5):
        pmid = f"survey-{index}"
        paper_id = upsert_paper({"pmid": pmid, "title": pmid, "year": 2024})
        _edge(pmid, paper_id, "SURVEYS_METHOD", "method-high-survey", "Method")

    applied = [
        gap for gap in tool_method_disease_combo_gap()["gaps"]
        if gap["gap_kind"] == "applied"
    ]

    assert [(gap["method"], gap["disease"]) for gap in applied[:2]] == [
        ("method-low-survey", "disease-second"),
        ("method-high-survey", "disease-first"),
    ]
    assert applied[0]["surveys_method_paper_cnt"] == 0
    assert applied[1]["surveys_method_paper_cnt"] == 5


def test_combo_reserves_slots_for_covered_channel(monkeypatch):
    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "TOOL_TOP_N", 21)
    for method_index in range(2):
        for paper_index in range(3):
            pmid = f"m{method_index}-{paper_index}"
            paper_id = upsert_paper({"pmid": pmid, "title": pmid, "year": 2024})
            _edge(pmid, paper_id, "APPLIES_METHOD", f"method-{method_index}", "Method")
            _edge(pmid, paper_id, "TARGETS_DISEASE", f"disease-{method_index}", "Disease")
    for disease_index in range(2, 21):
        pmid = f"disease-{disease_index}"
        paper_id = upsert_paper({"pmid": pmid, "title": pmid, "year": 2024})
        _edge(pmid, paper_id, "TARGETS_DISEASE", f"disease-{disease_index}", "Disease")
    cover_paper = upsert_paper({"pmid": "cover", "title": "cover", "year": 2024})
    _edge("cover", cover_paper, "COVERS_DISEASE", "covered-only", "Disease")

    gaps = tool_method_disease_combo_gap()["gaps"]

    assert len([gap for gap in gaps if gap["gap_kind"] == "applied"]) == 30
    assert any(gap["gap_kind"] == "covered" for gap in gaps)


def test_combo_covered_excluded_when_applied_cooccur(monkeypatch):
    _tmp_db(monkeypatch)
    for i in range(3):
        pid = upsert_paper({"pmid": f"both{i}", "title": f"t{i}", "year": 2024})
        _edge(f"both{i}", pid, "APPLIES_METHOD", "m", "Method")
        _edge(f"both{i}", pid, "TARGETS_DISEASE", "d", "Disease")
        _edge(f"both{i}", pid, "COVERS_DISEASE", "d", "Disease")

    gaps = tool_method_disease_combo_gap().get("gaps") or []
    covered = [
        gap
        for gap in gaps
        if gap.get("gap_kind") == "covered"
        and gap["method"] == "m"
        and gap["disease"] == "d"
    ]
    assert covered == []


def test_priority_matrix_secondary_sort_by_survey(monkeypatch):
    """Tied priority rows rank survey-backed methods first."""
    _tmp_db(monkeypatch)
    survey_paper = upsert_paper({"pmid": "survey", "title": "survey", "year": 2024})
    _edge("survey", survey_paper, "SURVEYS_METHOD", "method-hi", "Method")

    monkeypatch.setattr(
        gap_tools,
        "tool_method_disease_combo_gap",
        lambda focus=None: {
            "gaps": [
                {"method": "method-lo", "disease": "disease", "paper_cnt": 0, "gap": "unexplored"},
                {
                    "method": "method-hi",
                    "disease": "disease",
                    "paper_cnt": 0,
                    "gap": "unexplored",
                    "gap_kind": "covered",
                },
            ]
        },
    )

    rows = tool_literature_impact_priority_matrix()["data"]

    assert [row["method"] for row in rows] == ["method-hi", "method-lo"]
    assert [row["surveys_method_paper_cnt"] for row in rows] == [1, 0]
    assert [row["gap_priority_score"] for row in rows] == [3.0, 3.0]
    assert [row["gap_kind"] for row in rows] == ["covered", "applied"]


def test_emerging_secondary_sort_and_gap_kind(monkeypatch):
    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)

    from datetime import datetime, timedelta, timezone

    def paper(pmid: str, days_ago: int) -> int:
        pub_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        return upsert_paper({
            "pmid": pmid,
            "title": pmid,
            "pub_date": pub_date,
            "year": int(pub_date[:4]),
            "date_precision": "day",
            "extraction_done": 1,
        })

    p1 = paper("1", 3)
    _edge("1", p1, "APPLIES_METHOD", "method-a", "Method")
    _edge("1", p1, "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("1", p1, "PERFORMS_TASK", "survival prediction", "Task")
    p2 = paper("2", 4)
    _edge("2", p2, "APPLIES_METHOD", "method-a", "Method")
    _edge("2", p2, "TARGETS_DISEASE", "disease-b", "Disease")
    _edge("2", p2, "PERFORMS_TASK", "survival prediction", "Task")
    p3 = paper("3", 5)
    _edge("3", p3, "SURVEYS_METHOD", "method-a", "Method")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)

    assert rows
    assert all(row["gap_kind"] == "applied" for row in rows)
    assert all("surveys_method_paper_cnt" in row for row in rows)
    assert all(int(row["surveys_method_paper_cnt"]) >= 0 for row in rows)
    scores = [float(row["opportunity_score"]) for row in rows]
    assert scores == sorted(scores, reverse=True)
