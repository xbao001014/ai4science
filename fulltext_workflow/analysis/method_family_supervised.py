"""Local supervised Method-family model, blind gate, and immutable release."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

import config
from analysis.embedding_inputs import load_method_embedding_inputs
from analysis.embedding_store import get_cached_vectors
from analysis.method_family_rules import _load_frozen_rules, match_strict_rule
from analysis.method_taxonomy import FAMILIES
from db.schema import get_conn


ALGORITHM_VERSION = "balanced-ridge-hybrid-calibrated-fixed-snapshot-v7"
LEXICON_MIN_SUPPORT = 10
FIXED_SOURCE_MIN_SUPPORT = 2
MIN_BLIND_ROWS = 200
MIN_BLIND_PRECISION = 0.95
MIN_BLIND_PAPER_PRECISION = 0.95
MIN_BLIND_COVERAGE = 0.30
MIN_RELEASE_PAPER_COVERAGE = 0.80

_LEXICON_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "based",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "with",
    "approach",
    "algorithm",
    "analysis",
    "framework",
    "method",
    "model",
    "models",
    "network",
    "system",
    "tool",
}


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _write_report(report: dict[str, Any], output_path: str | Path | None) -> None:
    if not output_path:
        return
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _training_rows(parent_gold_set_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = [
            {
                "origin": "gold",
                "origin_id": parent_gold_set_id,
                "method_entity_id": int(row["method_entity_id"]),
                "method_name": str(row["method_name_snapshot"]),
                "paper_count": int(row["paper_count_snapshot"]),
                "label": str(row["normalized_primary"]),
            }
            for row in conn.execute(
                """SELECT method_entity_id, method_name_snapshot,
                          paper_count_snapshot, normalized_primary
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
                "method_name": str(row["method_name_snapshot"]),
                "paper_count": int(row["paper_count_snapshot"]),
                "label": str(row["normalized_primary"]),
            }
            for row in conn.execute(
                """SELECT l.extension_id, l.method_entity_id, l.method_name_snapshot,
                          l.paper_count_snapshot, l.normalized_primary
                   FROM method_family_gold_extension_labels l
                   JOIN method_family_gold_extensions x ON x.extension_id=l.extension_id
                   WHERE x.parent_gold_set_id=?
                   ORDER BY l.extension_id, l.method_entity_id""",
                (parent_gold_set_id,),
            ).fetchall()
        )
        rows.extend(
            {
                "origin": "retired_blind",
                "origin_id": str(row["promotion_id"]),
                "method_entity_id": int(row["method_entity_id"]),
                "method_name": str(row["method_name_snapshot"]),
                "paper_count": int(row["paper_count_snapshot"]),
                "label": str(row["normalized_primary"]),
            }
            for row in conn.execute(
                """SELECT p.promotion_id, l.method_entity_id,
                          i.method_name_snapshot, i.paper_count_snapshot,
                          l.normalized_primary
                   FROM method_family_blind_promotions p
                   JOIN method_family_blind_submission_labels l
                     ON l.submission_id=p.submission_id
                   JOIN method_family_blind_items i
                     ON i.blind_set_id=l.blind_set_id
                    AND i.blind_rank=l.blind_rank
                   WHERE p.parent_gold_set_id=?
                   ORDER BY p.promotion_id, l.method_entity_id""",
                (parent_gold_set_id,),
            ).fetchall()
        )
    deduplicated: dict[int, dict[str, Any]] = {}
    for row in rows:
        method_id = int(row["method_entity_id"])
        existing = deduplicated.get(method_id)
        if existing is not None and str(existing["label"]) != str(row["label"]):
            raise ValueError(
                f"Conflicting training labels for Method {method_id}: "
                f"{existing['label']} vs {row['label']}"
            )
        deduplicated.setdefault(method_id, row)
    return list(deduplicated.values())


def _payload_training_labels(
    model: Any, payload: dict[str, Any]
) -> dict[int, str]:
    """Load the immutable training-label snapshot carried by a model artifact."""
    frozen = payload.get("training_labels")
    if frozen is not None:
        return {int(method_id): str(label) for method_id, label in frozen}
    current_rows = _training_rows(str(model["parent_gold_set_id"]))
    if _json_hash(current_rows) != str(model["training_snapshot_sha256"]):
        raise ValueError(
            "Legacy model training labels no longer match current Gold data; retrain before preview or release"
        )
    return {
        int(row["method_entity_id"]): str(row["label"])
        for row in current_rows
    }


