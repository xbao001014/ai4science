"""Coverage-oriented manual review queue for Method-family expansion."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from analysis.method_family_rules import _load_frozen_rules, match_strict_rule
from analysis.method_taxonomy import FAMILIES
from db.schema import get_conn


QUEUE_VERSION = "method-family-coverage-queue-v1"
EXTENSION_NORMALIZATION_POLICY = "explicit_unknown_or_reject_prefix_v1"
QUEUE_FIELDS = (
    "queue_rank",
    "method_entity_id",
    "method_name",
    "method_role",
    "paper_count",
    "uncovered_paper_gain",
    "cumulative_covered_papers",
    "projected_paper_coverage_if_labeled",
    "suggested_primary",
    "top1_similarity",
    "ranking_score",
    "margin",
    "suggested_top3",
    "policy_rejection_reason",
    "gold_primary",
    "gold_secondary",
    "review_notes",
)


class CoverageGoldValidationError(ValueError):
    """Raised when an annotated coverage queue cannot be imported safely."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        preview = "; ".join(errors[:8])
        if len(errors) > 8:
            preview += f"; ... ({len(errors) - 8} more)"
        super().__init__(preview)


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_csv(rows: list[dict[str, Any]], output_path: str | Path) -> None:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(report: dict[str, Any], output_path: str | Path | None) -> None:
    if not output_path:
        return
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def build_coverage_review_queue(
    gold_set_id: str,
    calibration_id: str,
    ruleset_id: str,
    *,
    output_path: str | Path,
    report_output_path: str | Path | None = None,
    target_paper_coverage: float = 0.80,
    max_rows: int = 2000,
) -> dict[str, Any]:
    """Export a deterministic greedy queue that maximizes marginal PMID coverage.

    The projected coverage is an upper bound: it assumes every selected method
    receives a usable primary label. The queue is intended for manual coverage
    expansion, not as a statistically independent model-evaluation holdout.
    """
    if not 0 < float(target_paper_coverage) <= 1:
        raise ValueError("target_paper_coverage must be in (0, 1]")
    if int(max_rows) <= 0:
        raise ValueError("max_rows must be positive")

    with get_conn() as conn:
        gold = conn.execute(
            "SELECT * FROM method_family_gold_sets WHERE gold_set_id=?", (gold_set_id,)
        ).fetchone()
        calibration = conn.execute(
            "SELECT * FROM method_family_calibrations WHERE calibration_id=?",
            (calibration_id,),
        ).fetchone()
        ruleset = conn.execute(
            "SELECT * FROM method_family_rulesets WHERE ruleset_id=?", (ruleset_id,)
        ).fetchone()
        if not gold:
            raise ValueError(f"Unknown Gold set: {gold_set_id}")
        if not calibration or str(calibration["gold_set_id"]) != gold_set_id:
            raise ValueError("Calibration is missing or belongs to a different Gold set")
        if not ruleset or str(ruleset["gold_set_id"]) != gold_set_id:
            raise ValueError("Ruleset is missing or belongs to a different Gold set")
        if str(calibration["status"]) != "threshold_validated":
            raise ValueError("Calibration has not passed its threshold gate")
        if str(ruleset["status"]) != "rules_validated":
            raise ValueError("Ruleset has not passed its validation gate")

        gold_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT method_entity_id, normalized_primary
                   FROM method_family_gold_labels WHERE gold_set_id=?""",
                (gold_set_id,),
            ).fetchall()
        ]
        entities = [
            dict(row)
            for row in conn.execute(
                """SELECT e.id, e.name, COALESCE(e.method_role, 'unknown') AS method_role
                   FROM entities e WHERE e.type='Method' AND EXISTS (
                       SELECT 1 FROM relations r WHERE r.object_id=e.id
                         AND r.object_type='Method' AND r.relation='APPLIES_METHOD'
                         AND COALESCE(r.status, 'active')='active'
                   ) ORDER BY e.id"""
            ).fetchall()
        ]
        relations = [
            dict(row)
            for row in conn.execute(
                """SELECT id, object_id, COALESCE(source_pmid, '') AS source_pmid
                   FROM relations WHERE relation='APPLIES_METHOD'
                     AND object_type='Method' AND COALESCE(status, 'active')='active'
                   ORDER BY object_id, source_pmid, id"""
            ).fetchall()
        ]
        embedding_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT method_entity_id, family_id, candidate_rank, confidence,
                          similarity, margin
                   FROM method_family_assignments
                   WHERE taxonomy_version=? AND status='review'
                   ORDER BY method_entity_id, candidate_rank, family_id""",
                (str(gold["taxonomy_version"]),),
            ).fetchall()
        ]

    graph_snapshot_sha256 = _json_hash(
        [(int(row["object_id"]), str(row["source_pmid"])) for row in relations]
    )
    thresholds = json.loads(str(calibration["thresholds_json"]))
    embedding_allowlist = set(json.loads(str(calibration["embedding_family_allowlist_json"])))
    frozen_rules, eligible_rule_ids = _load_frozen_rules(ruleset)
    gold_by_id = {
        int(row["method_entity_id"]): str(row["normalized_primary"]) for row in gold_rows
    }
    embedding_by_id: dict[int, list[dict[str, Any]]] = {}
    for row in embedding_rows:
        embedding_by_id.setdefault(int(row["method_entity_id"]), []).append(row)
    pmids_by_method: dict[int, set[str]] = {}
    all_pmids: set[str] = set()
    for row in relations:
        pmid = str(row["source_pmid"])
        if not pmid:
            continue
        method_id = int(row["object_id"])
        pmids_by_method.setdefault(method_id, set()).add(pmid)
        all_pmids.add(pmid)

    assigned_ids: set[int] = set()
    excluded_gold_unknown: set[int] = set()
    rejection_reason: dict[int, str] = {}
    for entity in entities:
        method_id = int(entity["id"])
        if method_id in gold_by_id:
            if gold_by_id[method_id] == "unknown":
                excluded_gold_unknown.add(method_id)
                rejection_reason[method_id] = "gold_unknown"
            else:
                assigned_ids.add(method_id)
            continue
        eligible_match = match_strict_rule(
            str(entity["name"]),
            rules=frozen_rules,
            eligible_rule_ids=eligible_rule_ids,
        )
        if eligible_match is not None:
            assigned_ids.add(method_id)
            continue
        all_rule_match = match_strict_rule(str(entity["name"]), rules=frozen_rules)
        top = next(
            (row for row in embedding_by_id.get(method_id, ()) if int(row["candidate_rank"]) == 1),
            None,
        )
        if all_rule_match is not None and all_rule_match.rule_id not in eligible_rule_ids:
            rejection_reason[method_id] = "strict_rule_unapproved"
        elif top is None:
            rejection_reason[method_id] = "no_embedding_candidate"
        elif str(top["family_id"]) not in embedding_allowlist:
            rejection_reason[method_id] = "embedding_family_not_allowed"
        elif float(top["confidence"]) < float(thresholds["ranking_score_min"]):
            rejection_reason[method_id] = "embedding_score_below_threshold"
        elif float(top["margin"] or 0.0) < float(thresholds["margin_min"]):
            rejection_reason[method_id] = "embedding_margin_below_threshold"
        else:
            assigned_ids.add(method_id)

    covered_pmids = set().union(*(pmids_by_method.get(method_id, set()) for method_id in assigned_ids))
    base_covered_count = len(covered_pmids)
    required_covered_count = math.ceil(len(all_pmids) * float(target_paper_coverage))
    entity_by_id = {int(row["id"]): row for row in entities}
    candidates = {
        method_id: pmids
        for method_id, pmids in pmids_by_method.items()
        if method_id not in assigned_ids and method_id not in excluded_gold_unknown and pmids
    }

    selected_rows: list[dict[str, Any]] = []
    while (
        len(covered_pmids) < required_covered_count
        and candidates
        and len(selected_rows) < int(max_rows)
    ):
        best_method_id = max(
            candidates,
            key=lambda method_id: (
                len(candidates[method_id] - covered_pmids),
                len(candidates[method_id]),
                -method_id,
            ),
        )
        method_pmids = candidates.pop(best_method_id)
        marginal = len(method_pmids - covered_pmids)
        if marginal <= 0:
            break
        covered_pmids.update(method_pmids)
        entity = entity_by_id[best_method_id]
        ranked = sorted(
            embedding_by_id.get(best_method_id, ()),
            key=lambda row: (int(row["candidate_rank"]), str(row["family_id"])),
        )
        top = ranked[0] if ranked else None
        selected_rows.append(
            {
                "queue_rank": len(selected_rows) + 1,
                "method_entity_id": best_method_id,
                "method_name": str(entity["name"]),
                "method_role": str(entity["method_role"]),
                "paper_count": len(method_pmids),
                "uncovered_paper_gain": marginal,
                "cumulative_covered_papers": len(covered_pmids),
                "projected_paper_coverage_if_labeled": round(
                    len(covered_pmids) / len(all_pmids), 6
                )
                if all_pmids
                else 0.0,
                "suggested_primary": str(top["family_id"]) if top else "",
                "top1_similarity": round(float(top["similarity"]), 6) if top else "",
                "ranking_score": round(float(top["confidence"]), 6) if top else "",
                "margin": round(float(top["margin"] or 0.0), 6) if top else "",
                "suggested_top3": "|".join(str(row["family_id"]) for row in ranked[:3]),
                "policy_rejection_reason": rejection_reason.get(
                    best_method_id, "not_assigned"
                ),
                "gold_primary": "",
                "gold_secondary": "",
                "review_notes": "",
            }
        )

    queue_sha256 = _json_hash(selected_rows)
    queue_id = "queue-" + _json_hash(
        {
            "version": QUEUE_VERSION,
            "gold_set_id": gold_set_id,
            "calibration_id": calibration_id,
            "ruleset_id": ruleset_id,
            "graph_snapshot_sha256": graph_snapshot_sha256,
            "target_paper_coverage": target_paper_coverage,
            "max_rows": max_rows,
            "queue_sha256": queue_sha256,
        }
    )[:24]
    final_projected_coverage = len(covered_pmids) / len(all_pmids) if all_pmids else 0.0
    target_reached = len(covered_pmids) >= required_covered_count
    report = {
        "queue_id": queue_id,
        "queue_version": QUEUE_VERSION,
        "queue_sha256": queue_sha256,
        "gold_set_id": gold_set_id,
        "calibration_id": calibration_id,
        "ruleset_id": ruleset_id,
        "graph_snapshot_sha256": graph_snapshot_sha256,
        "status": "target_reached" if target_reached else "target_not_reached",
        "idempotent": False,
        "review_purpose": "manual_coverage_expansion_not_model_holdout",
        "projection_assumption": "every selected row receives a usable primary label",
        "counts": {
            "active_method_papers": len(all_pmids),
            "base_covered_papers": base_covered_count,
            "additional_projected_papers": len(covered_pmids) - base_covered_count,
            "selected_rows": len(selected_rows),
            "excluded_existing_gold_unknown": len(excluded_gold_unknown),
            "remaining_unassigned_candidates": len(candidates),
        },
        "coverage": {
            "base": round(base_covered_count / len(all_pmids), 6) if all_pmids else 0.0,
            "target": float(target_paper_coverage),
            "projected_if_all_labeled": round(final_projected_coverage, 6),
        },
    }
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT selection_json, metrics_json FROM method_family_review_queues WHERE queue_id=?",
            (queue_id,),
        ).fetchone()
        if existing:
            selected_rows = json.loads(str(existing["selection_json"]))
            report = json.loads(str(existing["metrics_json"]))
            report["idempotent"] = True
        else:
            conn.execute(
                """INSERT INTO method_family_review_queues
                   (queue_id, gold_set_id, calibration_id, ruleset_id,
                    graph_snapshot_sha256, target_paper_coverage, queue_sha256,
                    selection_json, metrics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    queue_id,
                    gold_set_id,
                    calibration_id,
                    ruleset_id,
                    graph_snapshot_sha256,
                    float(target_paper_coverage),
                    queue_sha256,
                    json.dumps(selected_rows, ensure_ascii=False, sort_keys=True),
                    json.dumps(report, ensure_ascii=False, sort_keys=True),
                ),
            )
    _write_csv(selected_rows, output_path)
    _write_json(report, report_output_path)
    return report


def _parse_queue_csv(path: str | Path) -> tuple[Path, bytes, list[dict[str, str]]]:
    target = Path(path)
    raw = target.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CoverageGoldValidationError([f"CSV must be UTF-8/UTF-8-BOM: {exc}"]) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = tuple(reader.fieldnames or ())
    missing = [field for field in QUEUE_FIELDS if field not in headers]
    if missing:
        raise CoverageGoldValidationError([f"Missing required columns: {', '.join(missing)}"])
    return target, raw, list(reader)


def _validate_immutable_queue_columns(
    csv_rows: list[dict[str, str]], stored_rows: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    if len(csv_rows) != len(stored_rows):
        return [f"Queue row count changed: expected {len(stored_rows)}, got {len(csv_rows)}"]
    integer_fields = {
        "queue_rank",
        "method_entity_id",
        "paper_count",
        "uncovered_paper_gain",
        "cumulative_covered_papers",
    }
    float_fields = {
        "projected_paper_coverage_if_labeled",
        "top1_similarity",
        "ranking_score",
        "margin",
    }
    annotation_fields = {"gold_primary", "gold_secondary", "review_notes"}
    for index, (actual, expected) in enumerate(zip(csv_rows, stored_rows), start=1):
        for field in QUEUE_FIELDS:
            if field in annotation_fields:
                continue
            raw_actual = str(actual.get(field, "")).strip()
            raw_expected = expected.get(field, "")
            try:
                if field in integer_fields:
                    same = int(raw_actual) == int(raw_expected)
                elif field in float_fields:
                    if raw_actual == "" and raw_expected == "":
                        same = True
                    else:
                        same = abs(float(raw_actual) - float(raw_expected)) <= 1e-9
                else:
                    same = raw_actual == str(raw_expected).strip()
            except (TypeError, ValueError):
                same = False
            if not same:
                errors.append(f"row {index + 1}: immutable field {field} changed")
                break
    return errors


def _normalize_extension_labels(
    rows: list[dict[str, str]], *, rank_start: int, rank_end: int
) -> tuple[list[dict[str, Any]], list[str]]:
    valid_families = {family.family_id for family in FAMILIES}
    valid_primary = valid_families | {"unknown"}
    errors: list[str] = []
    labels: list[dict[str, Any]] = []
    by_rank: dict[int, dict[str, str]] = {}
    for row_index, row in enumerate(rows, start=2):
        try:
            rank = int(str(row.get("queue_rank", "")).strip())
        except ValueError:
            errors.append(f"row {row_index}: queue_rank must be an integer")
            continue
        by_rank[rank] = row
    for rank in range(rank_start, rank_end + 1):
        row = by_rank.get(rank)
        if row is None:
            errors.append(f"missing queue_rank {rank}")
            continue
        raw_primary = str(row.get("gold_primary", "")).strip()
        notes = str(row.get("review_notes", "")).strip()
        if raw_primary:
            normalized_primary = raw_primary
        elif notes.casefold().startswith("[reject]"):
            normalized_primary = "unknown"
        else:
            errors.append(
                f"queue_rank {rank}: blank gold_primary requires a [reject] review note"
            )
            continue
        if normalized_primary not in valid_primary:
            errors.append(
                f"queue_rank {rank}: invalid gold_primary {normalized_primary!r}"
            )
            continue
        secondary = tuple(
            part.strip()
            for part in str(row.get("gold_secondary", "")).split("|")
            if part.strip()
        )
        invalid_secondary = set(secondary) - valid_families
        if invalid_secondary:
            errors.append(
                f"queue_rank {rank}: invalid secondary labels {sorted(invalid_secondary)}"
            )
        if len(secondary) != len(set(secondary)):
            errors.append(f"queue_rank {rank}: duplicate secondary label")
        if normalized_primary in secondary:
            errors.append(f"queue_rank {rank}: primary repeated in secondary")
        if normalized_primary == "unknown" and secondary:
            errors.append(f"queue_rank {rank}: unknown primary cannot have secondary labels")
        try:
            method_entity_id = int(str(row["method_entity_id"]).strip())
            paper_count = int(str(row["paper_count"]).strip())
            uncovered_gain = int(str(row["uncovered_paper_gain"]).strip())
        except (KeyError, ValueError):
            errors.append(f"queue_rank {rank}: invalid integer snapshot")
            continue
        labels.append(
            {
                "queue_rank": rank,
                "method_entity_id": method_entity_id,
                "method_name": str(row.get("method_name", "")).strip(),
                "raw_primary": raw_primary,
                "normalized_primary": normalized_primary,
                "secondary": secondary,
                "review_notes": notes,
                "paper_count": paper_count,
                "uncovered_gain": uncovered_gain,
            }
        )
    return labels, errors


def _base_policy_assigned_ids(
    *,
    calibration: Any,
    ruleset: Any,
    entities: list[dict[str, Any]],
    embedding_rows: list[dict[str, Any]],
    original_gold: dict[int, str],
) -> set[int]:
    thresholds = json.loads(str(calibration["thresholds_json"]))
    embedding_allowlist = set(
        json.loads(str(calibration["embedding_family_allowlist_json"]))
    )
    frozen_rules, eligible_rule_ids = _load_frozen_rules(ruleset)
    embedding_by_id = {
        int(row["method_entity_id"]): row for row in embedding_rows
    }
    assigned: set[int] = set()
    for entity in entities:
        method_id = int(entity["id"])
        if method_id in original_gold:
            if original_gold[method_id] != "unknown":
                assigned.add(method_id)
            continue
        rule_match = match_strict_rule(
            str(entity["name"]),
            rules=frozen_rules,
            eligible_rule_ids=eligible_rule_ids,
        )
        if rule_match is not None:
            assigned.add(method_id)
            continue
        embedding = embedding_by_id.get(method_id)
        if (
            embedding is not None
            and str(embedding["family_id"]) in embedding_allowlist
            and float(embedding["confidence"]) >= float(thresholds["ranking_score_min"])
            and float(embedding["margin"] or 0.0) >= float(thresholds["margin_min"])
        ):
            assigned.add(method_id)
    return assigned


def _model_policy_assigned_ids(
    model_id: str, *, entities: list[dict[str, Any]]
) -> set[int]:
    """Recreate the immutable assignment baseline of a model-backed queue."""
    from analysis.method_family_supervised import (
        _load_model,
        _payload_training_labels,
        _predict_one,
        _vectors_for_ids,
    )

    model, ruleset, payload, weights, label_ids = _load_model(model_id)
    training = _payload_training_labels(model, payload)
    vectors = _vectors_for_ids(int(entity["id"]) for entity in entities)
    assigned = {
        method_id for method_id, label in training.items() if label != "unknown"
    }
    for entity in entities:
        method_id = int(entity["id"])
        if method_id in training or method_id not in vectors:
            continue
        prediction = _predict_one(
            name=str(entity["name"]),
            vector=vectors[method_id],
            model=model,
            ruleset=ruleset,
            weights=weights,
            label_ids=label_ids,
            lexicon=payload.get("lexicon", {}),
            family_thresholds=payload.get("family_thresholds", {}),
            fixed_source_allowlist=payload.get("fixed_source_allowlist"),
        )
        if prediction["accepted"]:
            assigned.add(method_id)
    return assigned


def import_coverage_gold_extension(
    path: str | Path,
    *,
    queue_id: str,
    reviewer: str,
    rank_start: int = 1,
    rank_end: int = 200,
    expected_sha256: str | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate and immutably import one annotated range from a review queue."""
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    if rank_start < 1 or rank_end < rank_start:
        raise ValueError("rank range is invalid")
    target, raw, csv_rows = _parse_queue_csv(path)
    file_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and file_sha256 != expected_sha256.strip().lower():
        raise CoverageGoldValidationError(
            [
                "SHA-256 mismatch: expected "
                f"{expected_sha256.strip().lower()}, got {file_sha256}"
            ]
        )
    with get_conn() as conn:
        queue = conn.execute(
            "SELECT * FROM method_family_review_queues WHERE queue_id=?", (queue_id,)
        ).fetchone()
        if not queue:
            raise ValueError(f"Unknown review queue: {queue_id}")
        stored_rows = json.loads(str(queue["selection_json"]))
        calibration = conn.execute(
            "SELECT * FROM method_family_calibrations WHERE calibration_id=?",
            (str(queue["calibration_id"]),),
        ).fetchone()
        ruleset = conn.execute(
            "SELECT * FROM method_family_rulesets WHERE ruleset_id=?",
            (str(queue["ruleset_id"]),),
        ).fetchone()
    errors = _validate_immutable_queue_columns(csv_rows, stored_rows)
    labels, label_errors = _normalize_extension_labels(
        csv_rows, rank_start=rank_start, rank_end=rank_end
    )
    errors.extend(label_errors)
    if errors:
        raise CoverageGoldValidationError(errors)

    label_snapshot = [
        {
            "queue_rank": label["queue_rank"],
            "method_entity_id": label["method_entity_id"],
            "raw_primary": label["raw_primary"],
            "normalized_primary": label["normalized_primary"],
            "secondary": label["secondary"],
            "review_notes": label["review_notes"],
        }
        for label in labels
    ]
    label_snapshot_sha256 = _json_hash(label_snapshot)
    extension_id = "goldext-" + _json_hash(
        {
            "queue_id": queue_id,
            "rank_start": rank_start,
            "rank_end": rank_end,
            "label_snapshot_sha256": label_snapshot_sha256,
        }
    )[:24]
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT metrics_json FROM method_family_gold_extensions WHERE extension_id=?",
            (extension_id,),
        ).fetchone()
        if existing:
            report = json.loads(str(existing["metrics_json"]))
            report["idempotent"] = True
            _write_json(report, output_path)
            return report
        overlaps = conn.execute(
            """SELECT queue_rank FROM method_family_gold_extension_labels
               WHERE queue_id=? AND queue_rank BETWEEN ? AND ? ORDER BY queue_rank""",
            (queue_id, rank_start, rank_end),
        ).fetchall()
        if overlaps:
            raise CoverageGoldValidationError(
                [
                    "Queue ranks already imported by another immutable extension: "
                    f"{[int(row['queue_rank']) for row in overlaps[:10]]}"
                ]
            )
        original_gold = {
            int(row["method_entity_id"]): str(row["normalized_primary"])
            for row in conn.execute(
                """SELECT method_entity_id, normalized_primary
                   FROM method_family_gold_labels WHERE gold_set_id=?""",
                (str(queue["gold_set_id"]),),
            ).fetchall()
        }
        entities = [
            dict(row)
            for row in conn.execute(
                """SELECT e.id, e.name FROM entities e
                   WHERE e.type='Method' AND EXISTS (
                       SELECT 1 FROM relations r WHERE r.object_id=e.id
                         AND r.object_type='Method' AND r.relation='APPLIES_METHOD'
                         AND COALESCE(r.status, 'active')='active')"""
            ).fetchall()
        ]
        relations = [
            dict(row)
            for row in conn.execute(
                """SELECT object_id, COALESCE(source_pmid, '') AS source_pmid
                   FROM relations WHERE relation='APPLIES_METHOD'
                     AND object_type='Method' AND COALESCE(status, 'active')='active'"""
            ).fetchall()
        ]
        embedding_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT method_entity_id, family_id, confidence, margin
                   FROM method_family_assignments
                   WHERE taxonomy_version=? AND candidate_rank=1
                     AND is_primary=1 AND status='review'""",
                (str(calibration["taxonomy_version"]),),
            ).fetchall()
        ]
        previous_extension_ids = {
            int(row["method_entity_id"])
            for row in conn.execute(
                """SELECT method_entity_id FROM method_family_gold_extension_labels
                   WHERE queue_id=? AND normalized_primary!='unknown'""",
                (queue_id,),
            ).fetchall()
        }

    queue_metrics = json.loads(str(queue["metrics_json"]))
    base_model_id = str(queue_metrics.get("base_model_id") or "").strip()
    if base_model_id:
        base_ids = _model_policy_assigned_ids(base_model_id, entities=entities)
    else:
        base_ids = _base_policy_assigned_ids(
            calibration=calibration,
            ruleset=ruleset,
            entities=entities,
            embedding_rows=embedding_rows,
            original_gold=original_gold,
        )
    pmids_by_method: dict[int, set[str]] = defaultdict(set)
    all_pmids: set[str] = set()
    for relation in relations:
        pmid = str(relation["source_pmid"])
        if pmid:
            pmids_by_method[int(relation["object_id"])].add(pmid)
            all_pmids.add(pmid)
    base_pmids = set().union(*(pmids_by_method[method_id] for method_id in base_ids))
    previous_pmids = base_pmids | set().union(
        *(pmids_by_method[method_id] for method_id in previous_extension_ids)
    )
    current_known_ids = {
        int(label["method_entity_id"])
        for label in labels
        if label["normalized_primary"] != "unknown"
    }
    cumulative_pmids = previous_pmids | set().union(
        *(pmids_by_method[method_id] for method_id in current_known_ids)
    )
    distribution = Counter(str(label["normalized_primary"]) for label in labels)
    report = {
        "extension_id": extension_id,
        "queue_id": queue_id,
        "base_model_id": base_model_id or None,
        "parent_gold_set_id": str(queue["gold_set_id"]),
        "source_filename": target.name,
        "file_sha256": file_sha256,
        "label_snapshot_sha256": label_snapshot_sha256,
        "normalization_policy": EXTENSION_NORMALIZATION_POLICY,
        "rank_range": {"start": rank_start, "end": rank_end},
        "idempotent": False,
        "status": "coverage_extension_imported",
        "release_build_eligible": False,
        "counts": {
            "rows": len(labels),
            "known": len(current_known_ids),
            "unknown": len(labels) - len(current_known_ids),
            "secondary_labels": sum(len(label["secondary"]) for label in labels),
        },
        "primary_distribution": dict(sorted(distribution.items())),
        "coverage": {
            "active_method_papers": len(all_pmids),
            "base_covered_papers": len(base_pmids),
            "covered_before_extension": len(previous_pmids),
            "covered_after_extension": len(cumulative_pmids),
            "incremental_new_papers": len(cumulative_pmids - previous_pmids),
            "base": round(len(base_pmids) / len(all_pmids), 6) if all_pmids else 0.0,
            "before_extension": round(len(previous_pmids) / len(all_pmids), 6)
            if all_pmids
            else 0.0,
            "after_extension": round(len(cumulative_pmids) / len(all_pmids), 6)
            if all_pmids
            else 0.0,
            "required": 0.80,
        },
        "safety": {
            "used_for_model_holdout": False,
            "accepted_assignments_written": 0,
            "active_release_created": False,
        },
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_gold_extensions
               (extension_id, queue_id, parent_gold_set_id, file_sha256,
                source_filename, label_snapshot_sha256, rank_start, rank_end,
                row_count, known_count, unknown_count, secondary_count,
                reviewer, normalization_policy, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                extension_id,
                queue_id,
                str(queue["gold_set_id"]),
                file_sha256,
                target.name,
                label_snapshot_sha256,
                rank_start,
                rank_end,
                len(labels),
                len(current_known_ids),
                len(labels) - len(current_known_ids),
                sum(len(label["secondary"]) for label in labels),
                reviewer,
                EXTENSION_NORMALIZATION_POLICY,
                json.dumps(report, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.executemany(
            """INSERT INTO method_family_gold_extension_labels
               (extension_id, queue_id, method_entity_id, queue_rank,
                method_name_snapshot, raw_primary, normalized_primary,
                secondary_json, review_notes, paper_count_snapshot,
                uncovered_gain_snapshot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    extension_id,
                    queue_id,
                    label["method_entity_id"],
                    label["queue_rank"],
                    label["method_name"],
                    label["raw_primary"],
                    label["normalized_primary"],
                    json.dumps(label["secondary"], ensure_ascii=False),
                    label["review_notes"],
                    label["paper_count"],
                    label["uncovered_gain"],
                )
                for label in labels
            ],
        )
    _write_json(report, output_path)
    return report
