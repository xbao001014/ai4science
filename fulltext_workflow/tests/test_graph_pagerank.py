"""Tests for focus-seeded entity PageRank (graph_tools)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

config.DB_PATH = str(_ROOT / "data" / "test_graph_pagerank.db")

from analysis import graph_tools  # noqa: E402
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _setup() -> None:
    graph_tools.invalidate_cache()
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
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


def _seed() -> None:
    # Focus paper: NPC + CLAM co-occur
    p1 = upsert_paper({
        "pmid": "92000001",
        "title": "CLAM for nasopharyngeal carcinoma on WSI",
        "year": 2024,
        "abstract": "NPC study",
        "extraction_done": 1,
    })
    _link("92000001", p1, "Disease", "nasopharyngeal carcinoma", "TARGETS_DISEASE")
    _link("92000001", p1, "Method", "clam", "APPLIES_METHOD")
    _link("92000001", p1, "Method", "deep learning", "APPLIES_METHOD")

    # Unrelated paper: breast + SVM — must not dominate focused ranking
    p2 = upsert_paper({
        "pmid": "92000002",
        "title": "SVM for breast cancer staging",
        "year": 2023,
        "abstract": "breast study",
        "extraction_done": 1,
    })
    _link("92000002", p2, "Disease", "breast cancer", "TARGETS_DISEASE")
    _link("92000002", p2, "Method", "support vector machine", "APPLIES_METHOD")


def test_focus_pagerank_returns_methods_from_focus_papers_not_name_substring():
    """focus is disease/topic seed, not Method name filter."""
    _setup()
    _seed()
    out = graph_tools.tool_graph_entity_pagerank(
        entity_type="Method",
        focus="nasopharyngeal carcinoma",
        top_n=10,
    )
    names = {r["entity"] for r in out["data"]}
    assert "clam" in names or "deep learning" in names
    assert "support vector machine" not in names


def test_pagerank_scores_are_cached_per_focus():
    _setup()
    _seed()
    with patch.object(
        graph_tools, "_compute_pagerank", wraps=graph_tools._compute_pagerank
    ) as mock_pr:
        graph_tools.tool_graph_entity_pagerank(
            entity_type="Method", focus="nasopharyngeal carcinoma", top_n=5
        )
        graph_tools.tool_graph_entity_pagerank(
            entity_type="Method", focus="nasopharyngeal carcinoma", top_n=5
        )
        assert mock_pr.call_count == 1


def test_no_focus_still_includes_all_methods():
    _setup()
    _seed()
    out = graph_tools.tool_graph_entity_pagerank(
        entity_type="Method", focus=None, top_n=20
    )
    names = {r["entity"] for r in out["data"]}
    assert "clam" in names
    assert "support vector machine" in names