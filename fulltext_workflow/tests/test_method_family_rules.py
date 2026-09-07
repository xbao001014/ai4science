from __future__ import annotations

import json
import sqlite3
import sys
import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.method_family_rules import (  # noqa: E402
    build_policy_preview,
    evaluate_and_freeze_ruleset,
    match_strict_rule,
)
from analysis.method_family_review_queue import (  # noqa: E402
    QUEUE_FIELDS,
    build_coverage_review_queue,
    import_coverage_gold_extension,
)


def _match(name: str) -> tuple[str, str] | None:
    result = match_strict_rule(name)
    return (result.rule_id, result.family_id) if result else None


def test_strict_rule_boundaries_and_precedence():
    assert _match("TransMIL") == ("combo_transmil", "mil")
    assert _match("DINOv2 features") == ("representation_dino", "representation_learning")
    assert _match("multimodal transformer") == (
        "multimodal_architecture",
        "multimodal_fusion",
    )
    assert _match("virtual staining with CycleGAN") == (
        "generative_strict",
        "generative_model",
    )
    assert _match("Macenko stain normalization") == (
        "image_processing_strict",
        "image_processing",
    )
    assert _match("generative AI") is None
    assert _match("deep learning") is None
    assert _match("attention mechanism") is None
    assert _match("RT-qPCR") is None
    assert _match("graph convolutional neural network") == (
        "gnn_named",
        "graph_neural_network",
    )
    assert _match("self-supervised vision transformer (ViT)") == (
        "representation_named",
        "representation_learning",
    )
    assert _match("hierarchical multimodal co-attention transformer") == (
        "multimodal_architecture",
        "multimodal_fusion",
    )
    assert _match("classical weakly-supervised ViT") == ("mil_named", "mil")
    assert _match("MCS-Stain(Hover-Net)") == (
        "generative_strict",
        "generative_model",
    )
    assert _match("Olink proteomics platform") == ("tooling_named", "other_tooling")
    assert _match("spatial transformer network") is None
    assert match_strict_rule(
        "multimodal transformer", eligible_rule_ids={"transformer_named"}
    ) is None


def _seed_gold_and_methods() -> None:
    from db.schema import get_conn

    names = {
        1: "ResNet50",
        2: "DenseNet121",
        3: "generic AI workflow",
        4: "EfficientNet-B0",
        5: "ResNet101",
        6: "opaque classifier",
        7: "VGG16",
        8: "opaque embedding candidate",
        9: "unresolved workflow",
    }
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO entities (id, name, type) VALUES (?, ?, 'Method')",
            list(names.items()),
        )
        conn.execute(
            """INSERT INTO method_family_gold_sets
               (gold_set_id, taxonomy_version, file_sha256, source_filename,
                byte_count, row_count, known_count, unknown_count, secondary_count,
                normalization_policy, reviewer, split_manifest_sha256,
                calibration_count, holdout_count)
               VALUES ('gold-test', 'method-family-v1', ?, 'gold.csv', 100,
                       6, 5, 1, 0, 'test', 'expert', ?, 3, 3)""",
            ("a" * 64, "b" * 64),
        )
        labels = (
            (1, "ResNet50", "cnn", "calibration"),
            (2, "DenseNet121", "cnn", "calibration"),
            (3, "generic AI workflow", "unknown", "calibration"),
            (4, "EfficientNet-B0", "cnn", "holdout"),
            (5, "ResNet101", "cnn", "holdout"),
            (6, "opaque classifier", "cnn", "holdout"),
        )
        conn.executemany(
            """INSERT INTO method_family_gold_labels
               (gold_set_id, method_entity_id, source_row, method_name_snapshot,
                method_role_snapshot, paper_count_snapshot, raw_primary,
                normalized_primary, secondary_json, review_notes,
                suggested_primary, top1_similarity, ranking_score, margin,
                suggested_top3_json, split, split_group)
               VALUES ('gold-test', ?, ?, ?, 'unknown', 1, ?, ?, '[]', '',
                       'cnn', 0.8, 0.8, 0.1, '[\"cnn\"]', ?, ?)""",
            [
                (method_id, method_id + 1, name, family, family, split, f"group-{method_id}")
                for method_id, name, family, split in labels
            ],
        )
        conn.executemany(
            """INSERT INTO relations
               (subject_type, subject_id, relation, object_type, object_id,
                source_pmid, status)
               VALUES ('Paper', ?, 'APPLIES_METHOD', 'Method', ?, ?, 'active')""",
            [(method_id, method_id, f"PMID-{method_id}") for method_id in (1, 3, 7, 8, 9)],
        )


