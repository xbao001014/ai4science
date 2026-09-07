"""Immutable Gold ingestion and offline calibration for Method families."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

import config
from analysis.method_synonyms import resolve_method_entity_canonical
from analysis.method_taxonomy import FAMILIES
from db.schema import get_conn


REQUIRED_COLUMNS = (
    "method_entity_id",
    "method_name",
    "method_role",
    "paper_count",
    "first_year",
    "last_year",
    "suggested_primary",
    "top1_similarity",
    "ranking_score",
    "margin",
    "suggested_top3",
    "gold_primary",
    "gold_secondary",
    "review_notes",
)
NORMALIZATION_POLICY = "explicit_unknown_or_legacy_reject_v1"
LEGACY_REJECT_PREFIX = "[reject]"
SPLIT_VERSION = "gold-group-stratified-v1"
CALIBRATION_VERSION = "embedding-threshold-v2"
DEFAULT_HOLDOUT_FRACTION = 0.30
DEFAULT_MIN_ENTITY_PRECISION = 0.90
DEFAULT_MIN_PAPER_PRECISION = 0.95
DEFAULT_MIN_FAMILY_CALIBRATION_ACCEPTS = 10
DEFAULT_MIN_FAMILY_HOLDOUT_ACCEPTS = 10
DEFAULT_BLOCKED_EMBEDDING_FAMILIES = frozenset(
    {"image_processing", "multimodal_fusion", "generative_model"}
)


class GoldValidationError(ValueError):
    """Raised when a Gold CSV cannot be used safely."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        preview = "; ".join(self.errors[:8])
        if len(self.errors) > 8:
            preview += f"; ... ({len(self.errors) - 8} more)"
        super().__init__(preview)


@dataclass(frozen=True)
class GoldRow:
    source_row: int
    method_entity_id: int
    method_name: str
    method_role: str
    paper_count: int
    first_year: int | None
    last_year: int | None
    suggested_primary: str
    top1_similarity: float
    ranking_score: float
    margin: float
    suggested_top3: tuple[str, ...]
    raw_primary: str
    normalized_primary: str
    secondary: tuple[str, ...]
    review_notes: str
    split_group: str
    split: str = ""


@dataclass(frozen=True)
class GoldValidation:
    path: Path
    file_sha256: str
    byte_count: int
    taxonomy_version: str
    rows: tuple[GoldRow, ...]
    split_manifest_sha256: str = ""


def _parse_int(
    value: Any,
    *,
    row_number: int,
    field: str,
    required: bool = True,
    minimum: int | None = None,
) -> int | None:
    text = str(value or "").strip()
    if not text and not required:
        return None
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        raise ValueError(f"row {row_number}: {field} must be an integer") from None
    if minimum is not None and parsed < minimum:
        raise ValueError(f"row {row_number}: {field} must be >= {minimum}")
    return parsed


