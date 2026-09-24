from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from db.paper_sources import upsert_source_paper
from db.schema import get_conn, get_papers_for_extraction, init_db, upsert_paper
from fetcher.source_fetcher import matches_title_abstract, pathology_domain_relevant


def test_preprint_idempotency_and_later_pmid(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "sources.db"))
    init_db()
    data = {
        "title": "Whole slide image analysis with deep learning",
        "abstract": "We analyze whole slide pathology images with deep learning.",
        "doi": "https://doi.org/10.1234/example",
        "pub_date": "2026-09-20",
        "year": 2026,
        "date_precision": "day",
        "journal_name": "Example Journal",
        "authors": [{"name": "Ada Example"}, {"name": "Ben Example"}],
    }
    paper_id, created = upsert_source_paper(
        data, source="arxiv", external_id="2609.12345", group="wsi_classification_segmentation"
    )
    assert created
    assert upsert_source_paper(
        data, source="arxiv", external_id="2609.12345", group="wsi_classification_segmentation"
    ) == (paper_id, False)
    assert get_papers_for_extraction()[0]["source_key"] == "arxiv:2609.12345"

    upsert_paper({"pmid": "12345678", "doi": "10.1234/example", "title": data["title"]})
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
        assert row["pmid"] == "12345678"
        assert row["source_key"] == "arxiv:2609.12345"
        assert row["full_text_status"] == "pending"
        assert row["journal_id"] is not None
        assert conn.execute("SELECT COUNT(*) FROM paper_authors WHERE paper_id=?", (paper_id,)).fetchone()[0] == 2


def test_title_abstract_filter_rejects_speech_pathology():
    query = "pathology[Title/Abstract] AND (foundation model[Title/Abstract] OR self-supervised[Title/Abstract])"
    title = "Self-supervised learning for speech pathology"
    abstract = "We study acoustic features."
    assert matches_title_abstract(query, title, abstract)
    assert not pathology_domain_relevant(title, abstract)
    assert pathology_domain_relevant("Digital pathology foundation model", "Whole slide images")