def promote_blind_evaluation(
    evaluation_id: str,
    *,
    promoted_by: str,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Retire a completed blind evaluation and add its labels to future training only."""
    promoted_by = promoted_by.strip()
    if not promoted_by:
        raise ValueError("promoted_by is required")
    with get_conn() as conn:
        evaluation = conn.execute(
            "SELECT * FROM method_family_blind_evaluations WHERE evaluation_id=?",
            (evaluation_id,),
        ).fetchone()
        if not evaluation:
            raise ValueError(f"Unknown blind evaluation: {evaluation_id}")
        if str(evaluation["status"]) not in {"blind_rejected", "blind_validated"}:
            raise ValueError("Only a completed blind evaluation can be promoted")
        submission = conn.execute(
            "SELECT * FROM method_family_blind_submissions WHERE submission_id=?",
            (str(evaluation["submission_id"]),),
        ).fetchone()
        blind = conn.execute(
            "SELECT * FROM method_family_blind_sets WHERE blind_set_id=?",
            (str(submission["blind_set_id"]),),
        ).fetchone()
        labels = [
            dict(row)
            for row in conn.execute(
                """SELECT blind_rank, method_entity_id, normalized_primary,
                          secondary_json, review_notes
                   FROM method_family_blind_submission_labels
                   WHERE submission_id=? ORDER BY blind_rank""",
                (str(submission["submission_id"]),),
            ).fetchall()
        ]
        existing = conn.execute(
            "SELECT metrics_json FROM method_family_blind_promotions WHERE evaluation_id=?",
            (evaluation_id,),
        ).fetchone()
    if existing:
        report = json.loads(str(existing["metrics_json"]))
        report["idempotent"] = True
        _write_report(report, output_path)
        return report
    if len(labels) != int(submission["row_count"]):
        raise ValueError("Blind submission label count does not match its frozen row count")
    label_snapshot_sha = _json_hash(labels)
    promotion_id = "blindprom-" + _json_hash(
        {
            "evaluation_id": evaluation_id,
            "submission_id": str(submission["submission_id"]),
            "label_snapshot_sha256": label_snapshot_sha,
        }
    )[:24]
    distribution = Counter(str(row["normalized_primary"]) for row in labels)
    report = {
        "promotion_id": promotion_id,
        "evaluation_id": evaluation_id,
        "submission_id": str(submission["submission_id"]),
        "blind_set_id": str(submission["blind_set_id"]),
        "parent_gold_set_id": str(blind["parent_gold_set_id"]),
        "status": "retired_blind_promoted_for_future_training",
        "label_snapshot_sha256": label_snapshot_sha,
        "counts": {
            "rows": len(labels),
            "known": sum(row["normalized_primary"] != "unknown" for row in labels),
            "unknown": sum(row["normalized_primary"] == "unknown" for row in labels),
        },
        "primary_distribution": dict(distribution),
        "safety": {
            "original_evaluation_unchanged": True,
            "eligible_for_future_training": True,
            "eligible_for_future_blind_sampling": False,
            "release_gate_reused": False,
        },
        "idempotent": False,
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_blind_promotions
               (promotion_id, evaluation_id, submission_id, parent_gold_set_id,
                label_snapshot_sha256, promoted_by, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                promotion_id,
                evaluation_id,
                str(submission["submission_id"]),
                str(blind["parent_gold_set_id"]),
                label_snapshot_sha,
                promoted_by,
                json.dumps(report, ensure_ascii=False, sort_keys=True),
            ),
        )
    _write_report(report, output_path)
    return report


def _vectors_for_ids(ids: Iterable[int]) -> dict[int, np.ndarray]:
    wanted = set(int(value) for value in ids)
    inputs = {
        item.method_entity_id: item
        for item in load_method_embedding_inputs()
        if item.method_entity_id in wanted
    }
    cached = get_cached_vectors(
        [item.input_sha256 for item in inputs.values()],
        provider=config.EMBEDDING_PROVIDER,
        model=config.EMBEDDING_MODEL,
        dimensions=config.EMBEDDING_DIMENSIONS,
        touch=False,
    )
    vectors: dict[int, np.ndarray] = {}
    for method_id, item in inputs.items():
        record = cached.get(item.input_sha256)
        if record is None:
            continue
        vector = np.asarray(record.values, dtype=np.float64)
        norm = np.linalg.norm(vector)
        if norm > 0 and np.isfinite(norm):
            vectors[method_id] = vector / norm
    return vectors


def _fit_ridge(
    rows: list[dict[str, Any]],
    vectors: dict[int, np.ndarray],
    label_ids: list[str],
    alpha: float,
) -> np.ndarray:
    known = [row for row in rows if row["label"] in label_ids and row["method_entity_id"] in vectors]
    if not known:
        raise ValueError("No known training rows have cached embeddings")
    counts = Counter(str(row["label"]) for row in known)
    x = np.vstack([np.append(vectors[row["method_entity_id"]], 1.0) for row in known])
    y = np.zeros((len(known), len(label_ids)), dtype=np.float64)
    weights = np.asarray(
        [np.sqrt(len(known) / (len(label_ids) * counts[str(row["label"])])) for row in known]
    )
    for index, row in enumerate(known):
        y[index, label_ids.index(str(row["label"]))] = 1.0
    xw = x * weights[:, None]
    yw = y * weights[:, None]
    gram = xw @ xw.T
    gram.flat[:: len(gram) + 1] += float(alpha)
    return xw.T @ np.linalg.solve(gram, yw)


def _score(vector: np.ndarray, weights: np.ndarray, label_ids: list[str]) -> dict[str, Any]:
    scores = np.append(vector, 1.0) @ weights
    order = np.argsort(scores)[::-1]
    top = int(order[0])
    second = int(order[1]) if len(order) > 1 else top
    return {
        "family_id": label_ids[top],
        "score": float(scores[top]),
        "margin": float(scores[top] - scores[second]),
        "top3": [
            {"family_id": label_ids[int(i)], "score": float(scores[int(i)])}
            for i in order[:3]
        ],
    }


def _lexicon_phrases(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", name.casefold())
    phrases: set[str] = set()
    for size in (1, 2, 3, 4):
        for index in range(len(words) - size + 1):
            part = words[index : index + size]
            if size == 1 and (part[0] in _LEXICON_STOPWORDS or len(part[0]) < 3):
                continue
            if all(word in _LEXICON_STOPWORDS for word in part):
                continue
            phrases.add(" ".join(part))
    return phrases


def _learn_lexicon(
    rows: list[dict[str, Any]], *, minimum_support: int = LEXICON_MIN_SUPPORT
) -> dict[str, dict[str, Any]]:
    """Learn only phrases exclusive to one known family and absent from unknown labels."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        for phrase in _lexicon_phrases(str(row["method_name"])):
            counts[phrase][str(row["label"])] += 1
    lexicon: dict[str, dict[str, Any]] = {}
    for phrase, labels in sorted(counts.items()):
        total = sum(labels.values())
        known = [(label, count) for label, count in labels.items() if label != "unknown"]
        if len(known) != 1:
            continue
        label, count = known[0]
        if count >= minimum_support and count == total:
            lexicon[phrase] = {
                "family_id": label,
                "support": count,
                "tokens": len(phrase.split()),
            }
    return lexicon


def _match_lexicon(name: str, lexicon: dict[str, dict[str, Any]]) -> str | None:
    candidates = [
        (phrase, lexicon[phrase])
        for phrase in _lexicon_phrases(name)
        if phrase in lexicon
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            int(item[1]["tokens"]),
            int(item[1]["support"]),
            len(item[0]),
        ),
        reverse=True,
    )
    best_rank = (
        int(candidates[0][1]["tokens"]),
        int(candidates[0][1]["support"]),
    )
    tied = {
        str(item[1]["family_id"])
        for item in candidates
        if (int(item[1]["tokens"]), int(item[1]["support"])) == best_rank
    }
    return next(iter(tied)) if len(tied) == 1 else None