def _parse_float(value: Any, *, row_number: int, field: str) -> float:
    try:
        parsed = float(str(value or "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"row {row_number}: {field} must be numeric") from None
    if not math.isfinite(parsed):
        raise ValueError(f"row {row_number}: {field} must be finite")
    return parsed


def _split_group(method_name: str) -> str:
    canonical = resolve_method_entity_canonical(method_name).casefold().strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _frequency_band(paper_count: int) -> str:
    if paper_count >= 10:
        return "high"
    if paper_count >= 2:
        return "medium"
    return "singleton"


def load_and_validate_gold_csv(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_rows: int | None = 400,
    taxonomy_version: str = config.METHOD_TAXONOMY_VERSION,
) -> GoldValidation:
    """Parse a Gold CSV without changing it and return normalized labels."""
    target = Path(path)
    raw = target.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest != expected_sha256.strip().lower():
        raise GoldValidationError(
            [f"SHA-256 mismatch: expected {expected_sha256.strip().lower()}, got {digest}"]
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GoldValidationError([f"CSV must be UTF-8/UTF-8-BOM: {exc}"]) from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = tuple(reader.fieldnames or ())
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise GoldValidationError([f"Missing required columns: {', '.join(missing)}"])

    valid_families = {family.family_id for family in FAMILIES}
    parsed_rows: list[GoldRow] = []
    errors: list[str] = []
    seen_ids: set[int] = set()
    seen_groups: dict[str, tuple[int, str]] = {}
    for row_number, row in enumerate(reader, start=2):
        try:
            method_entity_id = _parse_int(
                row.get("method_entity_id"),
                row_number=row_number,
                field="method_entity_id",
                minimum=1,
            )
            assert method_entity_id is not None
            if method_entity_id in seen_ids:
                raise ValueError(f"row {row_number}: duplicate method_entity_id {method_entity_id}")
            seen_ids.add(method_entity_id)

            method_name = str(row.get("method_name") or "").strip()
            if not method_name:
                raise ValueError(f"row {row_number}: method_name is required")
            method_role = str(row.get("method_role") or "unknown").strip() or "unknown"
            paper_count = _parse_int(
                row.get("paper_count"),
                row_number=row_number,
                field="paper_count",
                minimum=0,
            )
            assert paper_count is not None
            first_year = _parse_int(
                row.get("first_year"),
                row_number=row_number,
                field="first_year",
                required=False,
                minimum=1000,
            )
            last_year = _parse_int(
                row.get("last_year"),
                row_number=row_number,
                field="last_year",
                required=False,
                minimum=1000,
            )
            if first_year is not None and last_year is not None and first_year > last_year:
                raise ValueError(f"row {row_number}: first_year is after last_year")

            suggested_primary = str(row.get("suggested_primary") or "").strip()
            if suggested_primary not in valid_families:
                raise ValueError(
                    f"row {row_number}: invalid suggested_primary {suggested_primary!r}"
                )
            suggested_top3 = tuple(
                item.strip()
                for item in str(row.get("suggested_top3") or "").split("|")
                if item.strip()
            )
            if not suggested_top3 or len(suggested_top3) > 3:
                raise ValueError(f"row {row_number}: suggested_top3 must contain 1-3 families")
            if len(suggested_top3) != len(set(suggested_top3)):
                raise ValueError(f"row {row_number}: suggested_top3 contains duplicates")
            invalid_suggested = [item for item in suggested_top3 if item not in valid_families]
            if invalid_suggested:
                raise ValueError(
                    f"row {row_number}: invalid suggested_top3 family {invalid_suggested[0]!r}"
                )
            if suggested_top3[0] != suggested_primary:
                raise ValueError(
                    f"row {row_number}: suggested_primary must be first in suggested_top3"
                )

            top1_similarity = _parse_float(
                row.get("top1_similarity"), row_number=row_number, field="top1_similarity"
            )
            if not -1.0 <= top1_similarity <= 1.0:
                raise ValueError(f"row {row_number}: top1_similarity must be between -1 and 1")
            ranking_score = _parse_float(
                row.get("ranking_score"), row_number=row_number, field="ranking_score"
            )
            margin = _parse_float(row.get("margin"), row_number=row_number, field="margin")
            if margin < 0:
                raise ValueError(f"row {row_number}: margin must be >= 0")

            raw_primary = str(row.get("gold_primary") or "").strip()
            review_notes = str(row.get("review_notes") or "").strip()
            legacy_reject = review_notes.casefold().startswith(LEGACY_REJECT_PREFIX)
            if raw_primary in valid_families or raw_primary == "unknown":
                normalized_primary = raw_primary
            elif not raw_primary and legacy_reject:
                normalized_primary = "unknown"
            elif not raw_primary:
                raise ValueError(
                    f"row {row_number}: empty gold_primary requires a {LEGACY_REJECT_PREFIX} note"
                )
            else:
                raise ValueError(f"row {row_number}: invalid gold_primary {raw_primary!r}")

            secondary = tuple(
                item.strip()
                for item in str(row.get("gold_secondary") or "").split("|")
                if item.strip()
            )
            if len(secondary) != len(set(secondary)):
                raise ValueError(f"row {row_number}: gold_secondary contains duplicates")
            invalid_secondary = [item for item in secondary if item not in valid_families]
            if invalid_secondary:
                raise ValueError(
                    f"row {row_number}: invalid gold_secondary family {invalid_secondary[0]!r}"
                )
            if normalized_primary in secondary:
                raise ValueError(f"row {row_number}: primary family is repeated in secondary")
            if normalized_primary == "unknown" and secondary:
                raise ValueError(f"row {row_number}: unknown label cannot have secondary families")

            split_group = _split_group(method_name)
            previous = seen_groups.get(split_group)
            if previous is not None:
                raise ValueError(
                    f"row {row_number}: method aliases duplicate split group from row {previous[0]}"
                )
            seen_groups[split_group] = (row_number, method_name)
            parsed_rows.append(
                GoldRow(
                    source_row=row_number,
                    method_entity_id=method_entity_id,
                    method_name=method_name,
                    method_role=method_role,
                    paper_count=paper_count,
                    first_year=first_year,
                    last_year=last_year,
                    suggested_primary=suggested_primary,
                    top1_similarity=top1_similarity,
                    ranking_score=ranking_score,
                    margin=margin,
                    suggested_top3=suggested_top3,
                    raw_primary=raw_primary,
                    normalized_primary=normalized_primary,
                    secondary=secondary,
                    review_notes=review_notes,
                    split_group=split_group,
                )
            )
        except ValueError as exc:
            errors.append(str(exc))

    if expected_rows is not None and len(parsed_rows) != int(expected_rows):
        errors.append(f"Expected {int(expected_rows)} valid rows, got {len(parsed_rows)}")
    if not parsed_rows:
        errors.append("Gold CSV has no valid data rows")
    if errors:
        raise GoldValidationError(errors)
    return GoldValidation(
        path=target.resolve(),
        file_sha256=digest,
        byte_count=len(raw),
        taxonomy_version=taxonomy_version,
        rows=tuple(parsed_rows),
    )


def _apportion(
    counts: dict[str, int],
    target: int,
    *,
    minimum_one: bool,
) -> dict[str, int]:
    total = sum(counts.values())
    if total <= 0 or target < 0 or target > total:
        raise ValueError("Invalid split apportionment")
    ideals = {key: target * count / total for key, count in counts.items()}
    quotas = {
        key: min(
            count,
            max(1 if minimum_one and count >= 2 and target else 0, math.floor(ideals[key])),
        )
        for key, count in counts.items()
    }
    while sum(quotas.values()) < target:
        candidates = [key for key, count in counts.items() if quotas[key] < count]
        if not candidates:
            raise ValueError("Cannot reach the requested holdout size")
        key = max(candidates, key=lambda item: (ideals[item] - quotas[item], counts[item], item))
        quotas[key] += 1
    while sum(quotas.values()) > target:
        candidates = [
            key
            for key in counts
            if quotas[key] > (1 if minimum_one and counts[key] >= 2 and target else 0)
        ]
        if not candidates:
            raise ValueError("Cannot reduce to the requested holdout size")
        key = min(candidates, key=lambda item: (ideals[item] - quotas[item], counts[item], item))
        quotas[key] -= 1
    return quotas


def assign_deterministic_split(
    validation: GoldValidation,
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
) -> GoldValidation:
    """Assign a reproducible label/role/frequency-stratified split."""
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between 0 and 1")
    rows = list(validation.rows)
    target_holdout = round(len(rows) * holdout_fraction)
    label_counts = Counter(row.normalized_primary for row in rows)
    label_quotas = _apportion(dict(label_counts), target_holdout, minimum_one=True)

    selected: set[int] = set()
    by_label: dict[str, list[GoldRow]] = defaultdict(list)
    for row in rows:
        by_label[row.normalized_primary].append(row)
    for label, label_rows in sorted(by_label.items()):
        by_substratum: dict[str, list[GoldRow]] = defaultdict(list)
        for row in label_rows:
            key = f"{row.method_role}|{_frequency_band(row.paper_count)}"
            by_substratum[key].append(row)
        sub_counts = {key: len(values) for key, values in by_substratum.items()}
        sub_quotas = _apportion(sub_counts, label_quotas[label], minimum_one=False)
        for stratum, stratum_rows in sorted(by_substratum.items()):
            ordered = sorted(
                stratum_rows,
                key=lambda row: hashlib.sha256(
                    f"{SPLIT_VERSION}|{validation.file_sha256}|{label}|{stratum}|"
                    f"{row.split_group}".encode("utf-8")
                ).hexdigest(),
            )
            selected.update(row.method_entity_id for row in ordered[: sub_quotas[stratum]])

    split_rows = tuple(
        replace(row, split="holdout" if row.method_entity_id in selected else "calibration")
        for row in rows
    )
    if sum(row.split == "holdout" for row in split_rows) != target_holdout:
        raise ValueError("Deterministic split did not produce the requested holdout size")
    manifest = [
        {
            "method_entity_id": row.method_entity_id,
            "split": row.split,
            "split_group": row.split_group,
        }
        for row in sorted(split_rows, key=lambda item: item.method_entity_id)
    ]
    manifest_sha = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return replace(validation, rows=split_rows, split_manifest_sha256=manifest_sha)


def _distribution(rows: Iterable[GoldRow], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(row, field)) for row in rows).items()))


