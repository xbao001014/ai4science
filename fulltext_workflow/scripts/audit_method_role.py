"""Audit method_role coverage on live corpus."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.method_role import classify_method_role
from analysis.method_synonyms import resolve_method_canonical
from db.schema import get_conn
from extractor.entity_normalize import is_low_value_method


def main() -> None:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS n
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type = 'Method'
              AND r.relation = 'APPLIES_METHOD'
              AND COALESCE(r.status, 'active') = 'active'
            GROUP BY e.id
            ORDER BY n DESC
            """
        ).fetchall()

    by_can: dict[str, int] = {}
    for r in rows:
        name = str(r["name"])
        if is_low_value_method(name):
            continue
        can = resolve_method_canonical(name)
        if is_low_value_method(can):
            continue
        by_can[can] = by_can.get(can, 0) + int(r["n"])

    ranked = sorted(by_can.items(), key=lambda x: -x[1])
    for top_n in (50, 100, 200):
        roles: Counter[str] = Counter()
        unknowns: list[tuple[int, str]] = []
        for name, n in ranked[:top_n]:
            role = classify_method_role(name)
            roles[role] += 1
            if role == "unknown":
                unknowns.append((n, name))
        print(f"=== Top {top_n} ===")
        print(dict(roles))
        pct_u = 100.0 * roles["unknown"] / top_n
        print(f"unknown pct: {pct_u:.1f}%")
        print("Top unknowns:")
        for n, name in unknowns[:25]:
            print(f"  {n:4d}  {name}")
        print()


def main_emerging() -> None:
    from analysis.method_maturity import (
        classify_method_maturity,
        corpus_applies_method_counts_canonical,
    )

    counts = corpus_applies_method_counts_canonical()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS n
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type = 'Method'
              AND r.relation = 'APPLIES_METHOD'
              AND COALESCE(r.status, 'active') = 'active'
            GROUP BY e.id
            """
        ).fetchall()

    by_can: dict[str, int] = {}
    for r in rows:
        name = str(r["name"])
        if is_low_value_method(name):
            continue
        can = resolve_method_canonical(name)
        if is_low_value_method(can):
            continue
        by_can[can] = by_can.get(can, 0) + int(r["n"])

    emerging: list[tuple[int, str, str, str]] = []
    for name, n in sorted(by_can.items(), key=lambda x: -x[1]):
        mat = classify_method_maturity(name, counts.get(name, n))
        if mat == "established":
            continue
        emerging.append((n, name, classify_method_role(name), mat))

    slice_n = min(150, len(emerging))
    roles: Counter[str] = Counter(r for _, _, r, _ in emerging[:slice_n])
    print(f"=== Non-established top {slice_n} ===")
    print(dict(roles))
    print(f"unknown pct: {100.0 * roles['unknown'] / slice_n:.1f}%")
    print("Top unknown non-established:")
    shown = 0
    for n, name, role, mat in emerging:
        if role != "unknown":
            continue
        print(f"  {n:4d}  [{mat}] {name}")
        shown += 1
        if shown >= 40:
            break


if __name__ == "__main__":
    main()
    main_emerging()
