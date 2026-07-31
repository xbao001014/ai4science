"""Tests for disease-topic focus filtering in gap tools."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

config.DB_PATH = str(_ROOT / "data" / "test_focus_filter.db")

from analysis.focus_filter import (  # noqa: E402
    debate_or_corpus_papers,
    focus_sql_clause,
    normalize_focus,
)
from analysis.gap_lifecycle import compute_limitation_temporal_profiles  # noqa: E402
from analysis.gap_tools import (  # noqa: E402
    tool_combo_gap_temporal,
    tool_corpus_focus_coverage,
    tool_method_disease_combo_gap,
    tool_recent_highcite_papers,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _setup() -> None:
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
    init_db()


def _seed_npc_fixture() -> None:
    paper = upsert_paper({
        "pmid": "91000001",
        "title": "CLAM for nasopharyngeal carcinoma on WSI",
        "year": 2024,
        "abstract": "NPC computational pathology study.",
        "extraction_done": 1,
    })
    disease_id = upsert_entity("nasopharyngeal carcinoma", "Disease")
    method_id = upsert_entity("clam", "Method")
    lim_id = upsert_entity("small sample size", "Limitation")
    insert_relation(
        "Paper", paper, "TARGETS_DISEASE", "Disease", disease_id,
        source_pmid="91000001", evidence_section="methods",
    )
    insert_relation(
        "Paper", paper, "APPLIES_METHOD", "Method", method_id,
        source_pmid="91000001", evidence_section="methods",
    )
    insert_relation(
        "Paper", paper, "REPORTS_LIMITATION", "Limitation", lim_id,
        source_pmid="91000001", evidence_section="limitations",
        evidence_quote="limited cohort size",
        polarity="asserted",
    )


def test_normalize_focus_treats_all_as_none():
    assert normalize_focus("All") is None
    assert normalize_focus("  corpus  ") is None
    assert normalize_focus("nasopharyngeal carcinoma") == "nasopharyngeal carcinoma"


def test_limitation_temporal_uses_disease_focus_not_limitation_name():
    _setup()
    _seed_npc_fixture()
    rows = compute_limitation_temporal_profiles(focus="nasopharyngeal carcinoma")
    assert any(r["limitation_name"] == "small sample size" for r in rows)


def test_limitation_temporal_profile_attaches_provenance_pmid():
    from analysis.gap_tools import tool_limitation_temporal_profile

    _setup()
    _seed_npc_fixture()
    out = tool_limitation_temporal_profile(focus="nasopharyngeal carcinoma")
    hit = next(
        r for r in out["data"] if r.get("limitation_name") == "small sample size"
    )
    assert hit.get("source_pmid") == "91000001"
    assert "91000001" in str(hit.get("sample_pmids") or "")
    assert hit.get("evidence_quote") == "limited cohort size"


def test_author_stated_gaps_uses_paper_focus_not_limitation_name():
    from analysis.gap_tools import tool_author_stated_gaps

    _setup()
    _seed_npc_fixture()
    out = tool_author_stated_gaps(focus="nasopharyngeal carcinoma")
    names = [r["limitation"] for r in out["data"]]
    assert "small sample size" in names
    hit = next(r for r in out["data"] if r["limitation"] == "small sample size")
    assert "91000001" in str(hit.get("sample_pmids") or "")
    assert hit.get("source_pmid") == "91000001"
    assert hit.get("evidence_quote") == "limited cohort size"
    # Chinese focus alias must also hit papers, not require 鼻咽 in limitation text
    zh = tool_author_stated_gaps(focus="鼻咽癌")
    assert any(r["limitation"] == "small sample size" for r in zh["data"])


def test_limitation_impact_and_metrics_use_paper_focus_not_entity_name():
    from analysis.gap_tools import (
        tool_limitation_impact_rank,
        tool_metric_evidence_quality,
    )

    _setup()
    _seed_npc_fixture()
    paper_id = upsert_paper({"pmid": "91000001", "title": "CLAM for nasopharyngeal carcinoma on WSI"})
    metric_id = upsert_entity("auc", "Metric")
    insert_relation(
        "Paper",
        paper_id,
        "ACHIEVES_METRIC",
        "Metric",
        metric_id,
        source_pmid="91000001",
        evidence_section="results",
        metric_value="0.91",
    )
    impact = tool_limitation_impact_rank(focus="鼻咽癌")
    assert any(r["limitation"] == "small sample size" for r in impact["data"])
    metrics = tool_metric_evidence_quality(focus="nasopharyngeal carcinoma")
    assert any(r["metric"] == "auc" for r in metrics["results_backed"])


def test_combo_gap_temporal_finds_methods_on_focus_papers():
    _setup()
    _seed_npc_fixture()
    rows = tool_combo_gap_temporal(focus="nasopharyngeal carcinoma")["data"]
    assert rows
    assert any(r["method"] == "clam" for r in rows)


def test_method_disease_combo_not_empty_for_disease_focus():
    _setup()
    _seed_npc_fixture()
    gaps = tool_method_disease_combo_gap(focus="nasopharyngeal carcinoma")["gaps"]
    assert gaps


def test_corpus_focus_coverage_counts_subset():
    _setup()
    _seed_npc_fixture()
    cov = tool_corpus_focus_coverage(focus="nasopharyngeal carcinoma")
    assert cov["focus_subset"]["papers"] >= 1
    assert cov["focus_subset"]["limitation_relations"] >= 1


def test_recent_highcite_includes_title_only_focus_paper():
    """Title match must count even when Disease entity is missing."""
    _setup()
    upsert_paper({
        "pmid": "91000099",
        "title": "Deep learning WSI diagnosis of nasopharyngeal carcinoma",
        "year": 2024,
        "citation_count": 12,
        "extraction_done": 0,
    })
    rows = tool_recent_highcite_papers(focus="nasopharyngeal carcinoma")["data"]
    assert any(r.get("pmid") == "91000099" for r in rows)


def test_debate_or_corpus_papers_falls_back_when_debate_has_no_titles():
    """Evidence tab must not show 0 when focus corpus has papers."""
    _setup()
    _seed_npc_fixture()
    rows, strategy = debate_or_corpus_papers([], "nasopharyngeal carcinoma", limit=10)
    assert rows, strategy
    assert strategy.startswith("corpus_")
    assert any("nasopharyngeal" in (r.get("title") or "").lower() for r in rows)


def _seed_polyp_fixture() -> None:
    paper = upsert_paper({
        "pmid": "91000100",
        "title": "AI detection of colorectal polyps on colonoscopy",
        "year": 2024,
        "abstract": "CAD for colorectal polyps.",
        "extraction_done": 1,
    })
    disease_id = upsert_entity("colorectal polyps", "Disease")
    insert_relation(
        "Paper", paper, "TARGETS_DISEASE", "Disease", disease_id,
        source_pmid="91000100", evidence_section="methods",
    )


def test_focus_sql_zh_polyp_expands_english():
    clause = focus_sql_clause("p.title", "肠息肉")
    assert "colorectal polyp" in clause.lower()
    assert "colorectal" in clause.lower()


def test_corpus_coverage_zh_polyp_nonzero_on_fixture():
    _setup()
    _seed_polyp_fixture()
    cov = tool_corpus_focus_coverage(focus="肠息肉")
    assert cov["focus_subset"]["papers"] >= 1


def test_corpus_coverage_zh_polyp_matches_english_baseline():
    _setup()
    _seed_polyp_fixture()
    zh = tool_corpus_focus_coverage(focus="肠息肉")["focus_subset"]["papers"]
    en = tool_corpus_focus_coverage(focus="colorectal polyp")["focus_subset"]["papers"]
    assert zh >= 1
    assert en >= 1
    assert zh == en


def test_crc_abbr_does_not_match_ccrcc_substring():
    """Short abbr 'crc' must not LIKE-match 'ccrcc' (renal)."""
    from analysis.disease_synonyms import concept_match_sql_clause, resolve_disease_concept
    from db.schema import get_conn

    _setup()
    upsert_entity("colorectal cancer", "Disease")
    upsert_entity("colorectal cancer (crc)", "Disease")
    upsert_entity("mss crc", "Disease")
    upsert_entity("clear cell renal cell carcinoma (ccrcc)", "Disease")

    concept = resolve_disease_concept("肠癌")
    assert concept is not None
    clause = " AND (" + concept_match_sql_clause("e.name", concept) + ")"
    with get_conn() as conn:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM entities e WHERE e.type = 'Disease'" + clause
            ).fetchall()
        }
    assert "colorectal cancer" in names
    assert "colorectal cancer (crc)" in names
    assert "mss crc" in names
    assert "clear cell renal cell carcinoma (ccrcc)" not in names


if __name__ == "__main__":
    test_normalize_focus_treats_all_as_none()
    test_limitation_temporal_uses_disease_focus_not_limitation_name()
    test_combo_gap_temporal_finds_methods_on_focus_papers()
    test_method_disease_combo_not_empty_for_disease_focus()
    test_corpus_focus_coverage_counts_subset()
    test_recent_highcite_includes_title_only_focus_paper()
    test_debate_or_corpus_papers_falls_back_when_debate_has_no_titles()
    test_focus_sql_zh_polyp_expands_english()
    test_corpus_coverage_zh_polyp_nonzero_on_fixture()
    test_corpus_coverage_zh_polyp_matches_english_baseline()
    test_crc_abbr_does_not_match_ccrcc_substring()
    print("all ok")