def gold_summary(validation: GoldValidation) -> dict[str, Any]:
    rows = validation.rows
    split_counts = Counter(row.split for row in rows if row.split)
    split_by_label: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        if row.split:
            split_by_label[row.normalized_primary][row.split] += 1
    return {
        "valid": True,
        "taxonomy_version": validation.taxonomy_version,
        "file_sha256": validation.file_sha256,
        "byte_count": validation.byte_count,
        "rows": len(rows),
        "known_rows": sum(row.normalized_primary != "unknown" for row in rows),
        "unknown_rows": sum(row.normalized_primary == "unknown" for row in rows),
        "legacy_reject_rows": sum(
            not row.raw_primary
            and row.review_notes.casefold().startswith(LEGACY_REJECT_PREFIX)
            for row in rows
        ),
        "secondary_labels": sum(len(row.secondary) for row in rows),
        "primary_distribution": _distribution(rows, "normalized_primary"),
        "normalization_policy": NORMALIZATION_POLICY,
        "split_version": SPLIT_VERSION,
        "split_manifest_sha256": validation.split_manifest_sha256 or None,
        "split_counts": dict(sorted(split_counts.items())),
        "split_by_label": {
            label: dict(sorted(counts.items())) for label, counts in sorted(split_by_label.items())
        },
    }


