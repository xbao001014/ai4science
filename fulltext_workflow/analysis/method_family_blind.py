"""Independent blind-set export and immutable label submission for Method family."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from analysis.embedding_inputs import load_method_embedding_inputs
from analysis.method_taxonomy import FAMILIES
from db.schema import get_conn


SAMPLING_VERSION = "method-family-blind-stratified-v1"
BLIND_FIELDS = (
    "blind_rank",
    "blind_item_id",
    "method_entity_id",
    "method_name",
    "method_role",
    "paper_count",
    "first_year",
    "last_year",
    "context_quality",
    "context_excerpt",
    "gold_primary",
    "gold_secondary",
    "review_notes",
)
SNAPSHOT_FIELDS = BLIND_FIELDS[:10]


class BlindValidationError(ValueError):
    """Raised when a blind submission is incomplete or changes frozen columns."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        preview = "; ".join(errors[:8])
        if len(errors) > 8:
            preview += f"; ... ({len(errors) - 8} more)"
        super().__init__(preview)


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _csv_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=BLIND_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + text.getvalue().encode("utf-8")


def _write_bytes(path: str | Path, raw: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return target.resolve()


def _frequency_band(paper_count: int) -> str:
    if paper_count >= 10:
        return "high"
    if paper_count >= 2:
        return "medium"
    return "singleton"


def _apportion(counts: dict[str, int], target: int) -> dict[str, int]:
    total = sum(counts.values())
    if target < 0 or target > total:
        raise ValueError("Invalid blind-set target")
    if not total:
        return {}
    ideals = {key: target * value / total for key, value in counts.items()}
    quotas = {key: min(value, int(ideals[key])) for key, value in counts.items()}
    while sum(quotas.values()) < target:
        candidates = [key for key, value in counts.items() if quotas[key] < value]
        key = max(candidates, key=lambda item: (ideals[item] - quotas[item], counts[item], item))
        quotas[key] += 1
    return quotas


def _stable_order(rows: Iterable[dict[str, Any]], seed: str) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: hashlib.sha256(
            f"{seed}|{row['method_entity_id']}|{row['method_name']}".encode("utf-8")
        ).hexdigest(),
    )


def _sample_stratified(
    rows: list[dict[str, Any]], *, size: int, seed: str
) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[str(row["hidden_suggested_primary"])].append(row)
    family_quotas = _apportion(
        {key: len(values) for key, values in by_family.items()}, size
    )
    selected: list[dict[str, Any]] = []
    for family, family_rows in sorted(by_family.items()):
        family_target = family_quotas.get(family, 0)
        by_substratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in family_rows:
            sub = f"{row['method_role']}|{_frequency_band(int(row['paper_count']))}"
            by_substratum[sub].append(row)
        sub_quotas = _apportion(
            {key: len(values) for key, values in by_substratum.items()}, family_target
        )
        for sub, sub_rows in sorted(by_substratum.items()):
            ordered = _stable_order(sub_rows, f"{seed}|{family}|{sub}")
            selected.extend(ordered[: sub_quotas.get(sub, 0)])
    if len(selected) != size:
        raise ValueError("Stratified sampling did not produce the requested size")
    return _stable_order(selected, f"{seed}|final")


def _load_training_snapshot(parent_gold_set_id: str) -> tuple[list[dict[str, Any]], set[int]]:
    with get_conn() as conn:
        rows = [
            {
                "origin": "gold",
                "origin_id": parent_gold_set_id,
                "method_entity_id": int(row["method_entity_id"]),
                "normalized_primary": str(row["normalized_primary"]),
            }
            for row in conn.execute(
                """SELECT method_entity_id, normalized_primary
                   FROM method_family_gold_labels WHERE gold_set_id=?
                   ORDER BY method_entity_id""",
                (parent_gold_set_id,),
            ).fetchall()
        ]
        rows.extend(
            {
                "origin": "extension",
                "origin_id": str(row["extension_id"]),
                "method_entity_id": int(row["method_entity_id"]),
                "normalized_primary": str(row["normalized_primary"]),
            }
            for row in conn.execute(
                """SELECT l.extension_id, l.method_entity_id, l.normalized_primary
                   FROM method_family_gold_extension_labels l
                   JOIN method_family_gold_extensions x ON x.extension_id=l.extension_id
                   WHERE x.parent_gold_set_id=?
                   ORDER BY l.extension_id, l.method_entity_id""",
                (parent_gold_set_id,),
            ).fetchall()
        )
    return rows, {int(row["method_entity_id"]) for row in rows}


