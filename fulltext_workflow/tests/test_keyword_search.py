"""Tests for multi-level keyword search on long gap titles."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

config.DB_PATH = str(_ROOT / "data" / "test_keyword_search.db")

from analysis.focus_filter import (  # noqa: E402
    meaningful_keyword_tokens,
    resolve_topic_pmids,
    search_papers_for_topic,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402

LONG_GAP = "Intratumoral Habitat Imaging for Breast Cancer Heterogeneity"


def _setup() -> None:
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
    init_db()


def _seed_habitat_fixture() -> None:
    paper = upsert_paper({
        "pmid": "92000001",
        "title": (
            "Habitat imaging with intratumoral radiomics for prediction of "
            "axillary response in breast cancer"
        ),
        "year": 2025,
        "abstract": "Breast cancer heterogeneity study.",
        "extraction_done": 1,
    })
    method_id = upsert_entity("habitat imaging", "Method")
    disease_id = upsert_entity("breast cancer", "Disease")
    insert_relation(
        "Paper", paper, "APPLIES_METHOD", "Method", method_id,
        source_pmid="92000001", evidence_section="methods",
    )
    insert_relation(
        "Paper", paper, "TARGETS_DISEASE", "Disease", disease_id,
        source_pmid="92000001", evidence_section="methods",
    )


def test_meaningful_tokens_drop_stopwords():
    tokens = meaningful_keyword_tokens(LONG_GAP)
    assert "for" not in tokens
    assert "intratumoral" in tokens
    assert "habitat" in tokens
    assert "breast" in tokens


def test_long_gap_title_falls_back_to_token_score():
    _setup()
    _seed_habitat_fixture()
    pmids, strategy = resolve_topic_pmids(LONG_GAP)
    assert pmids == ["92000001"]
    assert strategy.startswith("token_score")


def test_search_papers_for_topic_returns_papers_for_long_gap():
    _setup()
    _seed_habitat_fixture()
    rows, strategy = search_papers_for_topic(LONG_GAP, limit=10)
    assert len(rows) >= 1
    assert "92000001" in {row["pmid"] for row in rows}
    assert strategy.startswith("token_score")


def test_short_phrase_still_uses_full_phrase_match():
    _setup()
    _seed_habitat_fixture()
    _, strategy = search_papers_for_topic("habitat imaging", limit=10)
    assert strategy == "full_phrase"


if __name__ == "__main__":
    test_meaningful_tokens_drop_stopwords()
    test_long_gap_title_falls_back_to_token_score()
    test_search_papers_for_topic_returns_papers_for_long_gap()
    test_short_phrase_still_uses_full_phrase_match()
    print("all ok")
