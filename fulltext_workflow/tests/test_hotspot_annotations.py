"""Weekly board shows grounded annotations without changing its ranking."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.hotspot_annotations import attach_hotspot_annotations  # noqa: E402
from analysis.method_synonyms import resolve_method_canonical  # noqa: E402
from db.schema import (  # noqa: E402
    get_conn, init_db, insert_relation, insert_relation_evidence,
    upsert_entity, upsert_entity_mention, upsert_paper,
)


def test_weekly_rows_show_source_annotations_and_keep_order(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "hotspot.db")
    init_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    paper_id = upsert_paper({
        "pmid": "hotspot-1", "title": "Test", "pub_date": today,
        "date_precision": "day", "extraction_done": 1,
    })
    for name, entity_type, relation, quote, full, qualifiers in (
        ("GCN", "Method", "APPLIES_METHOD", "We used GCN.",
         "graph convolutional network", []),
        ("HER2-positive breast carcinoma", "Disease", "TARGETS_DISEASE",
         "We studied HER2-positive breast carcinoma.", "",
         [{"kind": "molecular", "phrase": "HER2-positive"}]),
    ):
        entity_id = upsert_entity(name, entity_type)
        relation_id = insert_relation(
            "Paper", paper_id, relation, entity_type, entity_id,
            source_pmid="hotspot-1", evidence_quote=quote,
        )
        evidence_id = insert_relation_evidence(
            relation_id, source_pmid="hotspot-1", evidence_quote=quote,
            evidence_status="located", context_text=quote,
        )
        upsert_entity_mention(
            evidence_id, relation_id, source_pmid="hotspot-1",
            entity_type=entity_type, surface_name=name, entity_id=entity_id,
            explicit_long_form=full, qualifiers=qualifiers,
        )
    with get_conn() as conn:
        disease_name = conn.execute(
            "SELECT name FROM entities WHERE type='Disease'"
        ).fetchone()[0]
    payload = {
        "new_methods": [{"name": resolve_method_canonical("GCN"), "emerging_score": 2.0},
                        {"name": "other-method", "emerging_score": 1.0}],
        "emerging_methods": [], "active_methods": [],
        "heating_diseases": [{"name": disease_name}],
    }
    details = attach_hotspot_annotations(payload, window_days=14)
    assert [r["name"] for r in payload["new_methods"]] == [
        resolve_method_canonical("GCN"), "other-method"
    ]
    assert payload["new_methods"][0]["paper_full_forms"] == "GCN → graph convolutional network"
    assert payload["new_methods"][0]["annotated_papers"] == 1
    assert payload["new_methods"][1]["annotation_status"] == "暂无注释"
    assert "HER2-positive" in payload["heating_diseases"][0]["disease_qualifiers"]
    assert {row["source_pmid"] for row in details} == {"hotspot-1"}
