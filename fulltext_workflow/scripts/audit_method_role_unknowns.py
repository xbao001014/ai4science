"""List top unknown Method entities by APPLIES_METHOD paper count."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.method_role import classify_method_role
from db.schema import get_conn
from extractor.entity_normalize import _norm_key


def main() -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM entities WHERE type='Method'"
        ).fetchall()
        cnts = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS n
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = 'Method'
              AND r.relation = 'APPLIES_METHOD'
              AND COALESCE(r.status, 'active') = 'active'
            GROUP BY e.id
            """
        ).fetchall()
    papers = {str(r["name"]): int(r["n"]) for r in cnts}

    unknown: list[tuple[int, str]] = []
    roles = Counter()
    for r in rows:
        name = str(r["name"])
        role = classify_method_role(name)
        roles[role] += 1
        if role == "unknown":
            unknown.append((papers.get(name, 0), name))

    unknown.sort(reverse=True)
    print("live classify counts:", dict(roles))
    print(f"unknown={roles['unknown']} / {sum(roles.values())} "
          f"({100 * roles['unknown'] / max(1, sum(roles.values())):.1f}%)")
    print("\nTop 80 unknowns by APPLIES papers:")
    for n, name in unknown[:80]:
        print(f"  {n:4d}  {name}")

    cues = Counter()
    for _n, name in unknown:
        k = _norm_key(name)
        checks = [
            ("gan", ("gan", "diffusion")),
            ("bert_llm", ("bert", "gpt", "llm", "language model")),
            ("graph", ("graph neural", "gcn", "gat", "gnn")),
            ("mlp", ("mlp", "multilayer perceptron", "multi-layer perceptron")),
            ("svm", ("svm", "support vector")),
            ("rf", ("random forest", "xgboost", "lightgbm")),
            ("cox", ("cox", "survival", "kaplan")),
            ("cluster", ("k-means", "kmeans", "hierarchical cluster")),
            ("shap", ("shap", "grad-cam", "lime", "cam")),
            ("omics", ("rna-seq", "scrna", "bulk rna", "single-cell")),
            ("attention_only", ("attention",)),
            ("network", ("neural network", "deep learning", "dnn")),
            ("mask_rcnn", ("mask r-cnn", "maskrcnn", "faster r-cnn", "retinanet")),
            ("deeplab", ("deeplab",)),
            ("efficient", ("efficientnet", "mobilenet")),
        ]
        for label, substrs in checks:
            if any(s in k for s in substrs):
                cues[label] += 1
    print("\ncue hits among unknowns:", dict(cues.most_common()))

    # Paper-weighted: share of APPLIES edges whose method is unknown
    with get_conn() as conn:
        edge_rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS n
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = 'Method'
              AND r.relation = 'APPLIES_METHOD'
              AND COALESCE(r.status, 'active') = 'active'
            GROUP BY e.id
            """
        ).fetchall()
    weighted = Counter()
    total_w = 0
    for r in edge_rows:
        n = int(r["n"])
        total_w += n
        weighted[classify_method_role(str(r["name"]))] += n
    print("\nAPPLIES paper-weighted role share:")
    for role, n in weighted.most_common():
        print(f"  {role:14s} {n:6d}  ({100 * n / max(1, total_w):.1f}%)")
    print(f"  unknown_rate={100 * weighted['unknown'] / max(1, total_w):.1f}%")


if __name__ == "__main__":
    main()
