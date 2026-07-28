"""Tests for paper_improvement_suggestions store and Pass 2 wiring."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    get_conn,
    init_db,
    list_active_improvement_suggestions,
    replace_paper_improvement_suggestions,
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


def test_replace_suggestions_supersedes_prior(monkeypatch):
    _tmp_db(monkeypatch)
    pmid = "90000001"
    upsert_paper({"pmid": pmid, "title": "Suggestion store test"})
    lim_id = upsert_entity("lack of external validation", "Limitation")

    n1 = replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "external_validation",
                "suggestion": "Validate on an independent cohort.",
                "evidence_quote": "lack of external validation",
                "evidence_section": "limitations",
                "grounding": "author_stated",
                "confidence": 0.9,
            }
        ],
    )
    assert n1 == 1
    assert len(list_active_improvement_suggestions(pmid)) == 1

    n2 = replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "external_validation",
                "suggestion": "Validate on a multi-center WSI cohort.",
                "evidence_quote": "future external validation",
                "evidence_section": "future_work",
                "grounding": "synthesized",
                "confidence": 0.85,
            }
        ],
    )
    assert n2 == 1
    active = list_active_improvement_suggestions(pmid)
    assert len(active) == 1
    assert "multi-center" in active[0]["suggestion"]

    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM paper_improvement_suggestions WHERE source_pmid=?",
            (pmid,),
        ).fetchone()["c"]
    assert total == 2  # one superseded + one active
