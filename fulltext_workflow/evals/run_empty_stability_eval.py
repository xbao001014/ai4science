"""Interleaved live-model evaluation of the P0 bounded empty-output policy."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "evals")]

from quality_cases import EXTRACTION
from run_quality_eval import grade_extraction


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-requests", type=int, default=40)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a fresh output directory")
    args.output.mkdir(parents=True)

    import config
    import extractor.llm_client as lc
    from extractor.section_extractor import _extract_from_text

    config.LLM_RETRY_ATTEMPTS = 1
    config.LLM_TEMPERATURE = 0.1
    config.LLM_MAX_TOKENS = 2400
    lc.configure_concurrency(args.workers)
    case = next(row for row in EXTRACTION if row["id"] == "E03")
    usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "api_errors": 0}
    current = ContextVar("stability_record")
    lock = threading.Lock()
    original = lc._client.chat.completions.create

    def tracked(**kwargs):
        row = current.get()
        with lock:
            if usage["requests"] >= args.max_requests:
                raise RuntimeError("request_cap_reached")
            usage["requests"] += 1
            row["requests"] += 1
        trace = {"request": copy.deepcopy({k: v for k, v in kwargs.items() if k in ("model", "messages", "temperature", "max_tokens", "response_format")})}
        started = time.perf_counter()
        try:
            response = original(**kwargs)
        except Exception as exc:
            with lock:
                usage["api_errors"] += 1
            trace["error"] = type(exc).__name__
            row["trace"].append(trace)
            raise
        trace["duration_s"] = round(time.perf_counter() - started, 3)
        trace["response"] = response.model_dump(exclude_none=True)
        row["trace"].append(trace)
        if response.usage:
            with lock:
                for name in ("prompt_tokens", "completion_tokens"):
                    value = getattr(response.usage, name, 0) or 0
                    usage[name] += value
        return response

    def run_one(policy: str, trial: int) -> dict:
        row = {"policy": policy, "trial": trial, "error": None, "requests": 0, "trace": []}
        current.set(row)
        audit = {}
        try:
            triples = _extract_from_text(
                case["title"],
                case["section"],
                case["section"],
                case["text"],
                study_type=case["study_type"],
                audit=audit,
                recall_policy=policy,
            )
            row["output"] = [triple.model_dump() for triple in triples]
            row["grade"] = grade_extraction(case, row["output"])
        except Exception as exc:
            row["error"] = type(exc).__name__
            row["output"] = []
            row["grade"] = grade_extraction(case, [])
            row["grade"]["pass"] = False
        row["audit"] = audit
        (args.output / f"{policy}-{trial}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        return {k: v for k, v in row.items() if k not in ("trace", "output")}

    jobs = [(policy, trial) for policy in ("phase2", "p0") for trial in range(1, args.repeats + 1)]
    random.Random(20260904).shuffle(jobs)
    rows = []
    with patch.object(lc._client, "max_retries", 0), patch.object(lc._client.chat.completions, "create", tracked), ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, *job) for job in jobs]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(row["policy"], row["trial"], "pass" if row["grade"]["pass"] else "fail", row["audit"].get("outcome"), flush=True)

    def metrics(policy: str) -> dict:
        selected = [row for row in rows if row["policy"] == policy]
        gold = sum(row["grade"]["gold"] for row in selected)
        return {
            "passed": sum(row["grade"]["pass"] and not row["error"] for row in selected),
            "total": len(selected),
            "recall": sum(row["grade"]["tp"] for row in selected) / gold if gold else None,
            "initial_empty": sum(row["audit"].get("empty_recheck") or row["audit"].get("outcome") == "model_empty" for row in selected),
            "final_empty": sum(not row["grade"]["predicted"] for row in selected),
            "requests": sum(row["requests"] for row in selected),
            "errors": sum(bool(row["error"]) for row in selected),
        }

    rows.sort(key=lambda row: (row["policy"], row["trial"]))
    result = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "case": case["id"],
        "design": "randomized_interleaved_same_prompt_policy_comparison",
        "label_tier": "silver_visible_development_failure_replay",
        "model": config.LLM_MODEL_EXTRACT,
        "temperature": config.LLM_TEMPERATURE,
        "repeats_per_policy": args.repeats,
        "case_sha256": hashlib.sha256(json.dumps(case, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "rows": rows,
        "metrics": {"phase2": metrics("phase2"), "p0": metrics("p0")},
        "usage": usage,
    }
    (args.output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": result["metrics"], "usage": usage}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
