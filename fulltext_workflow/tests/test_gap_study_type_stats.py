"""QA stats for study-type-specific relations (SURVEYS_METHOD, etc.)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

config.DB_PATH = str(_ROOT / "data" / "test_gap_study_type_stats.db")

from analysis.gap_tools import (  # noqa: E402
    tool_hotspot_entities,
    tool_study_type_relation_stats,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _setup_db() -> None:
    db_path = config.DB_PATH
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()


def _link(pmid: str, paper_id: int, etype: str, name: str, relation: str) -> None:
    eid = upsert_entity(name, etype)
    insert_relation(
        "Paper",
        paper_id,
        relation,
        etype,
        eid,
        source_pmid=pmid,
        evidence_section="methods",
    )


def test_study_type_relation_stats_shape():
    _setup_db()
    out = tool_study_type_relation_stats()
    assert "data" in out
    names = {r["relation"] for r in out["data"]}
    for rel in (
        "SURVEYS_METHOD",
        "COVERS_DISEASE",
        "RELEASES_DATASET",
        "PRETRAINS_ON",
    ):
        assert rel in names


def test_study_type_relation_stats_counts():
    _setup_db()
    p1 = upsert_paper({"pmid": "93000001", "title": "Review A", "year": 2024, "abstract": "x"})
    p2 = upsert_paper({"pmid": "93000002", "title": "Review B", "year": 2023, "abstract": "y"})
    _link("93000001", p1, "Method", "clam", "SURVEYS_METHOD")
    _link("93000001", p1, "Disease", "lung cancer", "COVERS_DISEASE")
    _link("93000002", p2, "Method", "mil", "SURVEYS_METHOD")

    out = tool_study_type_relation_stats()
    by_rel = {r["relation"]: r for r in out["data"]}
    assert by_rel["SURVEYS_METHOD"]["edge_cnt"] == 2
    assert by_rel["SURVEYS_METHOD"]["paper_cnt"] == 2
    assert by_rel["COVERS_DISEASE"]["edge_cnt"] == 1
    assert by_rel["RELEASES_DATASET"]["edge_cnt"] == 0
    assert by_rel["PRETRAINS_ON"]["edge_cnt"] == 0


def test_hotspot_entities_ignores_surveys_method():
    """Method heat must stay APPLIES_METHOD-only (SURVEYS_METHOD excluded)."""
    _setup_db()
    p1 = upsert_paper({"pmid": "93000010", "title": "R1", "year": 2024, "abstract": "a"})
    p2 = upsert_paper({"pmid": "93000011", "title": "R2", "year": 2023, "abstract": "b"})
    p3 = upsert_paper({"pmid": "93000012", "title": "R3", "year": 2022, "abstract": "c"})
    _link("93000010", p1, "Method", "survey-only", "SURVEYS_METHOD")
    _link("93000011", p2, "Method", "survey-only", "SURVEYS_METHOD")
    _link("93000012", p3, "Method", "applied", "APPLIES_METHOD")
    _link("93000011", p2, "Method", "applied", "APPLIES_METHOD")

    out = tool_hotspot_entities()
    names = {r["name"] for r in out["data"]}
    assert "survey-only" not in names
    assert "applied" in names