def _folds(rows: list[dict[str, Any]], count: int = 5) -> dict[int, int]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["label"])].append(row)
    result: dict[int, int] = {}
    for label, items in sorted(grouped.items()):
        ordered = sorted(
            items,
            key=lambda row: hashlib.sha256(
                f"{ALGORITHM_VERSION}|{label}|{row['method_entity_id']}".encode("utf-8")
            ).hexdigest(),
        )
        for index, row in enumerate(ordered):
            result[int(row["method_entity_id"])] = index % count
    return result


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [row for row in records if row.get("accepted")]
    correct = [row for row in accepted if row["predicted"] == row["label"] and row["label"] != "unknown"]
    known = [row for row in records if row["label"] != "unknown"]
    paper_den = sum(int(row.get("paper_count") or 0) for row in accepted)
    paper_num = sum(int(row.get("paper_count") or 0) for row in correct)
    family_stats: dict[str, dict[str, Any]] = {}
    for family in sorted({str(row["predicted"]) for row in accepted}):
        family_rows = [row for row in accepted if row["predicted"] == family]
        family_correct = sum(row["label"] == family for row in family_rows)
        family_stats[family] = {
            "accepted": len(family_rows),
            "correct": family_correct,
            "precision": round(family_correct / len(family_rows), 6) if family_rows else None,
        }
    return {
        "rows": len(records),
        "known_rows": len(known),
        "accepted": len(accepted),
        "correct": len(correct),
        "coverage": round(len(accepted) / len(records), 6) if records else 0.0,
        "precision": round(len(correct) / len(accepted), 6) if accepted else None,
        "known_recall": round(len(correct) / len(known), 6) if known else None,
        "paper_weighted_precision": round(paper_num / paper_den, 6) if paper_den else None,
        "unknown_false_accepts": sum(row["label"] == "unknown" for row in accepted),
        "per_predicted_family": family_stats,
    }


