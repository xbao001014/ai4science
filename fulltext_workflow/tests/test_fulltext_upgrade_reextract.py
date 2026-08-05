"""Tests for abstract→fulltext upgrade re-extract prep."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    clear_abstract_extractions_for_fulltext_upgrade,
    get_conn,
    init_db,
    insert_relation,
    list_papers_for_fulltext_upgrade,
    mark_extraction_done,
    mark_fulltext_status,
    set_paper_reconcile_status,
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


def _seed_abstract_extracted(pmid: str, *, year: int, ft_status: str) -> int:
    pid = upsert_paper(
        {
            "pmid": pmid,
            "title": f"Title {pmid}",
            "abstract": "Abstract body long enough.",
            "year": year,
            "journal_name": "J",
        }
    )
    mark_fulltext_status(pid, ft_status)
    mark_extraction_done(pid, "ai_algorithm")
    set_paper_reconcile_status(pid, "skipped_no_ft")
    mid = upsert_entity(f"method-{pmid}", "Method")
    insert_relation(
        "Paper",
        pid,
        "APPLIES_METHOD",
        "Method",
        mid,
        source_pmid=pmid,
        evidence_section="abstract",
        evidence_quote="q",
        extraction_granularity="abstract",
        confidence=0.9,
    )
    return pid


def test_list_upgrade_candidates_only_skipped_with_fulltext(monkeypatch):
    _tmp_db(monkeypatch)
    _seed_abstract_extracted("1", year=2025, ft_status="available")
    _seed_abstract_extracted("2", year=2024, ft_status="pdf_available")
    _seed_abstract_extracted("3", year=2023, ft_status="unavailable")
    done = upsert_paper(
        {"pmid": "4", "title": "D", "abstract": "A", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(done, "available")
    mark_extraction_done(done, "ai_algorithm")
    set_paper_reconcile_status(done, "done")

    rows = list_papers_for_fulltext_upgrade()
    pmids = [r["pmid"] for r in rows]
    assert pmids == ["1", "2"]  # year DESC; unavailable + done excluded


def test_clear_upgrade_removes_relations_and_resets_flags(monkeypatch):
    _tmp_db(monkeypatch)
    _seed_abstract_extracted("10", year=2025, ft_status="available")
    _seed_abstract_extracted("11", year=2024, ft_status="unavailable")

    n = clear_abstract_extractions_for_fulltext_upgrade()
    assert n == 1

    with get_conn() as conn:
        p10 = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid='10'"
        ).fetchone()
        p11 = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid='11'"
        ).fetchone()
        rel10 = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='10'"
        ).fetchone()[0]
        rel11 = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='11'"
        ).fetchone()[0]
    assert p10["extraction_done"] == 0
    assert p10["reconcile_status"] == "pending"
    assert rel10 == 0
    assert p11["extraction_done"] == 1
    assert p11["reconcile_status"] == "skipped_no_ft"
    assert rel11 == 1


def _section_extractor(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-key")
    from extractor import section_extractor as se

    return se


def test_run_extraction_upgrades_into_queue(monkeypatch):
    se = _section_extractor(monkeypatch)

    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "FULLTEXT_UPGRADE_REEXTRACT", True)
    monkeypatch.setattr(config, "DEFAULT_EXTRACT_LIMIT", 30)
    _seed_abstract_extracted("20", year=2025, ft_status="available")
    # also a plain pending paper
    upsert_paper(
        {
            "pmid": "21",
            "title": "Pending",
            "abstract": "Abstract body long enough.",
            "year": 2024,
            "journal_name": "J",
        }
    )

    seen: list[str] = []

    def fake_process(paper):
        seen.append(paper["pmid"])

    monkeypatch.setattr(se, "_process_paper", fake_process)
    se.run_extraction(limit=0)
    assert "20" in seen
    assert "21" in seen
    with get_conn() as conn:
        rel = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='20'"
        ).fetchone()[0]
    assert rel == 0  # cleared before process


def test_run_extraction_skips_upgrade_when_disabled(monkeypatch):
    se = _section_extractor(monkeypatch)

    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "FULLTEXT_UPGRADE_REEXTRACT", False)
    _seed_abstract_extracted("30", year=2025, ft_status="available")

    seen: list[str] = []
    monkeypatch.setattr(se, "_process_paper", lambda paper: seen.append(paper["pmid"]))
    se.run_extraction(limit=0)
    assert seen == []
    with get_conn() as conn:
        row = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid='30'"
        ).fetchone()
        rel = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='30'"
        ).fetchone()[0]
    assert row["extraction_done"] == 1
    assert row["reconcile_status"] == "skipped_no_ft"
    assert rel == 1


def test_run_extraction_pmid_list_does_not_auto_upgrade(monkeypatch):
    se = _section_extractor(monkeypatch)

    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "FULLTEXT_UPGRADE_REEXTRACT", True)
    _seed_abstract_extracted("40", year=2025, ft_status="available")

    seen: list[str] = []
    monkeypatch.setattr(se, "_process_paper", lambda paper: seen.append(paper["pmid"]))
    se.run_extraction(limit=0, pmids=["40"], force_reextract=False)
    # Without force_reextract, paper stays extraction_done=1; get_papers_by_pmids
    # still returns it and _process_paper is called — but relations must remain
    # because auto-upgrade prep must not run on pmid-list path.
    with get_conn() as conn:
        row = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid='40'"
        ).fetchone()
        rel = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='40'"
        ).fetchone()[0]
    assert row["extraction_done"] == 1
    assert row["reconcile_status"] == "skipped_no_ft"
    assert rel == 1
