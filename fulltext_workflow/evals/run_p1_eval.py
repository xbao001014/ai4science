"""P1 engineering eval: fulltext observability, retrieval, and agent handoff.

This suite intentionally excludes expert judgments of research-direction value.
It uses synthetic papers, a temporary SQLite database, and no network calls.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path[:0] = [str(ROOT), str(PROJECT)]


def paper(pmid: str, title: str, abstract: str, year: int) -> dict:
    return {
        "pmid": pmid, "doi": "", "pmc_id": None, "title": title,
        "abstract": abstract, "pub_date": f"{year}-01-01", "year": year,
        "date_precision": "day", "journal_name": "P1 Eval Journal",
        "journal_abbr": "P1E", "issn": None, "pub_types": [],
        "mesh_terms": [], "keywords": [], "source_queries": ["p1-eval"],
        "full_text_status": "available",
    }


def run() -> dict:
    import config
    from analysis.gap_tools import tool_literature_evidence_search
    from analysis.research_quality import enforce_moderator_handoff, validate_moderator_handoff
    from db.schema import (
        get_conn, init_db, insert_relation, insert_sections, upsert_entity,
        upsert_paper,
    )
    from extractor import section_extractor as se
    from extractor.fulltext_reconcile import ground_reconcile_payload
    from gap_agent import (
        MODERATOR_SYSTEM_PROMPT, SKEPTIC_SYSTEM_PROMPT,
        build_role_tool_bundle,
    )
    from llm_utils import truncate_for_llm

    checks: list[dict] = []

    def check(group: str, name: str, passed: bool, observed=None, expected=None):
        checks.append({
            "group": group, "name": name, "passed": bool(passed),
            "observed": observed, "expected": expected,
        })

    marker_text = "0123456789" * 8
    truncated = truncate_for_llm(marker_text, 32)
    check("fulltext", "truncation_respects_hard_cap", len(truncated) == 32, len(truncated), 32)
    check("fulltext", "truncation_is_visible", "truncated" in truncated, truncated[-20:], "marker")

    old_cap = config.EXTRACT_MAX_SECTION_CHARS
    old_llm = se.llm_call_structured
    try:
        config.EXTRACT_MAX_SECTION_CHARS = 32
        se.llm_call_structured = lambda *_: {"triples": []}
        audit = {}
        se._extract_from_text(
            "Study", "methods", "Methods", marker_text,
            study_type="ai_algorithm", audit=audit,
        )
    finally:
        config.EXTRACT_MAX_SECTION_CHARS = old_cap
        se.llm_call_structured = old_llm
    for key in ("source_chars", "sent_chars", "truncated", "outcome", "parsed", "postprocessed", "retained"):
        check("fulltext", f"section_audit_has_{key}", key in audit, audit.get(key), "present")

    reconcile = {
        "datasets": [], "covered_diseases": [], "limitations": [],
        "bindings": [], "recommendations": [],
        "surveyed_methods": [
            {"name": "CLAM", "quote": "We review CLAM."},
            {"name": "GhostNet", "quote": "Absent fabricated quote."},
        ],
    }
    grounded, rec_audit = ground_reconcile_payload(
        reconcile, [{"section_type": "introduction", "content": "We review CLAM."}]
    )
    check("fulltext", "reconcile_keeps_located_quote", len(grounded["surveyed_methods"]) == 1,
          len(grounded["surveyed_methods"]), 1)
    check("fulltext", "reconcile_rejects_unlocated_quote", rec_audit["rejected"] == 1,
          rec_audit["rejected"], 1)
    check("fulltext", "reconcile_labels_source_section",
          grounded["surveyed_methods"][0]["evidence_section"] == "introduction",
          grounded["surveyed_methods"][0]["evidence_section"], "introduction")
    check("fulltext", "reconcile_persists_offsets",
          grounded["surveyed_methods"][0]["evidence_start"] == 0 and
          grounded["surveyed_methods"][0]["evidence_end"] == 15,
          [grounded["surveyed_methods"][0]["evidence_start"], grounded["surveyed_methods"][0]["evidence_end"]],
          [0, 15])

    with tempfile.TemporaryDirectory(prefix="p1-eval-") as temp:
        old_db = config.DB_PATH
        config.DB_PATH = str(Path(temp) / "p1.sqlite")
        try:
            init_db()
            with get_conn() as conn:
                columns = {r[1] for r in conn.execute("PRAGMA table_info(extraction_audits)")}
            for col in ("source_chars", "sent_chars", "truncated", "outcome", "rejected_json"):
                check("fulltext", f"audit_table_has_{col}", col in columns, col in columns, True)

            p_id = upsert_paper(paper("21000", "Breast cancer pipeline", "Abstract", 2023))
            insert_sections(p_id, [
                {"section_type": "methods", "title": "Methods", "content": "We use CLAM.", "order_idx": 0},
                {"section_type": "results", "title": "Results", "content": "CLAM achieved AUC 0.91.", "order_idx": 1},
            ])
            old_extract = se._extract_from_text
            old_workers = config.EXTRACT_SECTION_WORKERS
            try:
                config.EXTRACT_SECTION_WORKERS = 1
                def fake_extract(title, section_type, section_title, content, **kwargs):
                    kwargs["audit"].update(
                        outcome="retained", source_chars=len(content), sent_chars=len(content),
                        truncated=False, parsed=1, postprocessed=1, retained=1,
                        rejected=[], empty_recheck=False, recall_check_reason=None,
                    )
                    return []
                se._extract_from_text = fake_extract
                se._extract_fulltext(
                    {"abstract": "Abstract"}, p_id, "21000", "Breast cancer pipeline",
                    "fulltext", study_type="ai_algorithm",
                )
            finally:
                se._extract_from_text = old_extract
                config.EXTRACT_SECTION_WORKERS = old_workers
            with get_conn() as conn:
                audit_rows = conn.execute("SELECT * FROM extraction_audits ORDER BY id").fetchall()
            check("fulltext", "full_pipeline_audits_each_section", len(audit_rows) == 2, len(audit_rows), 2)
            check("fulltext", "full_pipeline_preserves_section_identity",
                  {r["section_type"] for r in audit_rows} == {"methods", "results"},
                  sorted(r["section_type"] for r in audit_rows), ["methods", "results"])

            records = [
                ("21001", "Breast cancer segmentation validation", "breast cancer pathology", 2022,
                 "REPORTS_LIMITATION", "Limitation", "External validation for breast segmentation remains limited."),
                ("21002", "Breast cancer segmentation multicenter", "breast cancer pathology", 2027,
                 "APPLIES_METHOD", "Method", "We completed multicenter breast segmentation validation."),
                ("21003", "Lung cancer segmentation validation", "lung cancer pathology", 2021,
                 "REPORTS_LIMITATION", "Limitation", "External validation for lung segmentation remains limited."),
                ("21004", "CLAM for breast cancer classification", "breast cancer pathology", 2021,
                 "APPLIES_METHOD", "Method", "We applied CLAM to breast cancer classification."),
            ]
            for pmid, title, abstract, year, relation, entity_type, quote in records:
                paper_id = upsert_paper(paper(pmid, title, abstract, year))
                entity_id = upsert_entity(f"entity-{pmid}", entity_type)
                insert_relation(
                    "Paper", paper_id, relation, entity_type, entity_id,
                    source_pmid=pmid, evidence_section="discussion",
                    evidence_quote=quote, extraction_granularity="fulltext",
                )
            first = tool_literature_evidence_search(
                "breast segmentation external validation", focus="breast",
                top_k=3, cutoff_year=2024,
            )
            first_ids = [r["source_pmid"] for r in first["source_records"]]
            check("retrieval", "focus_precision_at_3", first_ids == ["21001"], first_ids, ["21001"])
            check("retrieval", "cutoff_excludes_future_counterexample", "21002" not in first_ids, first_ids, "exclude 21002")
            check("retrieval", "focus_excludes_other_disease", "21003" not in first_ids, first_ids, "exclude 21003")
            check("retrieval", "source_records_are_individually_attributable",
                  all(r.get("source_pmid") and r.get("evidence_quote") for r in first["source_records"]),
                  len(first["source_records"]), "all")
            check("retrieval", "cutoff_is_returned",
                  first["retrieval_metadata"]["cutoff_year"] == 2024,
                  first["retrieval_metadata"]["cutoff_year"], 2024)
            check("retrieval", "absence_scope_is_bounded",
                  first["retrieval_metadata"]["absence_scope"] == "in_corpus_only",
                  first["retrieval_metadata"]["absence_scope"], "in_corpus_only")
            second = tool_literature_evidence_search(
                "CLAM breast cancer classification", focus="breast", top_k=3, cutoff_year=2024,
            )
            second_ids = [r["source_pmid"] for r in second["source_records"]]
            expected = {"21001", "21004"}
            retrieved = set(first_ids + second_ids)
            recall = len(expected & retrieved) / len(expected)
            precision = len(expected & retrieved) / max(len(retrieved), 1)
            check("retrieval", "two_query_recall", recall == 1.0, recall, 1.0)
            check("retrieval", "two_query_precision", precision == 1.0, precision, 1.0)
            counter = next((r for r in second["source_records"] if r["source_pmid"] == "21004"), {})
            check("retrieval", "completed_work_is_counterevidence_channel",
                  counter.get("evidence_role") == "completed_work_counterevidence",
                  counter.get("evidence_role"), "completed_work_counterevidence")
        finally:
            config.DB_PATH = old_db

    good_review = {
        "verified_gaps": [{"candidate_id": "G01"}],
        "false_gaps": [{"candidate_id": "G02"}],
        "weak_evidence_gaps": [{"candidate_id": "G03"}],
    }
    good = validate_moderator_handoff(
        "### Research gap 1: Valid\n**Candidate ID**: G01\n", good_review
    )
    check("handoff", "verified_candidate_passes", good["status"] == "handoff_checked", good["status"], "handoff_checked")
    bad = validate_moderator_handoff(
        "### Research gap 1: Invalid\n**Candidate ID**: G02\n", good_review
    )
    check("handoff", "false_candidate_cannot_be_repromoted",
          "promoted_unverified_candidate:G02" in bad["issues"], bad["issues"], "issue")
    missing = validate_moderator_handoff("### Research gap 1: Missing\nNo id\n", good_review)
    check("handoff", "candidate_id_is_required", bool(missing["issues"]), missing["issues"], "issue")
    duplicate = validate_moderator_handoff(
        "### Research gap 1: A\n**Candidate ID**: G01\n### Research gap 2: B\n**Candidate ID**: G01\n",
        good_review,
    )
    check("handoff", "duplicate_promotion_is_blocked",
          "duplicate_promoted_candidate:G01" in duplicate["issues"], duplicate["issues"], "issue")
    check("handoff", "omitted_verified_ids_are_visible", "G01" in missing["omitted_verified_candidate_ids"],
          missing["omitted_verified_candidate_ids"], ["G01"])
    mixed_report = (
        "### Research gap 1: Keep\n**Candidate ID**: G01\n"
        "### Research gap 2: Remove\n**Candidate ID**: G02\n"
    )
    filtered, enforcement = enforce_moderator_handoff(mixed_report, good_review)
    check("handoff", "runtime_removes_unverified_gap_section",
          "**Candidate ID**: G01" in filtered and "**Candidate ID**: G02" not in filtered and enforcement["removed_candidate_ids"] == ["G02"],
          enforcement, {"removed_candidate_ids": ["G02"]})

    _, skeptic_schemas = build_role_tool_bundle("skeptic")
    skeptic_names = [s["function"]["name"] for s in skeptic_schemas]
    check("agent_contract", "skeptic_has_attributable_search", "literature_evidence_search" in skeptic_names,
          skeptic_names, "contains literature_evidence_search")
    check("agent_contract", "skeptic_prompt_bounds_empty_search",
          "in-corpus absence" in SKEPTIC_SYSTEM_PROMPT, "in-corpus absence" in SKEPTIC_SYSTEM_PROMPT, True)
    check("agent_contract", "moderator_prompt_requires_candidate_id",
          "**Candidate ID**" in MODERATOR_SYSTEM_PROMPT, "**Candidate ID**" in MODERATOR_SYSTEM_PROMPT, True)

    groups = {}
    for group in sorted({c["group"] for c in checks}):
        subset = [c for c in checks if c["group"] == group]
        groups[group] = {"passed": sum(c["passed"] for c in subset), "total": len(subset)}
    return {
        "suite": "p1_non_expert_quality",
        "label_tier": "synthetic_silver_development",
        "expert_research_direction_quality": "excluded_by_request",
        "network_calls": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "passed": sum(c["passed"] for c in checks),
            "total": len(checks),
            "groups": groups,
        },
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
