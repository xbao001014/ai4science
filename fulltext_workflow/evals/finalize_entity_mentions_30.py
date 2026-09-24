"""Finish annotation coverage and refresh the isolated 30-paper comparison."""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from db.schema import init_db  # noqa: E402
from evals.entity_context_30 import compare  # noqa: E402
from extractor.entity_mention_backfill import (  # noqa: E402
    backfill_paper_mentions, enrich_explicit_long_forms,
)


def finalize(eval_db: Path, pmid_file: Path, output: Path) -> dict:
    pmids = [line.strip() for line in pmid_file.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    if len(pmids) != 30 or len(set(pmids)) != 30:
        raise ValueError("Expected 30 unique PMIDs")
    config.DB_PATH = str(eval_db.resolve())
    init_db()
    summary_path = output / "annotation_summary.json"
    previous = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.exists() else {}
    )
    backfilled = sum(backfill_paper_mentions(pmid) for pmid in pmids)
    enriched = sum(enrich_explicit_long_forms(pmid) for pmid in pmids)
    # The running pilot may have started before the stricter name-grounding
    # check was loaded. Apply the same deterministic guard to saved qualifiers.
    discarded_qualifiers = 0
    with sqlite3.connect(eval_db) as conn:
        marks = ",".join("?" for _ in pmids)
        for mention_id, surface, raw_json in conn.execute(
            "SELECT id,surface_name,qualifiers_json FROM entity_mentions "
            f"WHERE entity_type='Disease' AND qualifiers_json<>'[]' AND source_pmid IN ({marks})",
            pmids,
        ).fetchall():
            qualifiers = json.loads(raw_json or "[]")
            kept = [
                q for q in qualifiers
                if q.get("phrase")
                and str(q["phrase"]).casefold() in str(surface or "").casefold()
                and str(q["phrase"]).casefold() != str(surface or "").casefold()
            ]
            discarded_qualifiers += len(qualifiers) - len(kept)
            if len(kept) != len(qualifiers):
                conn.execute(
                    "UPDATE entity_mentions SET qualifiers_json=? WHERE id=?",
                    (json.dumps(kept, ensure_ascii=False), mention_id),
                )
    compare(output / "before.json", eval_db, output / "comparison")
    comparison_summary_path = output / "comparison" / "summary.json"
    comparison_summary = json.loads(comparison_summary_path.read_text(encoding="utf-8"))
    comparison_summary["quality_verdict"] = "descriptive_unlabelled"
    comparison_summary_path.write_text(
        json.dumps(comparison_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with sqlite3.connect(eval_db) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" for _ in pmids)
        rows = [dict(row) for row in conn.execute(
            f"""SELECT m.source_pmid, m.entity_type, m.surface_name,
                       e.name AS normalized_name, m.method_role_hint,
                       m.explicit_long_form,
                       m.definition_quote, m.qualifiers_json,
                       m.resolution_status, m.annotation_version,
                       re.evidence_quote, re.evidence_status, re.context_text
                FROM entity_mentions m
                JOIN relations r ON r.id=m.relation_id
                JOIN relation_evidence re ON re.id=m.relation_evidence_id
                LEFT JOIN entities e ON e.id=m.entity_id
                WHERE m.source_pmid IN ({marks})
                  AND COALESCE(r.status,'active')='active'
                ORDER BY m.source_pmid, m.entity_type, m.surface_name""",
            pmids,
        )]
        source_texts = {}
        for pmid in pmids:
            source_texts[pmid] = "\n".join(
                str(row[0] or "") for row in conn.execute(
                    """SELECT s.content FROM document_sections s
                       JOIN papers p ON p.id=s.paper_id
                       WHERE COALESCE(p.source_key,p.pmid)=?""", (pmid,)
                )
            )
    with (output / "mentions_after.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [
            "source_pmid", "entity_type", "surface_name", "normalized_name",
            "method_role_hint", "explicit_long_form", "definition_quote", "qualifiers_json",
            "resolution_status", "annotation_version", "evidence_quote",
            "evidence_status", "context_text",
        ])
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "papers": len(pmids), "mentions": len(rows),
        "backfilled": int(previous.get("backfilled") or 0) + backfilled,
        "explicit_long_forms_enriched": int(previous.get("explicit_long_forms_enriched") or 0) + enriched,
        "discarded_invalid_qualifiers": (
            int(previous.get("discarded_invalid_qualifiers") or 0)
            + int(previous.get("discarded_quote_only_qualifiers") or 0)
            + discarded_qualifiers
        ),
        "method_mentions": sum(r["entity_type"] == "Method" for r in rows),
        "method_explicit_long_forms": sum(
            r["entity_type"] == "Method" and bool(r["explicit_long_form"]) for r in rows
        ),
        "disease_mentions": sum(r["entity_type"] == "Disease" for r in rows),
        "disease_explicit_long_forms": sum(
            r["entity_type"] == "Disease" and bool(r["explicit_long_form"]) for r in rows
        ),
        "disease_with_qualifiers": sum(
            r["entity_type"] == "Disease" and r["qualifiers_json"] != "[]" for r in rows
        ),
        "located_evidence_mentions": sum(r["evidence_status"] == "located" for r in rows),
        "definition_quotes_locatable": sum(
            bool(r["explicit_long_form"]) and bool(r["definition_quote"])
            and r["definition_quote"] in source_texts[r["source_pmid"]] for r in rows
        ),
        "qualifier_phrases": sum(len(json.loads(r["qualifiers_json"])) for r in rows),
        "all_unresolved": all(r["resolution_status"] == "unresolved" for r in rows),
        "interpretation": "descriptive_unlabelled",
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-db", type=Path, required=True)
    parser.add_argument("--pmids", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(finalize(args.eval_db, args.pmids, args.output), ensure_ascii=False))