def _ensure_methods_exist(rows: Sequence[GoldRow]) -> None:
    found: dict[int, str] = {}
    ids = [row.method_entity_id for row in rows]
    with get_conn() as conn:
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            marks = ",".join("?" for _ in chunk)
            for record in conn.execute(
                f"SELECT id, type FROM entities WHERE id IN ({marks})", tuple(chunk)
            ).fetchall():
                found[int(record["id"])] = str(record["type"])
    missing = [method_id for method_id in ids if method_id not in found]
    wrong_type = [method_id for method_id in ids if found.get(method_id) != "Method"]
    errors = []
    if missing:
        errors.append(f"Gold references missing entity IDs: {missing[:10]}")
    if wrong_type:
        errors.append(f"Gold references non-Method entity IDs: {wrong_type[:10]}")
    if errors:
        raise GoldValidationError(errors)


def import_gold_set(
    path: str | Path,
    *,
    reviewer: str,
    expected_sha256: str | None = None,
    expected_rows: int | None = 400,
    taxonomy_version: str = config.METHOD_TAXONOMY_VERSION,
) -> dict[str, Any]:
    """Validate, split and immutably import one expert Gold set."""
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    validation = assign_deterministic_split(
        load_and_validate_gold_csv(
            path,
            expected_sha256=expected_sha256,
            expected_rows=expected_rows,
            taxonomy_version=taxonomy_version,
        )
    )
    _ensure_methods_exist(validation.rows)
    gold_set_id = f"gold-{taxonomy_version}-{validation.file_sha256[:16]}"
    summary = gold_summary(validation)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT gold_set_id FROM method_family_gold_sets WHERE file_sha256=?",
            (validation.file_sha256,),
        ).fetchone()
        if existing:
            summary.update(
                {
                    "gold_set_id": str(existing["gold_set_id"]),
                    "idempotent": True,
                    "imported_rows": conn.execute(
                        "SELECT COUNT(*) FROM method_family_gold_labels WHERE gold_set_id=?",
                        (existing["gold_set_id"],),
                    ).fetchone()[0],
                }
            )
            return summary
        known = int(summary["known_rows"])
        unknown = int(summary["unknown_rows"])
        calibration_count = sum(row.split == "calibration" for row in validation.rows)
        holdout_count = sum(row.split == "holdout" for row in validation.rows)
        conn.execute(
            """INSERT INTO method_family_gold_sets
               (gold_set_id, taxonomy_version, file_sha256, source_filename,
                byte_count, row_count, known_count, unknown_count, secondary_count,
                normalization_policy, reviewer, split_manifest_sha256,
                calibration_count, holdout_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                gold_set_id,
                taxonomy_version,
                validation.file_sha256,
                validation.path.name,
                validation.byte_count,
                len(validation.rows),
                known,
                unknown,
                int(summary["secondary_labels"]),
                NORMALIZATION_POLICY,
                reviewer,
                validation.split_manifest_sha256,
                calibration_count,
                holdout_count,
            ),
        )
        conn.executemany(
            """INSERT INTO method_family_gold_labels
               (gold_set_id, method_entity_id, source_row, method_name_snapshot,
                method_role_snapshot, paper_count_snapshot, first_year_snapshot,
                last_year_snapshot, raw_primary, normalized_primary, secondary_json,
                review_notes, suggested_primary, top1_similarity, ranking_score,
                margin, suggested_top3_json, split, split_group)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    gold_set_id,
                    row.method_entity_id,
                    row.source_row,
                    row.method_name,
                    row.method_role,
                    row.paper_count,
                    row.first_year,
                    row.last_year,
                    row.raw_primary,
                    row.normalized_primary,
                    json.dumps(row.secondary, ensure_ascii=False),
                    row.review_notes,
                    row.suggested_primary,
                    row.top1_similarity,
                    row.ranking_score,
                    row.margin,
                    json.dumps(row.suggested_top3, ensure_ascii=False),
                    row.split,
                    row.split_group,
                )
                for row in validation.rows
            ],
        )
    summary.update({"gold_set_id": gold_set_id, "idempotent": False, "imported_rows": len(validation.rows)})
    return summary


