"""Deterministic P0 contract evaluation; no model or production DB calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "evals")]

from extractor.evidence_support import assess_evidence_support
from extractor.section_extractor import _recall_check_reason
from extractor.triple_models import Triple
from p0_cases import EMPTY_ROUTING, EVIDENCE_SUPPORT


def score(rows: list[dict], key: str) -> dict:
    labels = ("supported", "mentioned_only", "contradicted", "unclear")
    confusion = {truth: {pred: 0 for pred in labels} for truth in labels}
    for row in rows:
        confusion[row["expected"]][row[key]] += 1
    correct = sum(row[key] == row["expected"] for row in rows)
    false_supported = sum(row[key] == "supported" and row["expected"] != "supported" for row in rows)
    return {
        "accuracy": correct / len(rows),
        "correct": correct,
        "total": len(rows),
        "false_supported": false_supported,
        "confusion": confusion,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a fresh output directory")
    args.output.mkdir(parents=True)
    support_rows = []
    for case in EVIDENCE_SUPPORT:
        triple = Triple.model_validate(case["triple"])
        candidate, reason = assess_evidence_support(triple, case["quote"])
        support_rows.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "baseline": "supported",  # phase 2 locator treated every located quote alike
                "candidate": candidate,
                "reason": reason,
            }
        )
    routing_rows = []
    for case in EMPTY_ROUTING:
        row = {"id": case["id"]}
        for policy in ("phase2", "p0"):
            row[policy] = _recall_check_reason(case["study_type"], case["text"], policy=policy)
            row[f"{policy}_correct"] = row[policy] == case[policy]
        routing_rows.append(row)
    result = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "label_tier": "silver_agent_authored_visible_development_contract",
        "cases_sha256": hashlib.sha256((ROOT / "evals/p0_cases.py").read_bytes()).hexdigest(),
        "support_rows": support_rows,
        "evidence_support": {
            "baseline": score(support_rows, "baseline"),
            "candidate": score(support_rows, "candidate"),
        },
        "empty_routing": {
            "rows": routing_rows,
            "phase2_correct": sum(row["phase2_correct"] for row in routing_rows),
            "p0_correct": sum(row["p0_correct"] for row in routing_rows),
            "total": len(routing_rows),
            "candidate_reasons": dict(Counter(row["p0"] or "no_recheck" for row in routing_rows)),
        },
    }
    (args.output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence_support": result["evidence_support"], "empty_routing": result["empty_routing"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
