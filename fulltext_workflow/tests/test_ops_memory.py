"""Unit tests for weekly ops memory helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

config.DB_PATH = str(_ROOT / "data" / "test_ops_memory.db")

from analysis.ops_memory import (  # noqa: E402
    create_ops_run,
    finalize_ops_run,
    fingerprint_gap_title,
    format_memory_prompt_block,
    jaccard_overlap,
    link_hotspot_week,
    load_recent_gaps,
    normalize_focus_key,
    persist_debate_report,
    persist_gaps_from_report,
    tag_revisited_against_memory,
)
from db.schema import fetch_ops_gap_items_for_runs, init_db  # noqa: E402

SAMPLE_REPORT = """
## Research gap analysis

### Research gap 1: NPC radiomics prognosis modeling
**Research question**: Can multimodal radiomics improve NPC OS prediction?

### Research gap 2: Pathomics subtype discovery for NPC
**Research question**: Unsupervised subtypes on WSI.
"""


def _reset_ops_db() -> None:
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
    init_db()


def test_normalize_focus_key_empty_is_all():
    assert normalize_focus_key(None) == "__all__"
    assert normalize_focus_key("") == "__all__"
    assert normalize_focus_key("  ") == "__all__"


def test_normalize_focus_key_lower_strip():
    assert normalize_focus_key("  Nasopharyngeal Carcinoma ") == "nasopharyngeal carcinoma"


def test_fingerprint_stable_and_order_invariant():
    a = fingerprint_gap_title("Survival prediction with radiomics")
    b = fingerprint_gap_title("radiomics with Survival prediction")
    assert a == b
    assert len(a) == 16


def test_jaccard_identical_high():
    assert jaccard_overlap(
        "NPC radiomics prognosis deep learning",
        "NPC radiomics prognosis deep learning",
    ) == 1.0


def test_jaccard_unrelated_low():
    score = jaccard_overlap(
        "breast cancer pathomics grading",
        "cardiac CTA stenosis scoring",
    )
    assert score < 0.3


def test_persist_and_load_lookback_four():
    _reset_ops_db()
    ids = []
    for i in range(5):
        rid = create_ops_run("nasopharyngeal carcinoma", "gap-debate")
        persist_gaps_from_report(
            rid,
            SAMPLE_REPORT.replace("NPC", f"NPC{i}" if i < 4 else "NPC"),
        )
        finalize_ops_run(rid, gap_report_path=f"output/t{i}.md")
        ids.append(rid)
    bundle = load_recent_gaps("nasopharyngeal carcinoma", limit_runs=4)
    assert len(bundle.run_ids) == 4
    assert ids[0] not in bundle.run_ids
    assert ids[-1] in bundle.run_ids


def test_focus_lanes_do_not_mix():
    _reset_ops_db()
    r1 = create_ops_run("breast cancer", "gap-debate")
    persist_gaps_from_report(r1, SAMPLE_REPORT.replace("NPC", "breast"))
    finalize_ops_run(r1)
    r2 = create_ops_run(None, "gap-debate")
    persist_gaps_from_report(r2, "### Research gap 1: Global radiomics gap\n")
    finalize_ops_run(r2)
    breast = load_recent_gaps("breast cancer")
    all_lane = load_recent_gaps(None)
    assert breast.run_ids == [r1]
    assert all_lane.run_ids == [r2]


def test_memory_prompt_and_revisited_tag():
    _reset_ops_db()
    rid = create_ops_run("npc", "gap_ui")
    persist_gaps_from_report(rid, SAMPLE_REPORT)
    finalize_ops_run(rid)
    bundle = load_recent_gaps("npc")
    block = format_memory_prompt_block(bundle)
    assert "Ops memory" in block
    tagged = tag_revisited_against_memory(
        ["NPC radiomics prognosis modeling", "Completely novel cardiac gap"],
        bundle,
    )
    status_map = dict(tagged)
    assert status_map["NPC radiomics prognosis modeling"] == "revisited"
    assert status_map["Completely novel cardiac gap"] == "reported"


def test_persist_debate_marks_revisited():
    _reset_ops_db()
    rid0 = create_ops_run("npc", "gap-debate")
    persist_gaps_from_report(rid0, SAMPLE_REPORT)
    finalize_ops_run(rid0)
    rid1 = persist_debate_report(
        SAMPLE_REPORT, focus="npc", source="gap-debate", enabled=True
    )
    assert rid1 is not None
    items = fetch_ops_gap_items_for_runs([rid1])
    assert any(it["status"] == "revisited" for it in items)
    assert persist_debate_report(SAMPLE_REPORT, focus="npc", source="x", enabled=False) is None


def test_link_hotspot_creates_or_updates_run():
    _reset_ops_db()
    rid = link_hotspot_week("2026-W29")
    rid2 = link_hotspot_week("2026-W29")
    assert rid == rid2


def test_persist_proposal_fills_fields_and_links_gap():
    from analysis.ops_memory import persist_proposal
    from db.schema import get_conn

    _reset_ops_db()
    rid = create_ops_run("npc", "gap_ui")
    persist_gaps_from_report(rid, SAMPLE_REPORT)
    finalize_ops_run(rid)
    prop_id = persist_proposal(
        rid,
        gap_title="NPC radiomics prognosis modeling",
        proposal_md="# Proposal\n\n" + ("body " * 100),
        feasibility_score=0.81,
        critic_score=8.2,
        status="generated",
    )
    assert prop_id is not None
    with get_conn() as conn:
        row = dict(
            conn.execute(
                "SELECT gap_item_id, proposal_path, proposal_md, status, "
                "feasibility_score, critic_score FROM ops_proposals WHERE id=?",
                (prop_id,),
            ).fetchone()
        )
        run = dict(
            conn.execute(
                "SELECT proposal_report_path FROM ops_runs WHERE run_id=?",
                (rid,),
            ).fetchone()
        )
    assert row["gap_item_id"] is not None
    assert row["status"] == "generated"
    assert row["feasibility_score"] == 0.81
    assert row["critic_score"] == 8.2
    assert row["proposal_path"]
    assert os.path.isfile(row["proposal_path"])
    assert run["proposal_report_path"] == row["proposal_path"]


def test_resolve_ops_memory_block_respects_flag():
    from gap_agent import resolve_ops_memory_block  # noqa: E402

    _reset_ops_db()
    rid = create_ops_run("npc", "gap_ui")
    persist_gaps_from_report(rid, SAMPLE_REPORT)
    finalize_ops_run(rid)
    assert resolve_ops_memory_block("npc", True)
    assert resolve_ops_memory_block("npc", False) == ""


if __name__ == "__main__":
    tests = [
        test_normalize_focus_key_empty_is_all,
        test_normalize_focus_key_lower_strip,
        test_fingerprint_stable_and_order_invariant,
        test_jaccard_identical_high,
        test_jaccard_unrelated_low,
        test_persist_and_load_lookback_four,
        test_focus_lanes_do_not_mix,
        test_memory_prompt_and_revisited_tag,
        test_persist_debate_marks_revisited,
        test_link_hotspot_creates_or_updates_run,
        test_persist_proposal_fills_fields_and_links_gap,
        test_resolve_ops_memory_block_respects_flag,
    ]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(tests)} tests passed.")
