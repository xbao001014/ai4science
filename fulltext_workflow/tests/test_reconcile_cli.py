"""Tests for reconcile CLI pmid-list filtering."""
from __future__ import annotations

import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import init_db, mark_extraction_done, upsert_paper  # noqa: E402
from main import cmd_reconcile  # noqa: E402


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_reconcile_pmid_list_skips_without_pass1(monkeypatch, capsys):
    _tmp_db(monkeypatch)
    upsert_paper({"pmid": "111", "title": "Done"})
    upsert_paper({"pmid": "222", "title": "Pending"})
    mark_extraction_done(1, "observational")

    list_path = Path(tempfile.gettempdir()) / "reconcile_test_pmids.txt"
    list_path.write_text("111\n222\n999\n", encoding="utf-8")

    fake_se = MagicMock()
    monkeypatch.setitem(sys.modules, "extractor.section_extractor", fake_se)

    cmd_reconcile(Namespace(pmid_list=str(list_path)))

    out = capsys.readouterr().out
    assert "Skipped 2 PMID(s) without Pass 1: ['222', '999']" in out
    assert "[Reconcile] 1 paper(s)" in out
