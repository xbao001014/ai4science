"""Tests for multi-level keyword search on long gap titles."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

_TEST_DB = str(_ROOT / "data" / "test_keyword_search.db")
config.DB_PATH = _TEST_DB

from analysis.focus_filter import (  # noqa: E402
    meaningful_keyword_tokens,
    resolve_topic_pmids,
    search_papers_for_topic,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402

# Intentionally avoids disease-concept phrases so resolve falls through to token_score.
LONG_GAP = "Cross Attention MIL Aggregator for Slide Level Heterogeneity Modeling"


def _setup() -> None:
    config.DB_PATH = _TEST_DB
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
    init_db()


def _seed_wsi_fixture() -> None:
    paper = upsert_paper({
        "pmid": "92000001",
        "title": (
            "Cross attention MIL aggregator for slide-level heterogeneity "
            "modeling on whole-slide images"
        ),
        "year": 2025,
        "abstract": "Computational pathology multiple instance learning study.",
        "extraction_done": 1,
    })
    method_id = upsert_entity("cross attention mil", "Method")
    insert_relation(
        "Paper", paper, "APPLIES_METHOD", "Method", method_id,
        source_pmid="92000001", evidence_section="methods",
    )


def test_meaningful_tokens_drop_stopwords():
    tokens = meaningful_keyword_tokens(LONG_GAP)
    assert "for" not in tokens
    assert "cross" in tokens
    assert "attention" in tokens
    assert "mil" in tokens
    assert "heterogeneity" in tokens


def test_long_gap_title_falls_back_to_token_score():
    _setup()
    _seed_wsi_fixture()
    pmids, strategy = resolve_topic_pmids(LONG_GAP)
    assert pmids == ["92000001"]
    assert strategy.startswith("token_score")


def test_search_papers_for_topic_returns_papers_for_long_gap():
    _setup()
    _seed_wsi_fixture()
    rows, strategy = search_papers_for_topic(LONG_GAP, limit=10)
    assert len(rows) >= 1
    assert "92000001" in {row["pmid"] for row in rows}
    assert strategy.startswith("token_score")


def test_short_phrase_still_uses_full_phrase_match():
    _setup()
    _seed_wsi_fixture()
    _, strategy = search_papers_for_topic("cross attention mil", limit=10)
    assert strategy == "full_phrase"


def test_keyword_and_mesh_metadata_participate_in_retrieval():
    _setup()
    upsert_paper({
        "pmid": "92000002",
        "title": "A computational pathology benchmark",
        "year": 2024,
        "abstract": "Evaluation on digitized tissue.",
        "keywords": ["weak supervision", "support vector machine"],
        "mesh_terms": ["Breast Neoplasms"],
    })
    rows, _ = search_papers_for_topic("weak supervision", limit=10)
    assert [row["pmid"] for row in rows] == ["92000002"]


def test_method_and_disease_aliases_match_canonical_metadata():
    _setup()
    paper_id = upsert_paper({
        "pmid": "92000003",
        "title": "Validation study in mammary carcinoma",
        "year": 2024,
        "abstract": "A support vector machine was externally validated.",
    })
    disease_id = upsert_entity("breast cancer", "Disease")
    method_id = upsert_entity("support vector machines", "Method")
    insert_relation(
        "Paper", paper_id, "TARGETS_DISEASE", "Disease", disease_id,
        source_pmid="92000003",
    )
    insert_relation(
        "Paper", paper_id, "APPLIES_METHOD", "Method", method_id,
        source_pmid="92000003",
    )
    rows, strategy = search_papers_for_topic("SVM breast cancer", limit=10)
    assert [row["pmid"] for row in rows] == ["92000003"]
    assert strategy.startswith("hybrid_score")


def test_mixed_disease_query_does_not_return_every_disease_paper():
    _setup()
    for pmid, task in (("92000004", "segmentation"), ("92000005", "classification")):
        paper_id = upsert_paper({
            "pmid": pmid,
            "title": f"Breast cancer {task} study",
            "year": 2024,
        })
        disease_id = upsert_entity("breast cancer", "Disease")
        insert_relation(
            "Paper", paper_id, "TARGETS_DISEASE", "Disease", disease_id,
            source_pmid=pmid,
        )
    pmids, strategy = resolve_topic_pmids("breast cancer segmentation")
    assert pmids == ["92000004"]
    assert strategy.startswith("hybrid_score")


def test_upsert_entity_merges_curated_aliases_and_records_surface():
    _setup()
    from db.schema import get_conn

    canonical_id = upsert_entity("support vector machine", "Method")
    alias_id = upsert_entity("SVM", "Method")
    assert alias_id == canonical_id
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name, aliases FROM entities WHERE id=?", (canonical_id,)
        ).fetchone()
    assert row["name"] == "support vector machine"
    assert "svm" in (row["aliases"] or "")


def test_hyphenated_method_is_not_lost_by_sql_candidate_prefilter():
    _setup()
    paper_id = upsert_paper({
        "pmid": "92000006",
        "title": "U-Net segmentation for pathology",
        "year": 2024,
    })
    method_id = upsert_entity("u-net", "Method")
    insert_relation(
        "Paper", paper_id, "APPLIES_METHOD", "Method", method_id,
        source_pmid="92000006",
    )
    rows, _ = search_papers_for_topic("UNet", limit=10)
    assert [row["pmid"] for row in rows] == ["92000006"]


def test_unet_query_does_not_expand_to_unet_plus_plus():
    from analysis.retrieval import build_retrieval_plan

    plain = build_retrieval_plan("UNet breast cancer")
    plus = build_retrieval_plan("UNet++ breast cancer")
    assert plain["method_concepts"] == ["u-net"]
    assert plus["method_concepts"] == ["u-net++"]


if __name__ == "__main__":
    test_meaningful_tokens_drop_stopwords()
    test_long_gap_title_falls_back_to_token_score()
    test_search_papers_for_topic_returns_papers_for_long_gap()
    test_short_phrase_still_uses_full_phrase_match()
    print("all ok")
