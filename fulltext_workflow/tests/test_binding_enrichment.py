"""Pass-2 binding annotations for method×disease rows."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.binding_enrichment import (  # noqa: E402
    actionability_bump,
    actionability_hint,
    enrich_method_disease_rows,
)
from analysis.gap_tools import (  # noqa: E402
    tool_literature_impact_priority_matrix,
    tool_method_disease_combo_gap,
)
from analysis.weekly_hotspot import (  # noqa: E402
    compute_emerging_gap_opportunities,
    compute_weekly_hotspots,
)
from db.schema import (  # noqa: E402
    init_db,
    insert_relation,
    upsert_entity,
    upsert_paper,
    upsert_paper_entity_binding,
)


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_actionability_hint_and_bump():
    assert actionability_hint(0, 0) == "no_binding"
    assert actionability_hint(2, 0) == "bound_no_public"
    assert actionability_hint(1, 1) == "public_data"
    assert actionability_bump(0, 0) == 0.0
    assert actionability_bump(2, 0) == 0.25
    assert actionability_bump(1, 1) == 0.5


def test_enrich_rows_with_and_without_binding(monkeypatch):
    _tmp_db(monkeypatch)
    upsert_paper({"pmid": "b1", "title": "t", "year": 2024})
    mid = upsert_entity("method-a", "Method")
    did = upsert_entity("disease-a", "Disease")
    ds = upsert_entity("camelyon16", "Dataset", access_class="public")
    upsert_paper_entity_binding("b1", mid, did, ds, evidence_quote="used on")

    rows = [
        {"method": "method-a", "disease": "disease-a"},
        {"method": "method-a", "disease": "disease-b"},
    ]
    out = enrich_method_disease_rows(rows)
    assert len(out) == 2
    hit = out[0]
    assert hit["binding_paper_cnt"] == 1
    assert hit["public_dataset_cnt"] == 1
    assert "camelyon16" in hit["public_dataset_names"]
    assert hit["actionability_hint"] == "public_data"
    miss = out[1]
    assert miss["binding_paper_cnt"] == 0
    assert miss["public_dataset_cnt"] == 0
    assert miss["public_dataset_names"] == []
    assert miss["actionability_hint"] == "no_binding"


def test_enrich_rows_bound_no_public(monkeypatch):
    _tmp_db(monkeypatch)
    upsert_paper({"pmid": "b1", "title": "t", "year": 2024})
    mid = upsert_entity("method-a", "Method")
    did = upsert_entity("disease-a", "Disease")
    ds = upsert_entity("private-ds", "Dataset", access_class="private")
    upsert_paper_entity_binding("b1", mid, did, ds, evidence_quote="used on")

    rows = [{"method": "method-a", "disease": "disease-a"}]
    out = enrich_method_disease_rows(rows)
    hit = out[0]
    assert hit["binding_paper_cnt"] == 1
    assert hit["public_dataset_cnt"] == 0
    assert hit["public_dataset_names"] == []
    assert hit["actionability_hint"] == "bound_no_public"


def _edge(pmid: str, paper_id: int, relation: str, name: str, etype: str) -> int:
    entity_id = upsert_entity(name, etype)
    insert_relation(
        "Paper", paper_id, relation, etype, entity_id, source_pmid=pmid, status="active",
    )
    return entity_id


def test_combo_gap_includes_binding_fields(monkeypatch):
    _tmp_db(monkeypatch)
    for index in range(3):
        pmid = f"c{index}"
        paper_id = upsert_paper({"pmid": pmid, "title": f"t{index}", "year": 2024})
        _edge(pmid, paper_id, "APPLIES_METHOD", "hot-method", "Method")
        _edge(pmid, paper_id, "TARGETS_DISEASE", "hot-disease", "Disease")
    for index in range(3):
        pmid = f"u{index}"
        paper_id = upsert_paper({"pmid": pmid, "title": f"u{index}", "year": 2024})
        _edge(pmid, paper_id, "TARGETS_DISEASE", "hot-disease-2", "Disease")
    method_id = upsert_entity("hot-method", "Method")
    disease_id = upsert_entity("hot-disease", "Disease")
    upsert_paper({"pmid": "cb", "title": "bind", "year": 2023})
    dataset_id = upsert_entity("tcga", "Dataset", access_class="public")
    upsert_paper_entity_binding("cb", method_id, disease_id, dataset_id)

    gaps = tool_method_disease_combo_gap().get("gaps") or []
    assert gaps
    for gap in gaps:
        assert "binding_paper_cnt" in gap
        assert "actionability_hint" in gap
        assert "public_dataset_cnt" in gap


def test_priority_matrix_bumps_score_without_changing_set(monkeypatch):
    _tmp_db(monkeypatch)
    for index in range(3):
        pmid = f"p{index}"
        paper_id = upsert_paper({"pmid": pmid, "title": f"t{index}", "year": 2024})
        _edge(pmid, paper_id, "APPLIES_METHOD", "m1", "Method")
        _edge(pmid, paper_id, "TARGETS_DISEASE", "d1", "Disease")
    for index in range(3):
        pmid = f"q{index}"
        paper_id = upsert_paper({"pmid": pmid, "title": f"u{index}", "year": 2024})
        _edge(pmid, paper_id, "TARGETS_DISEASE", "d2", "Disease")
        _edge(pmid, paper_id, "APPLIES_METHOD", "m2", "Method")

    before = tool_literature_impact_priority_matrix()
    keys = {(row["method"], row["disease"]) for row in before["data"]}
    assert ("m1", "d2") in keys
    method_id = upsert_entity("m1", "Method")
    disease_id = upsert_entity("d2", "Disease")
    dataset_id = upsert_entity("pub-ds", "Dataset", access_class="public")
    upsert_paper({"pmid": "bx", "title": "b", "year": 2022})
    upsert_paper_entity_binding("bx", method_id, disease_id, dataset_id)

    after = tool_literature_impact_priority_matrix()
    keys_after = {(row["method"], row["disease"]) for row in after["data"]}
    assert keys_after == keys
    row = next(
        row for row in after["data"]
        if row["method"] == "m1" and row["disease"] == "d2"
    )
    assert row["public_dataset_cnt"] >= 1
    assert row["gap_priority_score"] >= 0.5


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def test_emerging_opportunities_enrich_and_bump(monkeypatch):
    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)

    def paper(pmid: str, days_ago: int) -> int:
        return upsert_paper({
            "pmid": pmid,
            "title": pmid,
            "pub_date": _iso(days_ago),
            "year": int(_iso(days_ago)[:4]),
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

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    assert rows
    for row in rows:
        assert "binding_paper_cnt" in row
        assert "actionability_hint" in row

    target = next(
        row for row in rows
        if row["method"] == "method-a" and row["disease"] == "disease-b"
    )
    base = float(target["opportunity_score"])
    method_id = upsert_entity("method-a", "Method")
    disease_id = upsert_entity("disease-b", "Disease")
    dataset_id = upsert_entity("pub", "Dataset", access_class="public")
    upsert_paper({"pmid": "bind", "title": "b", "year": 2020})
    upsert_paper_entity_binding("bind", method_id, disease_id, dataset_id)

    rows2 = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    assert {(row["method"], row["disease"]) for row in rows2} == {
        (row["method"], row["disease"]) for row in rows
    }
    target2 = next(
        row for row in rows2
        if row["method"] == "method-a" and row["disease"] == "disease-b"
    )
    assert target2["public_dataset_cnt"] >= 1
    assert float(target2["opportunity_score"]) >= base + 0.5 - 1e-6