def _load_gold_labels(gold_set_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with get_conn() as conn:
        gold = conn.execute(
            "SELECT * FROM method_family_gold_sets WHERE gold_set_id=?", (gold_set_id,)
        ).fetchone()
        if not gold:
            raise ValueError(f"Unknown Gold set: {gold_set_id}")
        rows = conn.execute(
            """SELECT method_entity_id, normalized_primary, suggested_primary,
                      ranking_score, margin, paper_count_snapshot, split
               FROM method_family_gold_labels
               WHERE gold_set_id=? ORDER BY method_entity_id""",
            (gold_set_id,),
        ).fetchall()
    return dict(gold), [dict(row) for row in rows]


def _evaluate(
    rows: Sequence[dict[str, Any]],
    *,
    score_min: float,
    margin_min: float,
    allowed_families: set[str],
) -> dict[str, Any]:
    accepted = [
        row
        for row in rows
        if str(row["suggested_primary"]) in allowed_families
        and float(row["ranking_score"]) >= score_min
        and float(row["margin"]) >= margin_min
    ]
    correct = [
        row
        for row in accepted
        if str(row["normalized_primary"]) != "unknown"
        and str(row["suggested_primary"]) == str(row["normalized_primary"])
    ]
    known = [row for row in rows if str(row["normalized_primary"]) != "unknown"]
    accepted_papers = sum(int(row["paper_count_snapshot"]) for row in accepted)
    correct_papers = sum(int(row["paper_count_snapshot"]) for row in correct)
    known_papers = sum(int(row["paper_count_snapshot"]) for row in known)
    per_family: dict[str, Any] = {}
    all_families = {family.family_id for family in FAMILIES}
    for family_id in sorted(all_families):
        family_gold = [row for row in rows if str(row["normalized_primary"]) == family_id]
        family_accepted = [row for row in accepted if str(row["suggested_primary"]) == family_id]
        family_correct = [
            row for row in family_accepted if str(row["normalized_primary"]) == family_id
        ]
        per_family[family_id] = {
            "gold_support": len(family_gold),
            "accepted_predictions": len(family_accepted),
            "correct": len(family_correct),
            "precision": round(len(family_correct) / len(family_accepted), 6)
            if family_accepted
            else None,
            "recall": round(len(family_correct) / len(family_gold), 6)
            if family_gold
            else None,
        }
    return {
        "rows": len(rows),
        "known_rows": len(known),
        "accepted": len(accepted),
        "correct": len(correct),
        "unknown_false_accepts": sum(
            str(row["normalized_primary"]) == "unknown" for row in accepted
        ),
        "entity_coverage": round(len(accepted) / len(rows), 6) if rows else 0.0,
        "entity_precision": round(len(correct) / len(accepted), 6) if accepted else None,
        "known_recall": round(len(correct) / len(known), 6) if known else None,
        "paper_weighted_precision": round(correct_papers / accepted_papers, 6)
        if accepted_papers
        else None,
        "paper_weighted_recall": round(correct_papers / known_papers, 6)
        if known_papers
        else None,
        "per_family": per_family,
    }


def _select_thresholds(
    rows: Sequence[dict[str, Any]],
    *,
    allowed_families: set[str],
    min_precision: float,
) -> tuple[float, float, dict[str, Any]]:
    max_score = max(float(row["ranking_score"]) for row in rows)
    max_margin = max(float(row["margin"]) for row in rows)
    score_values = [value / 100 for value in range(0, math.ceil(max_score * 100) + 1)]
    margin_values = [value / 100 for value in range(0, math.ceil(max_margin * 100) + 1)]
    best: tuple[tuple[float, float, float, float, float], float, float, dict[str, Any]] | None = None
    for score_min in score_values:
        for margin_min in margin_values:
            metrics = _evaluate(
                rows,
                score_min=score_min,
                margin_min=margin_min,
                allowed_families=allowed_families,
            )
            precision = metrics["entity_precision"]
            if precision is None or float(precision) < min_precision or metrics["accepted"] < 10:
                continue
            objective = (
                float(metrics["paper_weighted_recall"] or 0.0),
                float(metrics["known_recall"] or 0.0),
                float(precision),
                margin_min,
                score_min,
            )
            if best is None or objective > best[0]:
                best = (objective, score_min, margin_min, metrics)
    if best is None:
        raise ValueError("No calibration threshold satisfies the minimum precision")
    return best[1], best[2], best[3]


def calibrate_gold_set(
    gold_set_id: str,
    *,
    output_path: str | Path | None = None,
    blocked_families: Iterable[str] = DEFAULT_BLOCKED_EMBEDDING_FAMILIES,
    min_entity_precision: float = DEFAULT_MIN_ENTITY_PRECISION,
    min_paper_precision: float = DEFAULT_MIN_PAPER_PRECISION,
    min_family_calibration_accepts: int = DEFAULT_MIN_FAMILY_CALIBRATION_ACCEPTS,
    min_family_holdout_accepts: int = DEFAULT_MIN_FAMILY_HOLDOUT_ACCEPTS,
) -> dict[str, Any]:
    """Freeze an embedding-only calibration report; never promote assignments."""
    gold, all_rows = _load_gold_labels(gold_set_id)
    blocked = sorted(set(blocked_families))
    valid_families = {family.family_id for family in FAMILIES}
    invalid_blocked = set(blocked) - valid_families
    if invalid_blocked:
        raise ValueError(f"Unknown blocked families: {sorted(invalid_blocked)}")
    candidate_families = valid_families - set(blocked)
    calibration_key = {
        "version": CALIBRATION_VERSION,
        "gold_set_id": gold_set_id,
        "split_manifest_sha256": gold["split_manifest_sha256"],
        "blocked_families": blocked,
        "min_entity_precision": min_entity_precision,
        "min_paper_precision": min_paper_precision,
        "min_family_calibration_accepts": min_family_calibration_accepts,
        "min_family_holdout_accepts": min_family_holdout_accepts,
    }
    calibration_id = "cal-" + hashlib.sha256(
        json.dumps(calibration_key, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT metrics_json FROM method_family_calibrations WHERE calibration_id=?",
            (calibration_id,),
        ).fetchone()
    if existing:
        report = json.loads(str(existing["metrics_json"]))
        report["idempotent"] = True
        if output_path:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    calibration_rows = [row for row in all_rows if row["split"] == "calibration"]
    holdout_rows = [row for row in all_rows if row["split"] == "holdout"]
    score_min, margin_min, calibration_metrics = _select_thresholds(
        calibration_rows,
        allowed_families=candidate_families,
        min_precision=min_entity_precision,
    )
    holdout_pre_gate = _evaluate(
        holdout_rows,
        score_min=score_min,
        margin_min=margin_min,
        allowed_families=candidate_families,
    )
    family_gate: dict[str, dict[str, Any]] = {}
    embedding_allowlist: list[str] = []
    for family_id in sorted(valid_families):
        calibration_family = calibration_metrics["per_family"][family_id]
        holdout_family = holdout_pre_gate["per_family"][family_id]
        calibration_accepted = int(calibration_family["accepted_predictions"])
        calibration_precision = calibration_family["precision"]
        holdout_accepted = int(holdout_family["accepted_predictions"])
        holdout_precision = holdout_family["precision"]
        if family_id in blocked:
            decision = "blocked_prior"
        elif calibration_accepted < min_family_calibration_accepts:
            decision = "insufficient_calibration_support"
        elif calibration_precision is None or float(calibration_precision) < min_entity_precision:
            decision = "failed_calibration_precision"
        elif holdout_accepted < min_family_holdout_accepts:
            decision = "insufficient_holdout_support"
        elif holdout_precision is not None and float(holdout_precision) >= min_entity_precision:
            decision = "eligible"
            embedding_allowlist.append(family_id)
        else:
            decision = "failed_holdout_precision"
        family_gate[family_id] = {
            "decision": decision,
            "calibration_accepted_predictions": calibration_accepted,
            "calibration_precision": calibration_precision,
            "calibration_gold_support": calibration_family["gold_support"],
            "holdout_accepted_predictions": holdout_accepted,
            "holdout_precision": holdout_precision,
            "holdout_gold_support": holdout_family["gold_support"],
        }

    holdout_final = _evaluate(
        holdout_rows,
        score_min=score_min,
        margin_min=margin_min,
        allowed_families=set(embedding_allowlist),
    )
    calibration_final = _evaluate(
        calibration_rows,
        score_min=score_min,
        margin_min=margin_min,
        allowed_families=set(embedding_allowlist),
    )
    gates = {
        "pre_gate_holdout_entity_precision": (
            holdout_pre_gate["entity_precision"] is not None
            and float(holdout_pre_gate["entity_precision"]) >= min_entity_precision
        ),
        "pre_gate_holdout_paper_precision": (
            holdout_pre_gate["paper_weighted_precision"] is not None
            and float(holdout_pre_gate["paper_weighted_precision"]) >= min_paper_precision
        ),
        "nonempty_embedding_allowlist": bool(embedding_allowlist),
        "final_holdout_entity_precision": (
            holdout_final["entity_precision"] is not None
            and float(holdout_final["entity_precision"]) >= min_entity_precision
        ),
        "final_holdout_paper_precision": (
            holdout_final["paper_weighted_precision"] is not None
            and float(holdout_final["paper_weighted_precision"]) >= min_paper_precision
        ),
    }
    threshold_validated = all(gates.values())
    report = {
        "calibration_id": calibration_id,
        "gold_set_id": gold_set_id,
        "gold_file_sha256": gold["file_sha256"],
        "split_manifest_sha256": gold["split_manifest_sha256"],
        "taxonomy_version": gold["taxonomy_version"],
        "calibration_version": CALIBRATION_VERSION,
        "status": "threshold_validated" if threshold_validated else "threshold_rejected",
        "release_build_eligible": False,
        "release_blocker": "Strict rules and production paper coverage are not part of C0-A",
        "idempotent": False,
        "thresholds": {
            "ranking_score_min": score_min,
            "margin_min": margin_min,
            "min_entity_precision": min_entity_precision,
            "min_paper_precision": min_paper_precision,
            "min_family_calibration_accepts": min_family_calibration_accepts,
            "min_family_holdout_accepts": min_family_holdout_accepts,
        },
        "blocked_embedding_families": blocked,
        "candidate_embedding_families": sorted(candidate_families),
        "embedding_family_allowlist": embedding_allowlist,
        "split_counts": {
            "calibration": len(calibration_rows),
            "holdout": len(holdout_rows),
        },
        "calibration_pre_family_gate": calibration_metrics,
        "holdout_pre_family_gate": holdout_pre_gate,
        "family_gate": family_gate,
        "calibration_final_allowlist": calibration_final,
        "holdout_final_allowlist": holdout_final,
        "gates": gates,
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_calibrations
               (calibration_id, gold_set_id, taxonomy_version,
                split_manifest_sha256, ruleset_version, thresholds_json,
                embedding_family_allowlist_json, blocked_families_json,
                metrics_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                calibration_id,
                gold_set_id,
                gold["taxonomy_version"],
                gold["split_manifest_sha256"],
                "none-c0a",
                json.dumps(report["thresholds"], sort_keys=True),
                json.dumps(embedding_allowlist, sort_keys=True),
                json.dumps(blocked, sort_keys=True),
                json.dumps(report, ensure_ascii=False, sort_keys=True),
                report["status"],
            ),
        )
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
