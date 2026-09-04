"""Create, validate, and cryptographically seal independent expert holdouts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


STUDY_TYPES = (
    "ai_algorithm",
    "clinical_study",
    "foundation_model",
    "dataset_benchmark",
    "multimodal",
    "review",
    "meta_analysis",
    "other",
)
GAP_LABELS = ("supported", "refuted", "insufficient")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def init_package(output: Path, papers_per_type: int = 8, gaps_per_label: int = 8) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("holdout directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    papers = []
    for study_type in STUDY_TYPES:
        for index in range(1, papers_per_type + 1):
            papers.append(
                {
                    "slot_id": f"P-{study_type}-{index:02d}",
                    "unit": "paper",
                    "study_type": study_type,
                    "verified_paper_id": None,
                    "corpus_snapshot": None,
                    "input_path": None,
                    "is_synthetic": False,
                    "reviewer_a": {"reviewer_id": None, "triples": None, "forbidden_claims": None},
                    "reviewer_b": {"reviewer_id": None, "triples": None, "forbidden_claims": None},
                    "adjudication": {"reviewer_id": None, "status": "pending", "triples": None, "reasons": None},
                }
            )
    gaps = []
    for label in GAP_LABELS:
        for index in range(1, gaps_per_label + 1):
            gaps.append(
                {
                    "slot_id": f"G-{label}-{index:02d}",
                    "unit": "gap_evidence_pack",
                    "reference_stratum": label,
                    "candidate": None,
                    "scope": None,
                    "search_cutoff": None,
                    "corpus_snapshot": None,
                    "evidence_records": None,
                    "reviewer_a": {"reviewer_id": None, "label": None, "reasons": None},
                    "reviewer_b": {"reviewer_id": None, "label": None, "reasons": None},
                    "adjudication": {"reviewer_id": None, "status": "pending", "label": None, "reasons": None},
                }
            )
    _write_jsonl(output / "paper_annotations.jsonl", papers)
    _write_jsonl(output / "gap_annotations.jsonl", gaps)
    protocol = {
        "version": 1,
        "label_tier": "pending_expert_gold",
        "visibility": "sealed_holdout_candidate_do_not_use_for_prompt_tuning",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paper_slots": len(papers),
        "gap_slots": len(gaps),
        "requirements": [
            "two independent domain reviewers",
            "third reviewer adjudicates disagreements",
            "paper-level isolation; related versions remain together",
            "verified source identifiers and corpus snapshot",
            "no pending or synthetic row may be sealed as expert gold",
        ],
    }
    (output / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    return validate_package(output)


def validate_package(root: Path) -> dict:
    papers = _read_jsonl(root / "paper_annotations.jsonl")
    gaps = _read_jsonl(root / "gap_annotations.jsonl")
    issues: list[str] = []
    ids = [row.get("slot_id") for row in papers + gaps]
    if len(ids) != len(set(ids)):
        issues.append("duplicate_slot_id")
    for row in papers:
        if row.get("study_type") not in STUDY_TYPES:
            issues.append(f"{row.get('slot_id')}:invalid_study_type")
        if row.get("is_synthetic"):
            issues.append(f"{row.get('slot_id')}:synthetic_cannot_be_gold")
        if not row.get("verified_paper_id") or not row.get("corpus_snapshot") or not row.get("input_path"):
            issues.append(f"{row.get('slot_id')}:missing_source_metadata")
        a, b, adj = row.get("reviewer_a", {}), row.get("reviewer_b", {}), row.get("adjudication", {})
        if not a.get("reviewer_id") or not b.get("reviewer_id") or a.get("reviewer_id") == b.get("reviewer_id"):
            issues.append(f"{row.get('slot_id')}:independent_review_missing")
        if adj.get("status") != "adjudicated" or adj.get("triples") is None:
            issues.append(f"{row.get('slot_id')}:adjudication_pending")
    for row in gaps:
        if row.get("reference_stratum") not in GAP_LABELS:
            issues.append(f"{row.get('slot_id')}:invalid_reference_stratum")
        for field in ("candidate", "scope", "search_cutoff", "corpus_snapshot", "evidence_records"):
            if not row.get(field):
                issues.append(f"{row.get('slot_id')}:missing_{field}")
        a, b, adj = row.get("reviewer_a", {}), row.get("reviewer_b", {}), row.get("adjudication", {})
        if not a.get("reviewer_id") or not b.get("reviewer_id") or a.get("reviewer_id") == b.get("reviewer_id"):
            issues.append(f"{row.get('slot_id')}:independent_review_missing")
        if adj.get("status") != "adjudicated" or adj.get("label") not in GAP_LABELS:
            issues.append(f"{row.get('slot_id')}:adjudication_pending")
    return {
        "paper_rows": len(papers),
        "gap_rows": len(gaps),
        "ready_to_seal": not issues,
        "issue_count": len(issues),
        "issues": issues,
    }


def seal_package(root: Path, output: Path) -> dict:
    status = validate_package(root)
    if not status["ready_to_seal"]:
        raise ValueError(f"holdout is not sealable ({status['issue_count']} issues)")
    if output.exists():
        raise ValueError("seal output already exists")
    files = ("paper_annotations.jsonl", "gap_annotations.jsonl", "protocol.json")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    manifest = {
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "label_tier": "expert_adjudicated_gold",
        "content_sha256": hashes,
        "counts": {"papers": status["paper_rows"], "gap_evidence_packs": status["gap_rows"]},
    }
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--output", type=Path, required=True)
    init.add_argument("--papers-per-type", type=int, default=8)
    init.add_argument("--gaps-per-label", type=int, default=8)
    validate = sub.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--input", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        result = init_package(args.output, args.papers_per_type, args.gaps_per_label)
    elif args.command == "validate":
        result = validate_package(args.input)
    else:
        result = seal_package(args.input, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
