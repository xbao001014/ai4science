"""Strict name rules and an offline Method-family policy preview.

This module is deliberately read-only with respect to ``method_family_assignments``.
It freezes auditable evaluation artifacts while the Phase C release builder remains
disabled.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import config
from db.schema import get_conn


RULESET_VERSION = "method-family-rules-v3"
DEFAULT_MIN_CALIBRATION_MATCHES = 2
DEFAULT_MIN_CALIBRATION_PRECISION = 0.95
DEFAULT_MIN_HOLDOUT_PRECISION = 0.90
DEFAULT_MIN_GLOBAL_HOLDOUT_PRECISION = 0.95
DEFAULT_MIN_PAPER_COVERAGE = 0.80


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    family_id: str
    patterns: tuple[str, ...]
    excludes: tuple[str, ...] = ()
    priority: int = 0
    rationale: str = ""


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    family_id: str
    priority: int


STRICT_RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition(
        "combo_transmil",
        "mil",
        (r"\btrans[- ]?mil\b",),
        priority=120,
        rationale="TransMIL is a named multiple-instance architecture.",
    ),
    RuleDefinition(
        "combo_transunet",
        "transformer",
        (r"\btrans[- ]?u[- ]?net\b",),
        priority=120,
        rationale="TransUNet is treated as the named Transformer architecture.",
    ),
    RuleDefinition(
        "representation_dino",
        "representation_learning",
        (r"\bdino(?:v2)?\b",),
        priority=110,
        rationale="DINO/DINOv2 explicitly denotes self-supervised representation learning.",
    ),
    RuleDefinition(
        "mil_named",
        "mil",
        (
            r"\bmultiple[- ]instance learning\b",
            r"\bmulti[- ]instance learning\b",
            r"\bmultiple[- ]instance\b",
            r"\b(?:abmil|clam(?:[- ](?:sb|mb))?|dsmil)\b",
            r"\battention[- ]based mil\b",
            r"\bweakly[- ]supervised\b.*\bvit\b",
            r"\bmil\b",
        ),
        excludes=(r"\bmilieu\b",),
        priority=100,
        rationale="Only explicit MIL terminology and named MIL architectures.",
    ),
    RuleDefinition(
        "multimodal_architecture",
        "multimodal_fusion",
        (r"\bmulti[- ]?modal\b.*\btransformer\b",),
        priority=100,
        rationale="Explicit multimodal Transformer names describe the fusion family.",
    ),
    RuleDefinition(
        "generative_strict",
        "generative_model",
        (
            r"\bgenerative adversarial network(?:s)?\b",
            r"\bcycle[- ]?gan\b",
            r"\bdiffusion model(?:s)?\b",
            r"\bvariational autoencoder(?:s)?\b",
            r"\bvae(?:s)?\b",
            r"\bvirtual staining\b",
            r"\bmcs[- ]?stain(?:ing)?\b",
        ),
        excludes=(r"\bgenerative ai\b",),
        priority=90,
        rationale="Concrete generative architectures only; generic generative AI is excluded.",
    ),
    RuleDefinition(
        "foundation_exact",
        "foundation_model",
        (
            r"\buni(?:-v2)?\b",
            r"\bconch\b",
            r"\b(?:prov[- ]?)?gigapath\b",
            r"\bvirchow(?:2)?\b",
            r"\bchief\b",
            r"\bctranspath\b",
        ),
        priority=85,
        rationale="Allowlisted names of pathology foundation models.",
    ),
    RuleDefinition(
        "explainability_named",
        "explainability",
        (
            r"\bshap\b",
            r"\blime\b",
            r"\bgrad[- ]?cam(?:\+\+)?\b",
            r"\bscore[- ]?cam\b",
            r"\bintegrated gradients?\b",
            r"\blayer[- ]wise relevance propagation\b",
            r"\bpermutation importance\b",
        ),
        priority=50,
        rationale="Named post-hoc explainability methods.",
    ),
    RuleDefinition(
        "tooling_named",
        "other_tooling",
        (
            r"\bqupath\b",
            r"\bimagej\b",
            r"\bvosviewer\b",
            r"\bcitespace\b",
            r"\bbibliometrix\b",
            r"\bcellprofiler\b",
            r"\bhalo\b",
            r"\bolink\b",
        ),
        priority=80,
        rationale="Allowlisted software tools and analysis platforms.",
    ),
    RuleDefinition(
        "classical_named",
        "classical_statistics",
        (
            r"\brandom forest(?:s)?\b",
            r"\bsupport vector machine(?:s)?\b",
            r"\bsvm\b",
            r"\blogistic regression\b",
            r"\bcox(?: proportional hazards?)?(?: regression)?\b",
            r"\blasso\b",
            r"\bxgboost\b",
            r"\blightgbm\b",
            r"\bcatboost\b",
            r"\bk[- ]?means\b",
            r"\bk[- ]?nearest neighbou?rs?\b",
            r"\bknn\b",
            r"\bprincipal component analysis\b",
            r"\bpca\b",
            r"\belastic net\b",
            r"\bkaplan[- ]meier\b",
            r"\bnaive bayes\b",
        ),
        priority=80,
        rationale="Named classical statistical or machine-learning methods.",
    ),
    RuleDefinition(
        "cnn_named",
        "cnn",
        (
            r"\bconvolutional neural network(?:s)?\b",
            r"\bcnn(?:s)?\b",
            r"\bresnet(?:18|34|50|101|152)?\b",
            r"\bdensenet(?:121|169|201)?\b",
            r"\befficientnet(?:[- ]?b[0-9])?\b",
            r"\bmobilenet(?:v[23])?\b",
            r"\bvgg(?:16|19)?\b",
            r"\bxception\b",
            r"\bu[- ]?net(?:\+\+)?\b",
            r"\bdeeplab(?:v3\+?)?\b",
            r"\bconvnext\b",
            r"\byolo(?:v[0-9]+)?\b",
            r"\bhover[- ]?net\b",
        ),
        priority=70,
        rationale="Explicit convolutional family or architecture names.",
    ),
    RuleDefinition(
        "transformer_named",
        "transformer",
        (
            r"\bvision transformer(?:s)?\b",
            r"\btransformer(?:s)?\b",
            r"\bvit\b",
            r"\bswin(?:[- ]transformer)?\b",
            r"\bbeit\b",
            r"\bdeit\b",
        ),
        excludes=(r"\battention mechanism\b", r"\bspatial transformer\b"),
        priority=75,
        rationale="Explicit Transformer family or architecture names.",
    ),
    RuleDefinition(
        "gnn_named",
        "graph_neural_network",
        (
            r"\bgraph neural network(?:s)?\b",
            r"\bgraph convolutional neural network(?:s)?\b",
            r"\bgraph convolutional network(?:s)?\b",
            r"\bgraph attention network(?:s)?\b",
            r"\bmessage[- ]passing neural network(?:s)?\b",
            r"\bgnn(?:s)?\b",
            r"\bgcn(?:s)?\b",
            r"\bgat(?:s)?\b",
        ),
        priority=75,
        rationale="Explicit graph-neural-network terminology.",
    ),
    RuleDefinition(
        "representation_named",
        "representation_learning",
        (
            r"\bself[- ]supervised learning\b",
            r"\bself[- ]supervised\b",
            r"\bcontrastive learning\b",
            r"\bmetric learning\b",
            r"\bknowledge distillation\b",
            r"\bsimclr\b",
            r"\bmoco(?:v[23])?\b",
        ),
        priority=80,
        rationale="Explicit representation-learning objectives or named frameworks.",
    ),
    RuleDefinition(
        "bioinformatics_named",
        "bioinformatics_omics",
        (
            r"\bgene set enrichment analysis\b",
            r"\bgsea\b",
            r"\bweighted gene co[- ]expression network analysis\b",
            r"\bwgcna\b",
            r"\bcibersort(?:x)?\b",
            r"\brna[- ]seq(?:uencing)?\b",
            r"\bsingle[- ]cell rna(?: sequencing)?\b",
            r"\bspatial transcriptomics?\b",
            r"\bmulti[- ]omics?\b",
            r"\bproteomics?\b",
        ),
        excludes=(
            r"\b(?:rt[- ]?)?q[- ]?pcr\b",
            r"\bimmunohistochemistry\b",
            r"\bihc\b",
            r"\bplatform\b",
        ),
        priority=60,
        rationale="Explicit computational omics analyses; wet-lab assays are excluded.",
    ),
    RuleDefinition(
        "image_processing_strict",
        "image_processing",
        (
            r"\bstain normalization\b",
            r"\bcolor deconvolution\b",
            r"\bimage registration\b",
            r"\bmorphological image processing\b",
            r"\botsu(?:'s)?(?: thresholding)?\b",
            r"\bhandcrafted radiomics?\b",
            r"\bradiomic features?\b",
        ),
        excludes=(r"\bvirtual staining\b",),
        priority=60,
        rationale="Concrete non-model image processing operations.",
    ),
    RuleDefinition(
        "multimodal_strict",
        "multimodal_fusion",
        (
            r"\bmulti[- ]?modal feature fusion\b",
            r"\bcross[- ]modal attention\b",
            r"\bpathology[- ]genomic fusion\b",
            r"\bpathology genomics fusion\b",
        ),
        priority=60,
        rationale="Explicit cross-modal fusion operations only.",
    ),
)


def _normalized_name(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("–", "-").replace("—", "-").split())


def match_strict_rule(
    method_name: str,
    *,
    rules: Sequence[RuleDefinition] = STRICT_RULES,
    eligible_rule_ids: Iterable[str] | None = None,
) -> RuleMatch | None:
    """Return one unambiguous highest-priority name-rule match."""
    name = _normalized_name(method_name)
    eligible = set(eligible_rule_ids) if eligible_rule_ids is not None else None
    matches: list[RuleMatch] = []
    for rule in rules:
        if any(re.search(pattern, name, flags=re.IGNORECASE) for pattern in rule.excludes):
            continue
        if any(re.search(pattern, name, flags=re.IGNORECASE) for pattern in rule.patterns):
            matches.append(RuleMatch(rule.rule_id, rule.family_id, rule.priority))
    if not matches:
        return None
    top_priority = max(match.priority for match in matches)
    top = [match for match in matches if match.priority == top_priority]
    if len({match.family_id for match in top}) != 1:
        return None
    selected = sorted(top, key=lambda match: match.rule_id)[0]
    # An unapproved high-priority rule blocks lower-priority fallback. Otherwise,
    # e.g. an unapproved multimodal rule could silently become plain Transformer.
    if eligible is not None and selected.rule_id not in eligible:
        return None
    return selected


def _rules_payload(rules: Sequence[RuleDefinition]) -> list[dict[str, Any]]:
    return [asdict(rule) for rule in rules]


def _json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _write_report(report: dict[str, Any], output_path: str | Path | None) -> None:
    if not output_path:
        return
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _evaluate_rule_rows(
    rows: Sequence[dict[str, Any]],
    *,
    rules: Sequence[RuleDefinition],
    eligible_rule_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    eligible = None if eligible_rule_ids is None else set(eligible_rule_ids)
    records: list[tuple[dict[str, Any], RuleMatch]] = []
    per_rule_records: dict[str, list[tuple[dict[str, Any], RuleMatch]]] = {}
    for row in rows:
        match = match_strict_rule(
            str(row["method_name_snapshot"]), rules=rules, eligible_rule_ids=eligible
        )
        if match is None:
            continue
        records.append((row, match))
        per_rule_records.setdefault(match.rule_id, []).append((row, match))

    correct = sum(
        str(row["normalized_primary"]) != "unknown"
        and str(row["normalized_primary"]) == match.family_id
        for row, match in records
    )
    known_rows = sum(str(row["normalized_primary"]) != "unknown" for row in rows)
    accepted_papers = sum(int(row["paper_count_snapshot"]) for row, _ in records)
    correct_papers = sum(
        int(row["paper_count_snapshot"])
        for row, match in records
        if str(row["normalized_primary"]) != "unknown"
        and str(row["normalized_primary"]) == match.family_id
    )
    per_rule: dict[str, dict[str, Any]] = {}
    for rule in rules:
        matched = per_rule_records.get(rule.rule_id, [])
        rule_correct = sum(
            str(row["normalized_primary"]) != "unknown"
            and str(row["normalized_primary"]) == match.family_id
            for row, match in matched
        )
        per_rule[rule.rule_id] = {
            "family_id": rule.family_id,
            "matches": len(matched),
            "correct": rule_correct,
            "precision": round(rule_correct / len(matched), 6) if matched else None,
            "unknown_false_accepts": sum(
                str(row["normalized_primary"]) == "unknown" for row, _ in matched
            ),
        }
    return {
        "rows": len(rows),
        "known_rows": known_rows,
        "matched": len(records),
        "correct": correct,
        "unknown_false_accepts": sum(
            str(row["normalized_primary"]) == "unknown" for row, _ in records
        ),
        "coverage": round(len(records) / len(rows), 6) if rows else 0.0,
        "known_recall": round(correct / known_rows, 6) if known_rows else None,
        "precision": round(correct / len(records), 6) if records else None,
        "paper_weighted_precision": round(correct_papers / accepted_papers, 6)
        if accepted_papers
        else None,
        "per_rule": per_rule,
    }


def evaluate_and_freeze_ruleset(
    gold_set_id: str,
    *,
    output_path: str | Path | None = None,
    rules: Sequence[RuleDefinition] = STRICT_RULES,
    min_calibration_matches: int = DEFAULT_MIN_CALIBRATION_MATCHES,
    min_calibration_precision: float = DEFAULT_MIN_CALIBRATION_PRECISION,
    min_holdout_precision: float = DEFAULT_MIN_HOLDOUT_PRECISION,
    min_global_holdout_precision: float = DEFAULT_MIN_GLOBAL_HOLDOUT_PRECISION,
) -> dict[str, Any]:
    """Select rules on calibration, gate once on holdout, and freeze the report."""
    rules_payload = _rules_payload(rules)
    rules_envelope = {
        "ruleset_version": RULESET_VERSION,
        "matching_policy": "highest_priority_unapproved_blocks_fallback_v1",
        "rules": rules_payload,
        "gates": {
            "min_calibration_matches": min_calibration_matches,
            "min_calibration_precision": min_calibration_precision,
            "min_holdout_precision": min_holdout_precision,
            "min_global_holdout_precision": min_global_holdout_precision,
        },
    }
    rules_sha256 = _json_hash(rules_envelope)
    ruleset_id = "rules-" + _json_hash(
        {"gold_set_id": gold_set_id, "rules_sha256": rules_sha256}
    )[:24]
    with get_conn() as conn:
        gold = conn.execute(
            "SELECT * FROM method_family_gold_sets WHERE gold_set_id=?", (gold_set_id,)
        ).fetchone()
        if not gold:
            raise ValueError(f"Unknown Gold set: {gold_set_id}")
        existing = conn.execute(
            "SELECT metrics_json FROM method_family_rulesets WHERE ruleset_id=?", (ruleset_id,)
        ).fetchone()
        if existing:
            report = json.loads(str(existing["metrics_json"]))
            report["idempotent"] = True
            _write_report(report, output_path)
            return report
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT method_entity_id, method_name_snapshot, normalized_primary,
                          paper_count_snapshot, split
                   FROM method_family_gold_labels
                   WHERE gold_set_id=? ORDER BY method_entity_id""",
                (gold_set_id,),
            ).fetchall()
        ]

    calibration_rows = [row for row in rows if row["split"] == "calibration"]
    holdout_rows = [row for row in rows if row["split"] == "holdout"]
    calibration_all = _evaluate_rule_rows(calibration_rows, rules=rules)
    calibration_candidates = {
        rule_id
        for rule_id, metrics in calibration_all["per_rule"].items()
        if int(metrics["matches"]) >= min_calibration_matches
        and metrics["precision"] is not None
        and float(metrics["precision"]) >= min_calibration_precision
    }
    holdout_candidate = _evaluate_rule_rows(
        holdout_rows, rules=rules, eligible_rule_ids=calibration_candidates
    )
    eligible_rule_ids: list[str] = []
    rule_gate: dict[str, dict[str, Any]] = {}
    for rule in rules:
        calibration_metrics = calibration_all["per_rule"][rule.rule_id]
        holdout_metrics = holdout_candidate["per_rule"][rule.rule_id]
        if rule.rule_id not in calibration_candidates:
            decision = "failed_calibration_support_or_precision"
        elif int(holdout_metrics["matches"]) > 0 and (
            holdout_metrics["precision"] is None
            or float(holdout_metrics["precision"]) < min_holdout_precision
        ):
            decision = "failed_holdout_precision"
        else:
            decision = "eligible"
            eligible_rule_ids.append(rule.rule_id)
        rule_gate[rule.rule_id] = {
            "family_id": rule.family_id,
            "decision": decision,
            "calibration_matches": calibration_metrics["matches"],
            "calibration_precision": calibration_metrics["precision"],
            "holdout_matches": holdout_metrics["matches"],
            "holdout_precision": holdout_metrics["precision"],
        }

    calibration_final = _evaluate_rule_rows(
        calibration_rows, rules=rules, eligible_rule_ids=eligible_rule_ids
    )
    holdout_final = _evaluate_rule_rows(
        holdout_rows, rules=rules, eligible_rule_ids=eligible_rule_ids
    )
    gates = {
        "nonempty_rule_allowlist": bool(eligible_rule_ids),
        "calibration_precision": calibration_final["precision"] is not None
        and float(calibration_final["precision"]) >= min_calibration_precision,
        "holdout_precision": holdout_final["precision"] is not None
        and float(holdout_final["precision"]) >= min_global_holdout_precision,
        "holdout_unknown_false_accepts_zero": holdout_final["unknown_false_accepts"] == 0,
    }
    status = "rules_validated" if all(gates.values()) else "rules_rejected"
    report = {
        "ruleset_id": ruleset_id,
        "gold_set_id": gold_set_id,
        "gold_file_sha256": str(gold["file_sha256"]),
        "split_manifest_sha256": str(gold["split_manifest_sha256"]),
        "taxonomy_version": str(gold["taxonomy_version"]),
        "ruleset_version": RULESET_VERSION,
        "rules_sha256": rules_sha256,
        "status": status,
        "release_build_eligible": False,
        "release_blocker": "Production coverage is evaluated separately; accepted writes remain disabled",
        "idempotent": False,
        "thresholds": rules_envelope["gates"],
        "rule_count": len(rules),
        "eligible_rule_ids": eligible_rule_ids,
        "split_counts": {"calibration": len(calibration_rows), "holdout": len(holdout_rows)},
        "calibration_all_rules": calibration_all,
        "holdout_calibration_candidates": holdout_candidate,
        "rule_gate": rule_gate,
        "calibration_final_allowlist": calibration_final,
        "holdout_final_allowlist": holdout_final,
        "gates": gates,
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_rulesets
               (ruleset_id, gold_set_id, taxonomy_version, ruleset_version,
                rules_sha256, rules_json, eligible_rule_ids_json, metrics_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ruleset_id,
                gold_set_id,
                str(gold["taxonomy_version"]),
                RULESET_VERSION,
                rules_sha256,
                json.dumps(rules_payload, ensure_ascii=False, sort_keys=True),
                json.dumps(eligible_rule_ids, sort_keys=True),
                json.dumps(report, ensure_ascii=False, sort_keys=True),
                status,
            ),
        )
    _write_report(report, output_path)
    return report


