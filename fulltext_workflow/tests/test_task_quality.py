"""Tests for Task quality tiers."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.task_quality import (  # noqa: E402
    audit_task_names,
    classify_task_quality,
    run_task_quality_audit,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_reject_generic_and_narrative():
    assert classify_task_quality("classification") == "reject"
    assert classify_task_quality("workshop report on digital pathology") == "reject"


def test_weak_single_token_non_generic():
    # single token not in generic blacklist → weak (too coarse to bridge)
    assert classify_task_quality("quantification") == "weak"


def test_ok_specific_phrase():
    assert classify_task_quality("tumor subtype classification") == "ok"
    assert classify_task_quality("survival prediction") == "ok"
    assert classify_task_quality("prognosis prediction") == "ok"


def test_audit_counts():
    out = audit_task_names(
        [
            "classification",
            "tumor subtype classification",
            "quantification",
            "prognostic prediction",  # normalizes then ok
        ]
    )
    assert out["counts"]["reject"] >= 1
    assert out["counts"]["ok"] >= 2
    assert out["counts"]["weak"] >= 1


def test_run_task_quality_audit_markdown(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "90000001", "title": "Audit test", "extraction_done": 1})
    p2 = upsert_paper({"pmid": "90000002", "title": "No task paper", "extraction_done": 1})
    task_ok = upsert_entity("survival prediction", "Task")
    task_reject = upsert_entity("classification", "Task")
    task_weak = upsert_entity("quantification", "Task")
    insert_relation(
        "Paper", p1, "PERFORMS_TASK", "Task", task_ok, source_pmid="90000001"
    )
    insert_relation(
        "Paper", p1, "PERFORMS_TASK", "Task", task_reject, source_pmid="90000001"
    )
    insert_relation(
        "Paper", p2, "PERFORMS_TASK", "Task", task_weak, source_pmid="90000002"
    )

    md = run_task_quality_audit(limit_examples=10)
    lower = md.lower()
    assert "## reject" in lower or "### reject" in lower
    assert "## ok" in lower or "### ok" in lower
    assert "survival prediction" in md
    assert "classification" in md
    assert "performs_task" in lower