def export_blind_set(
    parent_gold_set_id: str,
    *,
    output_path: str | Path,
    size: int = 200,
    generation: int = 1,
) -> dict[str, Any]:
    """Freeze and export a representative blind set without model suggestions."""
    if size < 50:
        raise ValueError("Blind set size must be at least 50")
    if generation < 1:
        raise ValueError("Blind set generation must be positive")
    sampling_version = (
        SAMPLING_VERSION if generation == 1 else f"{SAMPLING_VERSION}-g{generation}"
    )
    with get_conn() as conn:
        gold = conn.execute(
            "SELECT * FROM method_family_gold_sets WHERE gold_set_id=?",
            (parent_gold_set_id,),
        ).fetchone()
        if not gold:
            raise ValueError(f"Unknown Gold set: {parent_gold_set_id}")
        entity_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT e.id AS method_entity_id, e.name AS method_name,
                          COALESCE(e.method_role, 'unknown') AS method_role,
                          COUNT(DISTINCT NULLIF(r.source_pmid, '')) AS paper_count,
                          MIN(p.year) AS first_year, MAX(p.year) AS last_year
                   FROM entities e
                   JOIN relations r ON r.object_id=e.id
                    AND r.object_type='Method' AND r.relation='APPLIES_METHOD'
                    AND COALESCE(r.status, 'active')='active'
                   LEFT JOIN papers p ON COALESCE(p.source_key,p.pmid)=r.source_pmid
                   WHERE e.type='Method'
                   GROUP BY e.id, e.name, e.method_role
                   ORDER BY e.id"""
            ).fetchall()
        ]
        assignment_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT method_entity_id, family_id, candidate_rank,
                          COALESCE(confidence, 0.0) AS confidence,
                          similarity, COALESCE(margin, 0.0) AS margin
                   FROM method_family_assignments
                   WHERE taxonomy_version=? AND status='review'
                   ORDER BY method_entity_id, candidate_rank, family_id""",
                (str(gold["taxonomy_version"]),),
            ).fetchall()
        ]
        prior_blind_ids = {
            int(row["method_entity_id"])
            for row in conn.execute(
                """SELECT i.method_entity_id
                   FROM method_family_blind_items i
                   JOIN method_family_blind_sets s ON s.blind_set_id=i.blind_set_id
                   WHERE s.parent_gold_set_id=? AND s.sampling_version!=?""",
                (parent_gold_set_id, sampling_version),
            ).fetchall()
        }
    training_rows, excluded_ids = _load_training_snapshot(parent_gold_set_id)
    excluded_ids.update(prior_blind_ids)
    training_snapshot_sha = _json_hash(training_rows)
    graph_snapshot_sha = _json_hash(entity_rows)
    seed = _json_hash(
        {
            "sampling_version": sampling_version,
            "graph_snapshot_sha256": graph_snapshot_sha,
            "training_snapshot_sha256": training_snapshot_sha,
            "row_count": size,
        }
    )
    assignments: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in assignment_rows:
        assignments[int(row["method_entity_id"])].append(row)
    inputs = {item.method_entity_id: item for item in load_method_embedding_inputs()}
    candidates: list[dict[str, Any]] = []
    for entity in entity_rows:
        method_id = int(entity["method_entity_id"])
        if method_id in excluded_ids:
            continue
        ranked = assignments.get(method_id, [])
        top1 = ranked[0] if ranked else None
        embedding_input = inputs.get(method_id)
        context_excerpt = embedding_input.text if embedding_input else f"method: {entity['method_name']}"
        context_quality = embedding_input.context_quality if embedding_input else "name_only"
        family = str(top1["family_id"]) if top1 else "__missing__"
        row = {
            **entity,
            "paper_count": int(entity["paper_count"] or 0),
            "context_quality": context_quality,
            "context_excerpt": context_excerpt,
            "stratum": f"{family}|{entity['method_role']}|{_frequency_band(int(entity['paper_count'] or 0))}",
            "hidden_suggested_primary": family,
            "hidden_top1_similarity": float(top1["similarity"]) if top1 else 0.0,
            "hidden_ranking_score": float(top1["confidence"]) if top1 else 0.0,
            "hidden_margin": float(top1["margin"]) if top1 else 0.0,
            "hidden_top3": [
                {
                    "family_id": str(item["family_id"]),
                    "similarity": float(item["similarity"]),
                    "ranking_score": float(item["confidence"]),
                }
                for item in ranked[:3]
            ],
        }
        candidates.append(row)
    if size > len(candidates):
        raise ValueError(f"Requested {size} blind rows, only {len(candidates)} are eligible")
    selected = _sample_stratified(candidates, size=size, seed=seed)
    exported_rows: list[dict[str, Any]] = []
    stored_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(selected, start=1):
        blind_item_id = "blind-" + hashlib.sha256(
            f"{seed}|{row['method_entity_id']}".encode("utf-8")
        ).hexdigest()[:16]
        visible = {
            "blind_rank": rank,
            "blind_item_id": blind_item_id,
            "method_entity_id": int(row["method_entity_id"]),
            "method_name": str(row["method_name"]),
            "method_role": str(row["method_role"]),
            "paper_count": int(row["paper_count"]),
            "first_year": row["first_year"] if row["first_year"] is not None else "",
            "last_year": row["last_year"] if row["last_year"] is not None else "",
            "context_quality": str(row["context_quality"]),
            "context_excerpt": str(row["context_excerpt"]),
            "gold_primary": "",
            "gold_secondary": "",
            "review_notes": "",
        }
        exported_rows.append(visible)
        stored_rows.append(
            {
                **visible,
                "stratum": str(row["stratum"]),
                "hidden_suggested_primary": str(row["hidden_suggested_primary"]),
                "hidden_top1_similarity": float(row["hidden_top1_similarity"]),
                "hidden_ranking_score": float(row["hidden_ranking_score"]),
                "hidden_margin": float(row["hidden_margin"]),
                "hidden_top3": row["hidden_top3"],
            }
        )
    sample_snapshot_sha = _json_hash(stored_rows)
    raw = _csv_bytes(exported_rows)
    export_sha = hashlib.sha256(raw).hexdigest()
    blind_set_id = "blind-" + _json_hash(
        {
            "parent_gold_set_id": parent_gold_set_id,
            "sample_snapshot_sha256": sample_snapshot_sha,
        }
    )[:24]
    target = _write_bytes(output_path, raw)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM method_family_blind_sets WHERE blind_set_id=?", (blind_set_id,)
        ).fetchone()
        if existing:
            if str(existing["export_sha256"]) != export_sha:
                raise ValueError("Existing blind set has a different export hash")
            idempotent = True
        else:
            conn.execute(
                """INSERT INTO method_family_blind_sets
                   (blind_set_id, parent_gold_set_id, taxonomy_version,
                    graph_snapshot_sha256, training_snapshot_sha256, sampling_version,
                    seed_sha256, sample_snapshot_sha256, export_sha256,
                    source_filename, row_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    blind_set_id,
                    parent_gold_set_id,
                    str(gold["taxonomy_version"]),
                    graph_snapshot_sha,
                    training_snapshot_sha,
                    sampling_version,
                    seed,
                    sample_snapshot_sha,
                    export_sha,
                    target.name,
                    size,
                ),
            )
            conn.executemany(
                """INSERT INTO method_family_blind_items
                   (blind_set_id, blind_rank, blind_item_id, method_entity_id,
                    method_name_snapshot, method_role_snapshot, paper_count_snapshot,
                    first_year_snapshot, last_year_snapshot, context_quality_snapshot,
                    context_excerpt_snapshot, stratum_snapshot,
                    hidden_suggested_primary, hidden_top1_similarity,
                    hidden_ranking_score, hidden_margin, hidden_top3_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        blind_set_id,
                        row["blind_rank"],
                        row["blind_item_id"],
                        row["method_entity_id"],
                        row["method_name"],
                        row["method_role"],
                        row["paper_count"],
                        row["first_year"] or None,
                        row["last_year"] or None,
                        row["context_quality"],
                        row["context_excerpt"],
                        row["stratum"],
                        row["hidden_suggested_primary"],
                        row["hidden_top1_similarity"],
                        row["hidden_ranking_score"],
                        row["hidden_margin"],
                        json.dumps(row["hidden_top3"], ensure_ascii=False, sort_keys=True),
                    )
                    for row in stored_rows
                ],
            )
            idempotent = False
    return {
        "blind_set_id": blind_set_id,
        "status": "awaiting_blind_labels",
        "idempotent": idempotent,
        "output": str(target),
        "rows": size,
        "eligible_pool": len(candidates),
        "generation": generation,
        "prior_blind_methods_excluded": len(prior_blind_ids),
        "export_sha256": export_sha,
        "sample_snapshot_sha256": sample_snapshot_sha,
        "graph_snapshot_sha256": graph_snapshot_sha,
        "training_snapshot_sha256": training_snapshot_sha,
        "visible_model_suggestions": 0,
        "family_strata": dict(Counter(row["hidden_suggested_primary"] for row in stored_rows)),
        "context_quality": dict(Counter(row["context_quality"] for row in stored_rows)),
    }


