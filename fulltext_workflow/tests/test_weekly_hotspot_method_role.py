"""Weekly hotspot payload includes method_role without changing maturity gates."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
import analysis.method_synonyms as method_synonyms  # noqa: E402
from analysis.weekly_hotspot import (  # noqa: E402
    compute_emerging_gap_opportunities,
    compute_weekly_hotspots,
)
from db.schema import get_conn, init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)
    monkeypatch.setattr(config, "HOTSPOT_ESTABLISHED_MIN_PAPERS", 10)
    init_db()
    return path


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _paper(pmid: str, days_ago: int) -> int:
    return upsert_paper({
        "pmid": pmid,
        "title": pmid,
        "pub_date": _iso(days_ago),
        "year": int(_iso(days_ago)[:4]),
        "date_precision": "day",
        "extraction_done": 1,
    })


def _edge(
    pmid: str,
    paper_id: int,
    name: str,
    *,
    method_role: str | None = None,
) -> None:
    entity_id = upsert_entity(name, "Method", method_role=method_role)
    insert_relation(
        "Paper", paper_id, "APPLIES_METHOD", "Method", entity_id,
        source_pmid=pmid, status="active",
    )


def _related_edge(
    pmid: str,
    paper_id: int,
    relation: str,
    name: str,
    entity_type: str,
) -> None:
    entity_id = upsert_entity(name, entity_type)
    insert_relation(
        "Paper", paper_id, relation, entity_type, entity_id,
        source_pmid=pmid, status="active",
    )


def test_emerging_and_active_have_method_role(monkeypatch):
    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 2)
    for i, pmid in enumerate(("1", "2"), start=1):
        pid = _paper(pmid, i)
        _edge(pmid, pid, "niche-mil-aggregator-x")
        _related_edge(pmid, pid, "TARGETS_DISEASE", "disease-a", "Disease")
    for i, pmid in enumerate(("3", "4"), start=1):
        pid = _paper(pmid, i + 2)
        _edge(pmid, pid, "resnet-50")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    emerging = {r["name"]: r for r in payload["emerging_methods"]}
    active = {r["name"]: r for r in payload["active_methods"]}

    assert emerging["niche-mil-aggregator-x"]["method_role"] == "aggregator"
    assert active["resnet-50"]["method_role"] == "backbone"
    # resnet-50 is established blacklist → excluded from emerging
    assert "resnet-50" not in emerging
    assert "resnet-50" in active
    assert payload.get("hot_combos")
    assert payload.get("hot_combos_by_method")
    for row in payload.get("hot_combos") or []:
        assert row.get("method_role") in {
            "backbone", "aggregator", "classical_ml", "tool", "unknown",
        }
    for row in payload.get("hot_combos_by_method") or []:
        assert row.get("method_role") in {
            "backbone", "aggregator", "classical_ml", "tool", "unknown",
        }


def test_weekly_hotspot_prefers_stored_method_role(monkeypatch):
    _tmp_db(monkeypatch)
    method = "opaque-method-z"
    paper_id = _paper("stored-role", 1)
    _edge("stored-role", paper_id, method, method_role="tool")
    _related_edge(
        "stored-role", paper_id, "TARGETS_DISEASE", "disease-a", "Disease"
    )

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)

    assert payload["active_methods"][0]["method_role"] == "tool"
    assert payload["hot_combos"][0]["method_role"] == "tool"
    assert payload["hot_combos_by_method"][0]["method_role"] == "tool"


def test_weekly_hotspot_preserves_alias_stored_method_role(monkeypatch):
    _tmp_db(monkeypatch)
    alias = "opaque-method-alias"
    canonical = "opaque-method-canonical"
    monkeypatch.setitem(method_synonyms._METHOD_SYNONYMS, alias, canonical)
    paper_id = _paper("stored-alias-role", 1)
    _edge("stored-alias-role", paper_id, alias, method_role="tool")
    _related_edge(
        "stored-alias-role", paper_id, "TARGETS_DISEASE", "disease-a", "Disease"
    )

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)

    assert payload["active_methods"][0]["name"] == canonical
    assert payload["active_methods"][0]["method_role"] == "tool"
    assert payload["hot_combos"][0]["method"] == canonical
    assert payload["hot_combos"][0]["method_role"] == "tool"


def test_methods_ui_renders_five_role_sections_in_order(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-key")
    import gap_ui

    headings: list[str] = []
    rendered_roles: list[str] = []
    monkeypatch.setattr(gap_ui.st, "subheader", headings.append)
    monkeypatch.setattr(
        gap_ui,
        "safe_table",
        lambda frame: rendered_roles.append(str(frame.iloc[0]["method_role"])),
    )
    rows = [
        {"name": "unclassified", "method_role": "not-a-role"},
        {"name": "tool", "method_role": "tool"},
        {"name": "classic", "method_role": "classical_ml"},
        {"name": "aggregator", "method_role": "aggregator"},
        {"name": "backbone", "method_role": "backbone"},
    ]

    gap_ui._render_methods_by_role(rows)

    assert rendered_roles == [
        "backbone",
        "aggregator",
        "classical_ml",
        "tool",
        "not-a-role",
    ]
    assert headings == [
        "基座 / 骨干（1）",
        "聚合器 / 贡献模块（1）",
        "传统 ML（1）",
        "工具 / 平台（1）",
        "未分类（1）",
    ]


def test_emerging_gap_opportunity_has_method_role(monkeypatch):
    _tmp_db(monkeypatch)
    method = "opaque-opportunity-method"
    support_paper = _paper("support", 2)
    _edge("support", support_paper, method, method_role="tool")
    _related_edge(
        "support", support_paper, "TARGETS_DISEASE", "disease-a", "Disease"
    )
    _related_edge(
        "support", support_paper, "PERFORMS_TASK", "survival prediction", "Task"
    )
    target_paper = _paper("target", 3)
    _related_edge(
        "target", target_paper, "TARGETS_DISEASE", "disease-b", "Disease"
    )
    _related_edge(
        "target", target_paper, "PERFORMS_TASK", "survival prediction", "Task"
    )
    payload = {
        "emerging_methods": [{
            "name": method,
            "method_maturity": "nascent",
            "corpus_paper_cnt": 1,
            "recent_cnt": 1,
            "velocity": 1.0,
            "emerging_score": 1.0,
        }],
        "active_methods": [],
        "heating_diseases": [{"name": "disease-b"}],
    }

    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)

    assert rows
    assert rows[0]["method_role"] == "tool"