def _select_fixed_source_allowlist(
    records: list[dict[str, Any]], *, minimum_support: int = FIXED_SOURCE_MIN_SUPPORT
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """Revalidate frozen rules and learned lexicons on the full OOF label set."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        if row.get("source") == "rule" and row.get("fixed_source_key"):
            grouped[str(row["fixed_source_key"])].append(row)
    allowlist: set[str] = set()
    report: dict[str, dict[str, Any]] = {}
    for key, items in sorted(grouped.items()):
        correct = [row for row in items if row["predicted"] == row["label"]]
        unknown_false_accepts = sum(row["label"] == "unknown" for row in items)
        paper_den = sum(int(row.get("paper_count") or 0) for row in items)
        paper_num = sum(int(row.get("paper_count") or 0) for row in correct)
        precision = len(correct) / len(items)
        paper_precision = paper_num / paper_den if paper_den else 0.0
        eligible = (
            len(items) >= minimum_support
            and unknown_false_accepts == 0
            and precision >= MIN_BLIND_PRECISION
            and paper_precision >= MIN_BLIND_PAPER_PRECISION
        )
        if eligible:
            allowlist.add(key)
        report[key] = {
            "matches": len(items),
            "correct": len(correct),
            "precision": round(precision, 6),
            "paper_weighted_precision": round(paper_precision, 6),
            "unknown_false_accepts": unknown_false_accepts,
            "eligible": eligible,
        }
    return allowlist, report


def _apply_fixed_source_allowlist(
    records: list[dict[str, Any]], allowlist: set[str]
) -> list[dict[str, Any]]:
    """Fall back to the OOF embedding prediction when a fixed source is unsafe."""
    result: list[dict[str, Any]] = []
    for row in records:
        if row.get("source") != "rule" or row.get("fixed_source_key") in allowlist:
            result.append(row)
            continue
        result.append(
            {
                **row,
                "predicted": row["fallback_predicted"],
                "score": row["fallback_score"],
                "margin": row["fallback_margin"],
                "source": "model",
            }
        )
    return result


def _select_thresholds(records: list[dict[str, Any]]) -> tuple[float, float, dict[str, Any]]:
    model_rows = [row for row in records if row["source"] == "model"]
    scores = sorted({float(row["score"]) for row in model_rows})
    margins = sorted({float(row["margin"]) for row in model_rows})
    score_candidates = [-1e9] + [scores[min(len(scores) - 1, int(q * (len(scores) - 1)))] for q in np.linspace(0, 1, 31)]
    margin_candidates = [-1e9] + [margins[min(len(margins) - 1, int(q * (len(margins) - 1)))] for q in np.linspace(0, 1, 31)]
    best: tuple[tuple[float, float, float], float, float, dict[str, Any]] | None = None
    for score_min in sorted(set(score_candidates)):
        for margin_min in sorted(set(margin_candidates)):
            gated = [
                {
                    **row,
                    "accepted": row["source"] == "rule"
                    or (row["source"] == "model" and row["score"] >= score_min and row["margin"] >= margin_min),
                }
                for row in records
            ]
            metrics = _metrics(gated)
            precision = metrics["precision"]
            if precision is None or float(precision) < MIN_BLIND_PRECISION:
                continue
            paper_precision = metrics["paper_weighted_precision"]
            if paper_precision is None or float(paper_precision) < MIN_BLIND_PAPER_PRECISION:
                continue
            if int(metrics["unknown_false_accepts"]) != 0:
                continue
            supported = [
                item
                for item in metrics["per_predicted_family"].values()
                if int(item["accepted"]) >= 5
            ]
            if any(float(item["precision"]) < 0.85 for item in supported):
                continue
            objective = (float(metrics["coverage"]), float(metrics["known_recall"] or 0), score_min)
            if best is None or objective > best[0]:
                best = (objective, float(score_min), float(margin_min), metrics)
    if best is None:
        gated = [{**row, "accepted": row["source"] == "rule"} for row in records]
        return 1e9, 1e9, _metrics(gated)
    return best[1], best[2], best[3]


def _select_family_thresholds(
    records: list[dict[str, Any]], label_ids: list[str]
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Maximize family coverage under family floors and global release gates."""

    def choose(family_id: str, minimum_precision: float) -> dict[str, Any]:
        model_rows = [
            row
            for row in records
            if row["source"] == "model" and row["predicted"] == family_id
        ]
        fixed_rows = [
            row
            for row in records
            if row["source"] == "rule" and row["predicted"] == family_id
        ]
        scores = sorted({float(row["score"]) for row in model_rows})
        margins = sorted({float(row["margin"]) for row in model_rows})
        score_candidates = [-1e9, *scores] if scores else [1e9]
        margin_candidates = [-1e9, *margins] if margins else [1e9]
        best: tuple[tuple[int, int, int, float], dict[str, Any]] | None = None
        for score_min in score_candidates:
            for margin_min in margin_candidates:
                accepted = fixed_rows + [
                    row
                    for row in model_rows
                    if row["score"] >= score_min and row["margin"] >= margin_min
                ]
                if not accepted or any(row["label"] == "unknown" for row in accepted):
                    continue
                correct = [row for row in accepted if row["label"] == family_id]
                precision = len(correct) / len(accepted)
                paper_den = sum(int(row.get("paper_count") or 0) for row in accepted)
                paper_num = sum(int(row.get("paper_count") or 0) for row in correct)
                paper_precision = paper_num / paper_den if paper_den else 0.0
                if precision < minimum_precision or paper_precision < minimum_precision:
                    continue
                objective = (
                    len(accepted),
                    len(correct),
                    paper_num,
                    float(score_min),
                )
                if best is None or objective > best[0]:
                    best = (
                        objective,
                        {
                            "score": float(score_min),
                            "margin": float(margin_min),
                        },
                    )
        return best[1] if best else {"score": 1e9, "margin": 1e9}

    family_precision_floor = {family_id: 0.85 for family_id in label_ids}
    while True:
        thresholds = {
            family_id: choose(family_id, family_precision_floor[family_id])
            for family_id in label_ids
        }
        gated = []
        for row in records:
            family = thresholds[str(row["predicted"])]
            gated.append(
                {
                    **row,
                    "accepted": row["source"] == "rule"
                    or (
                        row["score"] >= family["score"]
                        and row["margin"] >= family["margin"]
                    ),
                }
            )
        metrics = _metrics(gated)
        precision_ok = (
            metrics["precision"] is not None
            and float(metrics["precision"]) >= MIN_BLIND_PRECISION
        )
        paper_precision_ok = (
            metrics["paper_weighted_precision"] is not None
            and float(metrics["paper_weighted_precision"])
            >= MIN_BLIND_PAPER_PRECISION
        )
        if (
            precision_ok
            and paper_precision_ok
            and int(metrics["unknown_false_accepts"]) == 0
        ):
            return thresholds, metrics

        candidates: list[tuple[float, int, str]] = []
        for family_id in label_ids:
            if family_precision_floor[family_id] >= MIN_BLIND_PRECISION:
                continue
            accepted = [
                row
                for row in gated
                if row["accepted"] and row["predicted"] == family_id
            ]
            if not accepted:
                continue
            correct = [row for row in accepted if row["label"] == family_id]
            row_precision = len(correct) / len(accepted)
            paper_den = sum(int(row.get("paper_count") or 0) for row in accepted)
            paper_num = sum(int(row.get("paper_count") or 0) for row in correct)
            paper_precision = paper_num / paper_den if paper_den else 0.0
            candidates.append(
                (min(row_precision, paper_precision), -len(accepted), family_id)
            )
        if not candidates:
            return thresholds, metrics
        family_precision_floor[min(candidates)[2]] = MIN_BLIND_PRECISION


def _serialize_weights(weights: np.ndarray) -> dict[str, Any]:
    values = np.asarray(weights, dtype="<f4")
    return {
        "dtype": "float32-le",
        "shape": list(values.shape),
        "weights_b64": base64.b64encode(values.tobytes()).decode("ascii"),
    }


def _deserialize_weights(payload: dict[str, Any]) -> np.ndarray:
    values = np.frombuffer(base64.b64decode(payload["weights_b64"]), dtype="<f4")
    return values.reshape(tuple(int(v) for v in payload["shape"])).astype(np.float64)


def train_supervised_model(
    parent_gold_set_id: str,
    ruleset_id: str,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Fit a deterministic balanced ridge classifier using cached embeddings only."""
    with get_conn() as conn:
        gold = conn.execute(
            "SELECT * FROM method_family_gold_sets WHERE gold_set_id=?", (parent_gold_set_id,)
        ).fetchone()
        ruleset = conn.execute(
            "SELECT * FROM method_family_rulesets WHERE ruleset_id=?", (ruleset_id,)
        ).fetchone()
    if not gold:
        raise ValueError(f"Unknown Gold set: {parent_gold_set_id}")
    if not ruleset or str(ruleset["gold_set_id"]) != parent_gold_set_id:
        raise ValueError("Ruleset is missing or belongs to a different Gold set")
    if str(ruleset["status"]) != "rules_validated":
        raise ValueError("Ruleset has not passed validation")
    rows = _training_rows(parent_gold_set_id)
    training_snapshot_sha = _json_hash(rows)
    label_ids = sorted(
        {str(row["label"]) for row in rows if row["label"] != "unknown"}
    )
    if len(label_ids) < 2:
        raise ValueError("At least two known families are required")
    vectors = _vectors_for_ids(row["method_entity_id"] for row in rows)
    usable = [row for row in rows if row["method_entity_id"] in vectors]
    missing = len(rows) - len(usable)
    folds = _folds(usable)
    rules, eligible_rule_ids = _load_frozen_rules(ruleset)
    alpha_candidates = (0.1, 1.0, 10.0, 100.0)
    best_alpha: float | None = None
    best_records: list[dict[str, Any]] = []
    best_fixed_source_allowlist: set[str] = set()
    best_fixed_source_report: dict[str, dict[str, Any]] = {}
    best_accuracy = -1.0
    for alpha in alpha_candidates:
        records: list[dict[str, Any]] = []
        for fold in range(5):
            train = [row for row in usable if folds[row["method_entity_id"]] != fold]
            test = [row for row in usable if folds[row["method_entity_id"]] == fold]
            weights = _fit_ridge(train, vectors, label_ids, alpha)
            lexicon = _learn_lexicon(train)
            for row in test:
                fallback = _score(vectors[row["method_entity_id"]], weights, label_ids)
                rule = match_strict_rule(
                    str(row["method_name"]), rules=rules, eligible_rule_ids=eligible_rule_ids
                )
                lexical_family = _match_lexicon(str(row["method_name"]), lexicon)
                if rule is not None:
                    prediction = {
                        "family_id": rule.family_id,
                        "score": 1.0,
                        "margin": 1.0,
                    }
                    source = "rule"
                    fixed_source_key = f"strict_rule:{rule.rule_id}"
                elif lexical_family is not None:
                    prediction = {
                        "family_id": lexical_family,
                        "score": 1.0,
                        "margin": 1.0,
                    }
                    source = "rule"
                    fixed_source_key = f"lexicon:{lexical_family}"
                else:
                    prediction = fallback
                    source = "model"
                    fixed_source_key = None
                records.append(
                    {
                        **row,
                        "predicted": prediction["family_id"],
                        "score": prediction["score"],
                        "margin": prediction["margin"],
                        "source": source,
                        "fixed_source_key": fixed_source_key,
                        "fallback_predicted": fallback["family_id"],
                        "fallback_score": fallback["score"],
                        "fallback_margin": fallback["margin"],
                    }
                )
        fixed_source_allowlist, fixed_source_report = _select_fixed_source_allowlist(records)
        calibrated_records = _apply_fixed_source_allowlist(records, fixed_source_allowlist)
        known = [row for row in calibrated_records if row["label"] != "unknown"]
        accuracy = sum(row["predicted"] == row["label"] for row in known) / len(known)
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_alpha = alpha
            best_records = calibrated_records
            best_fixed_source_allowlist = fixed_source_allowlist
            best_fixed_source_report = fixed_source_report
    assert best_alpha is not None
    family_thresholds, gated_metrics = _select_family_thresholds(best_records, label_ids)
    score_threshold = -1e9
    margin_threshold = -1e9
    final_weights = _fit_ridge(usable, vectors, label_ids, best_alpha)
    final_lexicon = _learn_lexicon(usable)
    model_payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "label_ids": label_ids,
        "alpha": best_alpha,
        "score_threshold": score_threshold,
        "margin_threshold": margin_threshold,
        "threshold_strategy": "per_family_exact_v1",
        "family_thresholds": family_thresholds,
        "lexicon_min_support": LEXICON_MIN_SUPPORT,
        "lexicon": final_lexicon,
        "fixed_source_min_support": FIXED_SOURCE_MIN_SUPPORT,
        "fixed_source_allowlist": sorted(best_fixed_source_allowlist),
        "training_labels": sorted(
            (int(row["method_entity_id"]), str(row["label"])) for row in rows
        ),
        "weights": _serialize_weights(final_weights),
    }
    model_id = "model-" + _json_hash(
        {
            "parent_gold_set_id": parent_gold_set_id,
            "ruleset_id": ruleset_id,
            "training_snapshot_sha256": training_snapshot_sha,
            "model_payload": model_payload,
        }
    )[:24]
    report = {
        "model_id": model_id,
        "parent_gold_set_id": parent_gold_set_id,
        "ruleset_id": ruleset_id,
        "status": "trained_awaiting_blind_evaluation",
        "release_build_eligible": False,
        "algorithm_version": ALGORITHM_VERSION,
        "training_snapshot_sha256": training_snapshot_sha,
        "training_counts": {
            "rows": len(rows),
            "vectors": len(usable),
            "missing_vectors": missing,
            "known": sum(row["label"] != "unknown" for row in usable),
            "unknown": sum(row["label"] == "unknown" for row in usable),
        },
        "label_distribution": dict(Counter(str(row["label"]) for row in usable)),
        "selected": {
            "alpha": best_alpha,
            "score_threshold": score_threshold,
            "margin_threshold": margin_threshold,
            "threshold_strategy": "per_family_exact_v1",
            "family_thresholds": family_thresholds,
            "lexicon_min_support": LEXICON_MIN_SUPPORT,
            "lexicon_phrases": len(final_lexicon),
            "fixed_source_min_support": FIXED_SOURCE_MIN_SUPPORT,
            "fixed_source_allowlist": sorted(best_fixed_source_allowlist),
            "fixed_source_validation": best_fixed_source_report,
        },
        "cross_validation": {
            "folds": 5,
            "ungated_known_top1_accuracy": round(best_accuracy, 6),
            "gated": gated_metrics,
            "warning": "Training cross-validation is diagnostic only; the independent blind set is the release gate.",
        },
    }
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT metrics_json FROM method_family_models WHERE model_id=?", (model_id,)
        ).fetchone()
        if existing:
            result = json.loads(str(existing["metrics_json"]))
            result["idempotent"] = True
            _write_report(result, output_path)
            return result
        conn.execute(
            """INSERT INTO method_family_models
               (model_id, parent_gold_set_id, ruleset_id, taxonomy_version,
                training_snapshot_sha256, algorithm_version, provider,
                embedding_model, dimensions, alpha, score_threshold,
                margin_threshold, label_ids_json, model_json, metrics_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_id,
                parent_gold_set_id,
                ruleset_id,
                str(gold["taxonomy_version"]),
                training_snapshot_sha,
                ALGORITHM_VERSION,
                config.EMBEDDING_PROVIDER,
                config.EMBEDDING_MODEL,
                config.EMBEDDING_DIMENSIONS,
                best_alpha,
                score_threshold,
                margin_threshold,
                json.dumps(label_ids),
                json.dumps(model_payload, sort_keys=True),
                json.dumps(report, ensure_ascii=False, sort_keys=True),
                report["status"],
            ),
        )
    report["idempotent"] = False
    _write_report(report, output_path)
    return report


def _load_model(model_id: str) -> tuple[Any, Any, dict[str, Any], np.ndarray, list[str]]:
    with get_conn() as conn:
        model = conn.execute(
            "SELECT * FROM method_family_models WHERE model_id=?", (model_id,)
        ).fetchone()
        if not model:
            raise ValueError(f"Unknown model: {model_id}")
        ruleset = conn.execute(
            "SELECT * FROM method_family_rulesets WHERE ruleset_id=?",
            (str(model["ruleset_id"]),),
        ).fetchone()
    payload = json.loads(str(model["model_json"]))
    labels = [str(value) for value in payload["label_ids"]]
    return model, ruleset, payload, _deserialize_weights(payload["weights"]), labels


def _predict_one(
    *,
    name: str,
    vector: np.ndarray,
    model: Any,
    ruleset: Any,
    weights: np.ndarray,
    label_ids: list[str],
    lexicon: dict[str, dict[str, Any]] | None = None,
    family_thresholds: dict[str, dict[str, float]] | None = None,
    fixed_source_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    rules, eligible = _load_frozen_rules(ruleset)
    rule = match_strict_rule(name, rules=rules, eligible_rule_ids=eligible)
    fixed_allowlist = None if fixed_source_allowlist is None else set(fixed_source_allowlist)
    if rule is not None and (
        fixed_allowlist is None or f"strict_rule:{rule.rule_id}" in fixed_allowlist
    ):
        return {"family_id": rule.family_id, "score": 1.0, "margin": 1.0, "source": "strict_rule", "accepted": True}
    lexical_family = None if rule is not None else _match_lexicon(name, lexicon or {})
    if lexical_family is not None and (
        fixed_allowlist is None or f"lexicon:{lexical_family}" in fixed_allowlist
    ):
        return {
            "family_id": lexical_family,
            "score": 1.0,
            "margin": 1.0,
            "source": "supervised_lexicon",
            "accepted": True,
        }
    prediction = _score(vector, weights, label_ids)
    prediction["source"] = "supervised_embedding"
    if family_thresholds and prediction["family_id"] in family_thresholds:
        threshold = family_thresholds[prediction["family_id"]]
        score_threshold = float(threshold["score"])
        margin_threshold = float(threshold["margin"])
    else:
        score_threshold = float(model["score_threshold"])
        margin_threshold = float(model["margin_threshold"])
    prediction["accepted"] = (
        prediction["score"] >= score_threshold
        and prediction["margin"] >= margin_threshold
    )
    return prediction


def evaluate_blind_submission(
    model_id: str,
    submission_id: str,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    model, ruleset, payload, weights, label_ids = _load_model(model_id)
    with get_conn() as conn:
        submission = conn.execute(
            "SELECT * FROM method_family_blind_submissions WHERE submission_id=?",
            (submission_id,),
        ).fetchone()
        if not submission:
            raise ValueError(f"Unknown blind submission: {submission_id}")
        blind = conn.execute(
            "SELECT * FROM method_family_blind_sets WHERE blind_set_id=?",
            (str(submission["blind_set_id"]),),
        ).fetchone()
        if str(blind["parent_gold_set_id"]) != str(model["parent_gold_set_id"]):
            raise ValueError("Blind set and model use different parent Gold sets")
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT i.blind_rank, i.method_entity_id,
                          i.method_name_snapshot AS method_name,
                          i.paper_count_snapshot AS paper_count,
                          i.context_excerpt_snapshot,
                          l.normalized_primary AS label
                   FROM method_family_blind_items i
                   JOIN method_family_blind_submission_labels l
                     ON l.blind_set_id=i.blind_set_id AND l.blind_rank=i.blind_rank
                   WHERE i.blind_set_id=? ORDER BY i.blind_rank""",
                (str(submission["blind_set_id"]),),
            ).fetchall()
        ]
        existing = conn.execute(
            """SELECT metrics_json FROM method_family_blind_evaluations
               WHERE model_id=? AND submission_id=?""",
            (model_id, submission_id),
        ).fetchone()
    if existing:
        report = json.loads(str(existing["metrics_json"]))
        report["idempotent"] = True
        _write_report(report, output_path)
        return report
    hashes = [hashlib.sha256(str(row["context_excerpt_snapshot"]).encode("utf-8")).hexdigest() for row in rows]
    cached = get_cached_vectors(
        hashes,
        provider=str(model["provider"]),
        model=str(model["embedding_model"]),
        dimensions=int(model["dimensions"]),
        touch=False,
    )
    records: list[dict[str, Any]] = []
    for row, input_hash in zip(rows, hashes):
        vector_record = cached.get(input_hash)
        if vector_record is None:
            raise ValueError(f"Blind row {row['blind_rank']} has no frozen cached embedding")
        vector = np.asarray(vector_record.values, dtype=np.float64)
        vector /= np.linalg.norm(vector)
        prediction = _predict_one(
            name=str(row["method_name"]),
            vector=vector,
            model=model,
            ruleset=ruleset,
            weights=weights,
            label_ids=label_ids,
            lexicon=payload.get("lexicon", {}),
            family_thresholds=payload.get("family_thresholds", {}),
            fixed_source_allowlist=payload.get("fixed_source_allowlist"),
        )
        records.append({**row, "predicted": prediction["family_id"], **prediction})
    metrics = _metrics(records)
    training_ids = set(_payload_training_labels(model, payload))
    training_overlap_ids = sorted(
        int(row["method_entity_id"])
        for row in rows
        if int(row["method_entity_id"]) in training_ids
    )
    supported_families = [
        item for item in metrics["per_predicted_family"].values() if int(item["accepted"]) >= 5
    ]
    gates = {
        "minimum_rows": len(records) >= MIN_BLIND_ROWS,
        "precision": metrics["precision"] is not None and float(metrics["precision"]) >= MIN_BLIND_PRECISION,
        "paper_weighted_precision": metrics["paper_weighted_precision"] is not None
        and float(metrics["paper_weighted_precision"]) >= MIN_BLIND_PAPER_PRECISION,
        "coverage": float(metrics["coverage"]) >= MIN_BLIND_COVERAGE,
        "unknown_false_accepts_zero": int(metrics["unknown_false_accepts"]) == 0,
        "supported_family_precision": all(float(item["precision"]) >= 0.85 for item in supported_families),
        "independent_training_overlap_zero": not training_overlap_ids,
    }
    status = "blind_validated" if all(gates.values()) else "blind_rejected"
    evaluation_id = "eval-" + _json_hash(
        {"model_id": model_id, "submission_id": submission_id, "metrics": metrics}
    )[:24]
    report = {
        "evaluation_id": evaluation_id,
        "model_id": model_id,
        "submission_id": submission_id,
        "blind_set_id": str(submission["blind_set_id"]),
        "status": status,
        "release_build_eligible": status == "blind_validated",
        "thresholds": {
            "score": float(model["score_threshold"]),
            "margin": float(model["margin_threshold"]),
            "strategy": payload.get("threshold_strategy", "global"),
            "families": payload.get("family_thresholds", {}),
        },
        "metrics": metrics,
        "gates": gates,
        "safety": {
            "blind_labels_used_for_training": bool(training_overlap_ids),
            "training_overlap_count": len(training_overlap_ids),
            "training_overlap_sample": training_overlap_ids[:20],
            "accepted_assignments_written": 0,
        },
        "idempotent": False,
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_blind_evaluations
               (evaluation_id, model_id, submission_id, metrics_json, status)
               VALUES (?, ?, ?, ?, ?)""",
            (evaluation_id, model_id, submission_id, json.dumps(report, ensure_ascii=False, sort_keys=True), status),
        )
    _write_report(report, output_path)
    return report


def build_release(
    model_id: str,
    evaluation_id: str,
    *,
    manual_override: bool = False,
    approved_by: str | None = None,
    approval_reason: str | None = None,
    minimum_paper_coverage: float = MIN_RELEASE_PAPER_COVERAGE,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    if not 0 < float(minimum_paper_coverage) <= 1:
        raise ValueError("minimum_paper_coverage must be in (0, 1]")
    approved_by = (approved_by or "").strip()
    approval_reason = (approval_reason or "").strip()
    if manual_override and (not approved_by or not approval_reason):
        raise ValueError("Manual override requires approved_by and approval_reason")
    if not manual_override and float(minimum_paper_coverage) != MIN_RELEASE_PAPER_COVERAGE:
        raise ValueError("A non-default coverage threshold requires manual_override")
    model, ruleset, payload, weights, label_ids = _load_model(model_id)
    with get_conn() as conn:
        evaluation = conn.execute(
            "SELECT * FROM method_family_blind_evaluations WHERE evaluation_id=?",
            (evaluation_id,),
        ).fetchone()
        if not evaluation or str(evaluation["model_id"]) != model_id:
            raise ValueError("Blind evaluation is missing or belongs to another model")
        if str(evaluation["status"]) != "blind_validated" and not manual_override:
            raise ValueError("Blind evaluation has not passed the release gate")
        relations = [
            dict(row)
            for row in conn.execute(
                """SELECT id, object_id, COALESCE(source_pmid, '') AS source_pmid
                   FROM relations WHERE relation='APPLIES_METHOD'
                     AND object_type='Method' AND COALESCE(status, 'active')='active'
                   ORDER BY object_id, source_pmid, id"""
            ).fetchall()
        ]
        names = {
            int(row["id"]): str(row["name"])
            for row in conn.execute(
                """SELECT id, name FROM entities WHERE type='Method' AND EXISTS (
                       SELECT 1 FROM relations r WHERE r.object_id=entities.id
                         AND r.object_type='Method' AND r.relation='APPLIES_METHOD'
                         AND COALESCE(r.status, 'active')='active')"""
            ).fetchall()
        }
    graph_sha = _json_hash([(int(row["object_id"]), str(row["source_pmid"])) for row in relations])
    release_key = {"model_id": model_id, "evaluation_id": evaluation_id, "graph_snapshot_sha256": graph_sha}
    if manual_override:
        release_key["manual_override"] = {
            "approved_by": approved_by,
            "approval_reason": approval_reason,
            "minimum_paper_coverage": float(minimum_paper_coverage),
        }
    release_id = "release-" + _json_hash(release_key)[:24]
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT metrics_json FROM method_family_releases WHERE release_id=?", (release_id,)
        ).fetchone()
    if existing:
        report = json.loads(str(existing["metrics_json"]))
        report["idempotent"] = True
        _write_report(report, output_path)
        return report
    training = _payload_training_labels(model, payload)
    vectors = _vectors_for_ids(names)
    assignments: list[dict[str, Any]] = []
    for method_id, name in names.items():
        training_label = training.get(method_id)
        if training_label is not None:
            if training_label != "unknown":
                assignments.append({"method_entity_id": method_id, "family_id": training_label, "source": "expert_gold", "score": 1.0, "margin": 1.0})
            continue
        vector = vectors.get(method_id)
        if vector is None:
            continue
        prediction = _predict_one(
            name=name,
            vector=vector,
            model=model,
            ruleset=ruleset,
            weights=weights,
            label_ids=label_ids,
            lexicon=payload.get("lexicon", {}),
            family_thresholds=payload.get("family_thresholds", {}),
            fixed_source_allowlist=payload.get("fixed_source_allowlist"),
        )
        if prediction["accepted"]:
            assignments.append({"method_entity_id": method_id, "family_id": prediction["family_id"], "source": prediction["source"], "score": prediction["score"], "margin": prediction["margin"]})
    assigned_ids = {int(row["method_entity_id"]) for row in assignments}
    all_pmids = {str(row["source_pmid"]) for row in relations if str(row["source_pmid"])}
    covered_pmids = {str(row["source_pmid"]) for row in relations if str(row["source_pmid"]) and int(row["object_id"]) in assigned_ids}
    covered_relations = sum(int(row["object_id"]) in assigned_ids for row in relations)
    coverage = {
        "entity": round(len(assigned_ids) / len(names), 6) if names else 0.0,
        "relation": round(covered_relations / len(relations), 6) if relations else 0.0,
        "paper": round(len(covered_pmids) / len(all_pmids), 6) if all_pmids else 0.0,
        "minimum_paper": float(minimum_paper_coverage),
    }
    model_metrics = json.loads(str(model["metrics_json"]))
    diagnostic = model_metrics.get("cross_validation", {}).get("gated", {})
    supported_families = [
        item
        for item in diagnostic.get("per_predicted_family", {}).values()
        if int(item.get("accepted", 0)) >= 5
    ]
    diagnostic_gates = {
        "precision": diagnostic.get("precision") is not None
        and float(diagnostic["precision"]) >= MIN_BLIND_PRECISION,
        "paper_weighted_precision": diagnostic.get("paper_weighted_precision") is not None
        and float(diagnostic["paper_weighted_precision"]) >= MIN_BLIND_PAPER_PRECISION,
        "unknown_false_accepts_zero": int(diagnostic.get("unknown_false_accepts", -1)) == 0,
        "supported_family_precision": all(
            float(item.get("precision", 0.0)) >= 0.85 for item in supported_families
        ),
    }
    release_gates = {
        "blind_evaluation": str(evaluation["status"]) == "blind_validated",
        "paper_coverage": coverage["paper"] >= float(minimum_paper_coverage),
        **{f"diagnostic_{key}": value for key, value in diagnostic_gates.items()},
    }
    if manual_override:
        eligible = release_gates["paper_coverage"] and all(diagnostic_gates.values())
        status = "release_validated_override" if eligible else "release_rejected"
    else:
        eligible = all(release_gates.values())
        status = "release_validated" if eligible else "release_rejected"
    assignment_sha = _json_hash(sorted(assignments, key=lambda row: row["method_entity_id"]))
    report = {
        "release_id": release_id,
        "model_id": model_id,
        "evaluation_id": evaluation_id,
        "status": status,
        "activation_eligible": status in {"release_validated", "release_validated_override"},
        "graph_snapshot_sha256": graph_sha,
        "assignment_snapshot_sha256": assignment_sha,
        "counts": {
            "active_methods": len(names),
            "assigned_methods": len(assignments),
            "unknown_methods": len(names) - len(assignments),
        },
        "source_counts": dict(Counter(str(row["source"]) for row in assignments)),
        "family_counts": dict(Counter(str(row["family_id"]) for row in assignments)),
        "coverage": coverage,
        "gates": release_gates,
        "approval": {
            "mode": "manual_override" if manual_override else "strict",
            "approved_by": approved_by or None,
            "reason": approval_reason or None,
            "waived_gates": (
                [
                    "independent_blind_evaluation",
                    f"default_minimum_paper_coverage:{MIN_RELEASE_PAPER_COVERAGE}",
                ]
                if manual_override
                else []
            ),
        },
        "idempotent": False,
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_releases
               (release_id, model_id, evaluation_id, taxonomy_version,
                graph_snapshot_sha256, assignment_snapshot_sha256,
                metrics_json, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (release_id, model_id, evaluation_id, str(model["taxonomy_version"]), graph_sha, assignment_sha, json.dumps(report, ensure_ascii=False, sort_keys=True), status),
        )
        conn.executemany(
            """INSERT INTO method_family_release_assignments
               (release_id, method_entity_id, family_id, source, score, margin)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(release_id, row["method_entity_id"], row["family_id"], row["source"], row["score"], row["margin"]) for row in assignments],
        )
    _write_report(report, output_path)
    return report


def preview_production_coverage(model_id: str) -> dict[str, Any]:
    """Read-only production coverage preview; it cannot create or activate a release."""
    model, ruleset, payload, weights, label_ids = _load_model(model_id)
    with get_conn() as conn:
        relations = [
            dict(row)
            for row in conn.execute(
                """SELECT id, object_id, COALESCE(source_pmid, '') AS source_pmid
                   FROM relations WHERE relation='APPLIES_METHOD'
                     AND object_type='Method' AND COALESCE(status, 'active')='active'"""
            ).fetchall()
        ]
        names = {
            int(row["id"]): str(row["name"])
            for row in conn.execute(
                """SELECT id, name FROM entities WHERE type='Method' AND EXISTS (
                       SELECT 1 FROM relations r WHERE r.object_id=entities.id
                         AND r.object_type='Method' AND r.relation='APPLIES_METHOD'
                         AND COALESCE(r.status, 'active')='active')"""
            ).fetchall()
        }
    training = _payload_training_labels(model, payload)
    vectors = _vectors_for_ids(names)
    assigned: dict[int, str] = {}
    sources: Counter[str] = Counter()
    for method_id, name in names.items():
        label = training.get(method_id)
        if label is not None:
            if label != "unknown":
                assigned[method_id] = label
                sources["expert_gold"] += 1
            continue
        vector = vectors.get(method_id)
        if vector is None:
            continue
        prediction = _predict_one(
            name=name,
            vector=vector,
            model=model,
            ruleset=ruleset,
            weights=weights,
            label_ids=label_ids,
            lexicon=payload.get("lexicon", {}),
            family_thresholds=payload.get("family_thresholds", {}),
            fixed_source_allowlist=payload.get("fixed_source_allowlist"),
        )
        if prediction["accepted"]:
            assigned[method_id] = str(prediction["family_id"])
            sources[str(prediction["source"])] += 1
    all_pmids = {str(row["source_pmid"]) for row in relations if str(row["source_pmid"])}
    covered_pmids = {
        str(row["source_pmid"])
        for row in relations
        if str(row["source_pmid"]) and int(row["object_id"]) in assigned
    }
    return {
        "model_id": model_id,
        "status": "preview_only_awaiting_blind_gate",
        "accepted_assignments_written": 0,
        "active_release_created": False,
        "counts": {
            "active_methods": len(names),
            "assigned_methods": len(assigned),
            "unknown_methods": len(names) - len(assigned),
        },
        "source_counts": dict(sources),
        "family_counts": dict(Counter(assigned.values())),
        "paper_coverage": round(len(covered_pmids) / len(all_pmids), 6) if all_pmids else 0.0,
        "required_paper_coverage": MIN_RELEASE_PAPER_COVERAGE,
    }


def activate_release(release_id: str, *, activated_by: str) -> dict[str, Any]:
    activated_by = activated_by.strip()
    if not activated_by:
        raise ValueError("activated_by is required")
    with get_conn() as conn:
        release = conn.execute(
            "SELECT * FROM method_family_releases WHERE release_id=?", (release_id,)
        ).fetchone()
        if not release:
            raise ValueError(f"Unknown release: {release_id}")
        if str(release["status"]) not in {"release_validated", "release_validated_override"}:
            raise ValueError("Only a validated strict or manual-override release can be activated")
        existing = conn.execute(
            "SELECT activation_id, activated_at FROM method_family_release_activations WHERE release_id=?",
            (release_id,),
        ).fetchone()
        if existing:
            return {"release_id": release_id, "status": "active", "idempotent": True, "activation_id": int(existing["activation_id"]), "activated_at": str(existing["activated_at"])}
        cursor = conn.execute(
            "INSERT INTO method_family_release_activations (release_id, activated_by) VALUES (?, ?)",
            (release_id, activated_by),
        )
        activation_id = int(cursor.lastrowid)
    return {"release_id": release_id, "status": "active", "idempotent": False, "activation_id": activation_id}


def load_active_method_family_map() -> tuple[str | None, dict[int, str]]:
    """Return latest append-only activation and its method-to-family map."""
    with get_conn() as conn:
        active = conn.execute(
            """SELECT release_id FROM method_family_release_activations
               ORDER BY activation_id DESC LIMIT 1"""
        ).fetchone()
        if not active:
            return None, {}
        release_id = str(active["release_id"])
        mapping = {
            int(row["method_entity_id"]): str(row["family_id"])
            for row in conn.execute(
                """SELECT method_entity_id, family_id
                   FROM method_family_release_assignments WHERE release_id=?""",
                (release_id,),
            ).fetchall()
        }
    return release_id, mapping


def load_active_method_family_name_map() -> tuple[str | None, dict[str, str]]:
    """Resolve an active release to canonical Method names by paper-weighted vote."""
    release_id, by_id = load_active_method_family_map()
    if not release_id:
        return None, {}
    from analysis.method_synonyms import resolve_method_canonical

    with get_conn() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT e.id, e.name,
                          COUNT(DISTINCT NULLIF(r.source_pmid, '')) AS paper_count
                   FROM entities e
                   LEFT JOIN relations r ON r.object_id=e.id
                    AND r.object_type='Method' AND r.relation='APPLIES_METHOD'
                    AND COALESCE(r.status, 'active')='active'
                   WHERE e.type='Method'
                   GROUP BY e.id, e.name"""
            ).fetchall()
        ]
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        method_id = int(row["id"])
        family = by_id.get(method_id)
        if not family:
            continue
        canonical = resolve_method_canonical(str(row["name"]))
        votes[canonical][family] += max(1, int(row["paper_count"] or 0))
    return release_id, {
        name: max(families, key=lambda family: (families[family], family))
        for name, families in votes.items()
    }