def import_blind_submission(
    path: str | Path,
    *,
    blind_set_id: str,
    reviewer: str,
    expected_sha256: str | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate complete blind labels and freeze them without training on them."""
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    target = Path(path)
    raw = target.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and file_sha != expected_sha256.strip().lower():
        raise BlindValidationError([f"SHA-256 mismatch: expected {expected_sha256}, got {file_sha}"])
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != BLIND_FIELDS:
        raise BlindValidationError(["CSV columns or order differ from the frozen blind template"])
    submitted = list(reader)
    with get_conn() as conn:
        blind = conn.execute(
            "SELECT * FROM method_family_blind_sets WHERE blind_set_id=?", (blind_set_id,)
        ).fetchone()
        if not blind:
            raise ValueError(f"Unknown blind set: {blind_set_id}")
        frozen = [
            dict(row)
            for row in conn.execute(
                """SELECT blind_rank, blind_item_id, method_entity_id,
                          method_name_snapshot AS method_name,
                          method_role_snapshot AS method_role,
                          paper_count_snapshot AS paper_count,
                          COALESCE(first_year_snapshot, '') AS first_year,
                          COALESCE(last_year_snapshot, '') AS last_year,
                          context_quality_snapshot AS context_quality,
                          context_excerpt_snapshot AS context_excerpt
                   FROM method_family_blind_items WHERE blind_set_id=?
                   ORDER BY blind_rank""",
                (blind_set_id,),
            ).fetchall()
        ]
        existing = conn.execute(
            "SELECT metrics_json FROM method_family_blind_submissions WHERE blind_set_id=?",
            (blind_set_id,),
        ).fetchone()
    if existing:
        report = json.loads(str(existing["metrics_json"]))
        report["idempotent"] = True
        return report
    errors: list[str] = []
    if len(submitted) != int(blind["row_count"]):
        errors.append(f"Expected {blind['row_count']} rows, got {len(submitted)}")
    valid_families = {family.family_id for family in FAMILIES}
    valid_primary = valid_families | {"unknown"}
    labels: list[dict[str, Any]] = []
    for index, expected in enumerate(frozen):
        if index >= len(submitted):
            break
        row = submitted[index]
        rank = index + 1
        for field in SNAPSHOT_FIELDS:
            if str(row.get(field, "")) != str(expected[field]):
                errors.append(f"blind_rank {rank}: frozen field {field} was changed")
        primary = str(row.get("gold_primary", "")).strip()
        if primary not in valid_primary:
            errors.append(f"blind_rank {rank}: gold_primary must be a family ID or explicit unknown")
            continue
        secondary = tuple(
            part.strip() for part in str(row.get("gold_secondary", "")).split("|") if part.strip()
        )
        invalid = set(secondary) - valid_families
        if invalid:
            errors.append(f"blind_rank {rank}: invalid secondary labels {sorted(invalid)}")
        if len(secondary) != len(set(secondary)):
            errors.append(f"blind_rank {rank}: duplicate secondary label")
        if primary in secondary:
            errors.append(f"blind_rank {rank}: primary repeated in secondary")
        if primary == "unknown" and secondary:
            errors.append(f"blind_rank {rank}: unknown cannot have secondary labels")
        labels.append(
            {
                "blind_rank": rank,
                "blind_item_id": str(row["blind_item_id"]),
                "method_entity_id": int(row["method_entity_id"]),
                "normalized_primary": primary,
                "secondary": secondary,
                "review_notes": str(row.get("review_notes", "")).strip(),
            }
        )
    if errors:
        raise BlindValidationError(errors)
    label_snapshot_sha = _json_hash(labels)
    submission_id = "blindsub-" + _json_hash(
        {"blind_set_id": blind_set_id, "label_snapshot_sha256": label_snapshot_sha}
    )[:24]
    known = sum(row["normalized_primary"] != "unknown" for row in labels)
    report = {
        "submission_id": submission_id,
        "blind_set_id": blind_set_id,
        "status": "blind_labels_frozen",
        "idempotent": False,
        "file_sha256": file_sha,
        "label_snapshot_sha256": label_snapshot_sha,
        "counts": {
            "rows": len(labels),
            "known": known,
            "unknown": len(labels) - known,
            "secondary_labels": sum(len(row["secondary"]) for row in labels),
        },
        "primary_distribution": dict(Counter(row["normalized_primary"] for row in labels)),
        "safety": {
            "used_for_training": False,
            "accepted_assignments_written": 0,
            "active_release_created": False,
        },
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_blind_submissions
               (submission_id, blind_set_id, file_sha256, source_filename,
                label_snapshot_sha256, reviewer, row_count, known_count,
                unknown_count, secondary_count, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                submission_id,
                blind_set_id,
                file_sha,
                target.name,
                label_snapshot_sha,
                reviewer,
                len(labels),
                known,
                len(labels) - known,
                sum(len(row["secondary"]) for row in labels),
                json.dumps(report, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.executemany(
            """INSERT INTO method_family_blind_submission_labels
               (submission_id, blind_set_id, blind_rank, blind_item_id,
                method_entity_id, normalized_primary, secondary_json, review_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    submission_id,
                    blind_set_id,
                    row["blind_rank"],
                    row["blind_item_id"],
                    row["method_entity_id"],
                    row["normalized_primary"],
                    json.dumps(row["secondary"], ensure_ascii=False),
                    row["review_notes"],
                )
                for row in labels
            ],
        )
    if output_path:
        report_path = Path(output_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
