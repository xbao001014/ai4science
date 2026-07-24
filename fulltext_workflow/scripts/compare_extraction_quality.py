#!/usr/bin/env python3
"""Compare extraction quality: DB baseline stats and optional live re-extract."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import get_conn, get_paper_sections  # noqa: E402
from extractor.entity_normalize import is_generic_method

def _top_entities(entity_type: str, relation: str, limit: int = 20) -> list[tuple[str, int]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name, COUNT(*) AS cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = ? AND r.relation = ?
            GROUP BY e.id
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (entity_type, relation, limit),
        ).fetchall()
    return [(row["name"], row["cnt"]) for row in rows]


def print_db_baseline() -> None:
    print("=== DB: top Methods (APPLIES_METHOD = contribution) ===")
    for name, cnt in _top_entities("Method", "APPLIES_METHOD"):
        tag = " [generic]" if is_generic_method(name) else ""
        print(f"  {cnt:4d}  {name}{tag}")

    print("\n=== DB: top Methods (COMPARES_METHOD = baselines) ===")
    for name, cnt in _top_entities("Method", "COMPARES_METHOD"):
        tag = " [generic]" if is_generic_method(name) else ""
        print(f"  {cnt:4d}  {name}{tag}")

    print("\n=== DB baseline: top Limitations (REPORTS_LIMITATION) ===")
    for name, cnt in _top_entities("Limitation", "REPORTS_LIMITATION"):
        print(f"  {cnt:4d}  {name}")

    generic_total = sum(
        cnt for name, cnt in _top_entities("Method", "APPLIES_METHOD", limit=500)
        if is_generic_method(name)
    )
    print(f"\nGeneric methods in APPLIES_METHOD top-500: {generic_total} relations")


def _sample_papers(limit: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, pmid, title
            FROM papers
            WHERE extraction_done = 1
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def live_reextract(pmid: str | None, limit: int, section_types: set[str]) -> None:
    from extractor.section_extractor import _extract_from_text

    papers = []
    if pmid:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, pmid, title FROM papers WHERE pmid = ?", (pmid,)
            ).fetchone()
        if not row:
            print(f"PMID {pmid} not found.")
            return
        papers = [dict(row)]
    else:
        papers = _sample_papers(limit)

    print(f"\n=== Live re-extract ({len(papers)} paper(s)) ===")
    for paper in papers:
        sections = get_paper_sections(paper["id"])
        jobs = [
            s
            for s in sections
            if s["section_type"] in section_types and (s["content"] or "").strip()
        ]
        print(f"\nPMID {paper['pmid']}: {paper['title'][:80]}")
        if not jobs:
            print("  (no matching sections)")
            continue

        method_names: Counter[str] = Counter()
        compares_names: Counter[str] = Counter()
        limitation_names: Counter[str] = Counter()
        for sec in jobs:
            triples = _extract_from_text(
                paper["title"],
                sec["section_type"],
                sec["title"] or sec["section_type"],
                sec["content"],
            )
            for t in triples:
                if t.object.type == "Method" and t.relation == "APPLIES_METHOD":
                    method_names[t.object.name] += 1
                if t.object.type == "Method" and t.relation == "COMPARES_METHOD":
                    compares_names[t.object.name] += 1
                if t.object.type == "Limitation" and t.relation == "REPORTS_LIMITATION":
                    limitation_names[t.object.name] += 1

        print("  APPLIES_METHOD:", ", ".join(method_names) or "(none)")
        print("  COMPARES_METHOD:", ", ".join(compares_names) or "(none)")
        print("  Limitations:", ", ".join(limitation_names) or "(none)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare extraction quality")
    parser.add_argument("--baseline", action="store_true", help="Print DB entity stats")
    parser.add_argument("--live", action="store_true", help="Re-extract sample papers via LLM")
    parser.add_argument("--pmid", type=str, default=None, help="Single PMID for --live")
    parser.add_argument("--limit", type=int, default=3, help="Random papers for --live")
    parser.add_argument(
        "--sections",
        type=str,
        default="methods,discussion,limitations",
        help="Comma-separated section types for --live",
    )
    args = parser.parse_args()

    if not args.baseline and not args.live:
        args.baseline = True

    if args.baseline:
        print_db_baseline()

    if args.live:
        section_types = {s.strip() for s in args.sections.split(",") if s.strip()}
        live_reextract(args.pmid, args.limit, section_types)


if __name__ == "__main__":
    main()
