"""One live Scout -> Skeptic -> Moderator structural/provenance smoke test.

The score deliberately excludes novelty, feasibility and usefulness judgments.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gap_agent import stream_gap_debate_agent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--focus", default="breast cancer")
    parser.add_argument("--top-n", type=int, default=2)
    args = parser.parse_args()
    events = list(stream_gap_debate_agent(
        focus=args.focus,
        top_n=args.top_n,
        max_debate_rounds=1,
        use_ops_memory=False,
    ))
    phases = {e.get("role") for e in events if e.get("type") == "phase_start"}
    proposal = next((e.get("content", "") for e in events if e.get("type") == "optimist_proposal"), "")
    candidate_ids = sorted(set(re.findall(r"\bG\d{2,}\b", proposal)))
    reviewer = next((e for e in events if e.get("type") == "skeptic_review"), {})
    final = next((e for e in reversed(events) if e.get("type") == "final"), {})
    calls = [
        {"role": e.get("role"), "name": e.get("name"), "args": e.get("args")}
        for e in events if e.get("type") == "tool_call"
    ]
    checks = [
        {"name": "all_three_roles_ran", "passed": phases == {"optimist", "skeptic", "moderator"}, "observed": sorted(phases)},
        {"name": "scout_emitted_stable_candidate_ids", "passed": bool(candidate_ids), "observed": candidate_ids},
        {"name": "skeptic_review_was_structured", "passed": bool(reviewer.get("content")), "observed": reviewer.get("confidence")},
        {"name": "skeptic_called_attributable_search", "passed": any(c["role"] == "skeptic" and c["name"] == "literature_evidence_search" for c in calls), "observed": calls},
        {"name": "moderator_handoff_guard_passed", "passed": final.get("handoff_audit", {}).get("status") == "handoff_checked", "observed": final.get("handoff_audit")},
        {"name": "final_event_exists", "passed": bool(final), "observed": final.get("validation_status")},
        {"name": "no_runtime_error_events", "passed": not any(e.get("type") == "error" for e in events), "observed": [e for e in events if e.get("type") == "error"]},
    ]
    result = {
        "suite": "p1_live_chain_structural_smoke",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "focus": args.focus,
        "model_judgment_scope": "workflow_structure_and_provenance_only",
        "research_direction_quality": "not_scored",
        "requests": sum(e.get("type") == "llm_request_start" for e in events),
        "tool_calls": len(calls),
        "metrics": {"passed": sum(c["passed"] for c in checks), "total": len(checks)},
        "checks": checks,
        "events": events,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("suite", "requests", "tool_calls", "metrics")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