def _load_frozen_rules(row: Any) -> tuple[tuple[RuleDefinition, ...], set[str]]:
    rules = tuple(
        RuleDefinition(
            rule_id=str(item["rule_id"]),
            family_id=str(item["family_id"]),
            patterns=tuple(item["patterns"]),
            excludes=tuple(item.get("excludes", ())),
            priority=int(item["priority"]),
            rationale=str(item.get("rationale", "")),
        )
        for item in json.loads(str(row["rules_json"]))
    )
    return rules, set(json.loads(str(row["eligible_rule_ids_json"])))


def build_policy_preview(
    gold_set_id: str,
    calibration_id: str,
    ruleset_id: str,
    *,
    output_path: str | Path | None = None,
    min_paper_coverage: float = DEFAULT_MIN_PAPER_COVERAGE,
) -> dict[str, Any]:
    """Preview Gold > strict rule > calibrated embedding without accepting rows."""
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
        if not calibration:
            raise ValueError(f"Unknown calibration: {calibration_id}")
        if not ruleset:
            raise ValueError(f"Unknown ruleset: {ruleset_id}")
        if str(calibration["gold_set_id"]) != gold_set_id:
            raise ValueError("Calibration belongs to a different Gold set")
        if str(ruleset["gold_set_id"]) != gold_set_id:
            raise ValueError("Ruleset belongs to a different Gold set")
        if str(calibration["status"]) != "threshold_validated":
            raise ValueError("Calibration has not passed its threshold gate")
        if str(ruleset["status"]) != "rules_validated":
            raise ValueError("Ruleset has not passed its validation gate")

        gold_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT method_entity_id, normalized_primary, secondary_json
                   FROM method_family_gold_labels WHERE gold_set_id=?""",
                (gold_set_id,),
            ).fetchall()
        ]
        entity_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT e.id, e.name
                   FROM entities e
                   WHERE e.type='Method' AND EXISTS (
                       SELECT 1 FROM relations r WHERE r.object_id=e.id
                         AND r.object_type='Method' AND r.relation='APPLIES_METHOD'
                         AND COALESCE(r.status, 'active')='active'
                   ) ORDER BY e.id"""
            ).fetchall()
        ]
        relation_rows = [
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
                """SELECT method_entity_id, family_id, confidence, margin
                   FROM method_family_assignments
                   WHERE taxonomy_version=? AND candidate_rank=1
                     AND is_primary=1 AND status='review'""",
                (str(gold["taxonomy_version"]),),
            ).fetchall()
        ]
        accepted_before = int(
            conn.execute(
                "SELECT COUNT(*) FROM method_family_assignments WHERE status='accepted'"
            ).fetchone()[0]
        )
    graph_snapshot_sha256 = _json_hash(
        [(int(row["object_id"]), str(row["source_pmid"])) for row in relation_rows]
    )
    preview_id = "preview-" + _json_hash(
        {
            "gold_set_id": gold_set_id,
            "calibration_id": calibration_id,
            "ruleset_id": ruleset_id,
            "graph_snapshot_sha256": graph_snapshot_sha256,
            "min_paper_coverage": min_paper_coverage,
        }
    )[:24]
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT metrics_json FROM method_family_policy_previews WHERE preview_id=?",
            (preview_id,),
        ).fetchone()
    if existing:
        report = json.loads(str(existing["metrics_json"]))
        report["idempotent"] = True
        _write_report(report, output_path)
        return report

    calibration_metrics = json.loads(str(calibration["metrics_json"]))
    thresholds = json.loads(str(calibration["thresholds_json"]))
    embedding_allowlist = set(json.loads(str(calibration["embedding_family_allowlist_json"])))
    frozen_rules, eligible_rule_ids = _load_frozen_rules(ruleset)
    gold_by_id = {int(row["method_entity_id"]): row for row in gold_rows}
    embedding_by_id = {int(row["method_entity_id"]): row for row in embedding_rows}

    assignments: dict[int, dict[str, Any]] = {}
    source_counts: Counter[str] = Counter()
    primary_family_counts: Counter[str] = Counter()
    all_family_counts: Counter[str] = Counter()
    gold_unknown_blocked = 0
    for entity in entity_rows:
        method_id = int(entity["id"])
        gold_row = gold_by_id.get(method_id)
        if gold_row is not None:
            primary = str(gold_row["normalized_primary"])
            if primary == "unknown":
                gold_unknown_blocked += 1
                continue
            secondary = tuple(json.loads(str(gold_row["secondary_json"])))
            assignments[method_id] = {
                "primary": primary,
                "secondary": secondary,
                "source": "gold",
            }
        else:
            rule_match = match_strict_rule(
                str(entity["name"]),
                rules=frozen_rules,
                eligible_rule_ids=eligible_rule_ids,
            )
            if rule_match is not None:
                assignments[method_id] = {
                    "primary": rule_match.family_id,
                    "secondary": (),
                    "source": "strict_rule",
                }
            else:
                embedding = embedding_by_id.get(method_id)
                if (
                    embedding is not None
                    and str(embedding["family_id"]) in embedding_allowlist
                    and float(embedding["confidence"]) >= float(thresholds["ranking_score_min"])
                    and float(embedding["margin"] or 0.0) >= float(thresholds["margin_min"])
                ):
                    assignments[method_id] = {
                        "primary": str(embedding["family_id"]),
                        "secondary": (),
                        "source": "embedding",
                    }
        assignment = assignments.get(method_id)
        if assignment:
            source_counts[str(assignment["source"])] += 1
            primary_family_counts[str(assignment["primary"])] += 1
            all_family_counts[str(assignment["primary"])] += 1
            all_family_counts.update(str(family) for family in assignment["secondary"])

    assigned_ids = set(assignments)
    covered_relations = sum(int(row["object_id"]) in assigned_ids for row in relation_rows)
    all_pmids = {str(row["source_pmid"]) for row in relation_rows if str(row["source_pmid"])}
    covered_pmids = {
        str(row["source_pmid"])
        for row in relation_rows
        if str(row["source_pmid"]) and int(row["object_id"]) in assigned_ids
    }
    entity_coverage = len(assigned_ids) / len(entity_rows) if entity_rows else 0.0
    relation_coverage = covered_relations / len(relation_rows) if relation_rows else 0.0
    paper_coverage = len(covered_pmids) / len(all_pmids) if all_pmids else 0.0
    status = "coverage_validated" if paper_coverage >= min_paper_coverage else "coverage_rejected"
    report = {
        "preview_id": preview_id,
        "gold_set_id": gold_set_id,
        "calibration_id": calibration_id,
        "ruleset_id": ruleset_id,
        "taxonomy_version": str(gold["taxonomy_version"]),
        "graph_snapshot_sha256": graph_snapshot_sha256,
        "status": status,
        "release_build_eligible": False,
        "release_blocker": "C0-B is preview-only; accepted assignment/release writers are disabled",
        "idempotent": False,
        "precedence": ["gold", "strict_rule", "embedding", "unknown"],
        "embedding_policy": {
            "calibration_version": calibration_metrics.get("calibration_version"),
            "family_allowlist": sorted(embedding_allowlist),
            "ranking_score_min": float(thresholds["ranking_score_min"]),
            "margin_min": float(thresholds["margin_min"]),
        },
        "rules_policy": {
            "ruleset_version": str(ruleset["ruleset_version"]),
            "eligible_rule_ids": sorted(eligible_rule_ids),
        },
        "counts": {
            "active_method_entities": len(entity_rows),
            "assigned_method_entities": len(assigned_ids),
            "unknown_method_entities": len(entity_rows) - len(assigned_ids),
            "gold_unknown_blocked": gold_unknown_blocked,
            "active_method_relations": len(relation_rows),
            "covered_method_relations": covered_relations,
            "active_method_papers": len(all_pmids),
            "covered_method_papers": len(covered_pmids),
        },
        "coverage": {
            "entity": round(entity_coverage, 6),
            "relation": round(relation_coverage, 6),
            "paper": round(paper_coverage, 6),
            "minimum_paper": min_paper_coverage,
        },
        "primary_source_counts": dict(sorted(source_counts.items())),
        "primary_family_counts": dict(sorted(primary_family_counts.items())),
        "all_family_counts_including_manual_secondary": dict(sorted(all_family_counts.items())),
        "safety": {
            "accepted_assignments_before": accepted_before,
            "accepted_assignments_written": 0,
            "active_release_created": False,
        },
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_policy_previews
               (preview_id, gold_set_id, calibration_id, ruleset_id,
                graph_snapshot_sha256, metrics_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                preview_id,
                gold_set_id,
                calibration_id,
                ruleset_id,
                graph_snapshot_sha256,
                json.dumps(report, ensure_ascii=False, sort_keys=True),
                status,
            ),
        )
    _write_report(report, output_path)
    return report