def test_ruleset_and_policy_preview_are_immutable_and_do_not_accept(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "rules.sqlite"))
    init_db()
    _seed_gold_and_methods()
    rules_report = evaluate_and_freeze_ruleset("gold-test")
    assert rules_report["status"] == "rules_validated"
    assert "cnn_named" in rules_report["eligible_rule_ids"]
    assert rules_report["holdout_final_allowlist"]["precision"] == 1.0

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO method_family_calibrations
               (calibration_id, gold_set_id, taxonomy_version,
                split_manifest_sha256, ruleset_version, thresholds_json,
                embedding_family_allowlist_json, blocked_families_json,
                metrics_json, status)
               VALUES ('cal-test', 'gold-test', 'method-family-v1', ?, 'none-c0a',
                       ?, '[\"cnn\"]', '[]', ?, 'threshold_validated')""",
            (
                "b" * 64,
                json.dumps({"ranking_score_min": 0.52, "margin_min": 0.01}),
                json.dumps({"calibration_version": "embedding-threshold-v2"}),
            ),
        )
        conn.execute(
            """INSERT INTO method_family_assignments
               (method_entity_id, family_id, taxonomy_version, candidate_rank,
                is_primary, confidence, similarity, margin, source, status,
                input_sha256, provider, model, dimensions)
               VALUES (8, 'cnn', 'method-family-v1', 1, 1, 0.8, 0.7, 0.1,
                       'embedding_shadow', 'review', ?, 'bailian',
                       'text-embedding-v4', 768)""",
            ("c" * 64,),
        )

    preview = build_policy_preview(
        "gold-test",
        "cal-test",
        rules_report["ruleset_id"],
        min_paper_coverage=0.60,
    )
    assert preview["status"] == "coverage_validated"
    assert preview["primary_source_counts"] == {"embedding": 1, "gold": 1, "strict_rule": 1}
    assert preview["counts"]["gold_unknown_blocked"] == 1
    assert preview["coverage"] == {
        "entity": 0.6,
        "relation": 0.6,
        "paper": 0.6,
        "minimum_paper": 0.6,
    }
    assert preview["release_build_eligible"] is False
    queue_path = tmp_path / "review.csv"
    queue_report = build_coverage_review_queue(
        "gold-test",
        "cal-test",
        rules_report["ruleset_id"],
        output_path=queue_path,
        target_paper_coverage=0.80,
    )
    assert queue_report["status"] == "target_reached"
    assert queue_report["counts"]["selected_rows"] == 1
    assert queue_report["coverage"]["projected_if_all_labeled"] == 0.8
    with queue_path.open(encoding="utf-8-sig", newline="") as handle:
        queue_rows = list(csv.DictReader(handle))
    assert queue_rows[0]["method_entity_id"] == "9"
    assert queue_rows[0]["gold_primary"] == ""
    queue_rows[0]["gold_primary"] = "cnn"
    queue_rows[0]["review_notes"] = "[judge] explicit synthetic label"
    with queue_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(queue_rows)
    extension = import_coverage_gold_extension(
        queue_path,
        queue_id=queue_report["queue_id"],
        reviewer="expert-coverage-v1",
        rank_start=1,
        rank_end=1,
    )
    duplicate = import_coverage_gold_extension(
        queue_path,
        queue_id=queue_report["queue_id"],
        reviewer="ignored-on-idempotent-import",
        rank_start=1,
        rank_end=1,
    )
    assert extension["counts"] == {
        "rows": 1,
        "known": 1,
        "unknown": 0,
        "secondary_labels": 0,
    }
    assert extension["coverage"]["after_extension"] == 0.8
    assert duplicate["idempotent"] is True
    with get_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM method_family_assignments WHERE status='accepted'"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM method_family_policy_previews").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM method_family_review_queues").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM method_family_gold_extensions").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM method_family_gold_extension_labels"
        ).fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with get_conn() as conn:
            conn.execute(
                "UPDATE method_family_rulesets SET status='changed' WHERE ruleset_id=?",
                (rules_report["ruleset_id"],),
            )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with get_conn() as conn:
            conn.execute(
                "UPDATE method_family_gold_extensions SET reviewer='changed' WHERE extension_id=?",
                (extension["extension_id"],),
            )
