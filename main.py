"""main.py — Pathology AI Literature Knowledge Graph Pipeline
CLI entry point.  Always run as:  python main.py <command>

Usage examples:
  python main.py --help
  python main.py fetch              # Step 1+2: PubMed + S2 fetch
  python main.py fetch --pubmed-only
  python main.py extract            # Step 3: LLM triple extraction
  python main.py extract --limit 50
  python main.py import-if data/journals_if.xlsx
  python main.py build              # Step 4: build KG + visualize
  python main.py build --no-citations --no-authors
  python main.py run-all            # Full pipeline end-to-end
  python main.py stats              # Print DB statistics only
"""
from __future__ import annotations

import argparse
import sys
import time


def cmd_init(args: argparse.Namespace) -> None:
    from utils.db import init_db
    init_db()
    print("[Init] Database initialized.")


def cmd_fetch(args: argparse.Namespace) -> None:
    from utils.db import init_db, db_stats
    init_db()

    if not args.s2_only:
        print("\n── Step 1: PubMed fetch ──────────────────────────────────")
        from fetcher.pubmed_fetcher import fetch_all_queries
        fetch_all_queries(resume=not args.no_resume)

    if not args.pubmed_only:
        print("\n── Step 2: Semantic Scholar enrichment ───────────────────")
        from fetcher.s2_fetcher import enrich_from_s2
        enrich_from_s2(fetch_citations=not args.no_citations)

    print("\n[Fetch] DB stats:", db_stats())


def cmd_extract(args: argparse.Namespace) -> None:
    from utils.db import init_db, db_stats, get_conn
    init_db()
    print("\n── Step 3: LLM extraction ────────────────────────────────────")

    # Show current paper counts before starting
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        done  = conn.execute("SELECT COUNT(*) FROM papers WHERE extraction_done=1").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE extraction_done=0 AND abstract IS NOT NULL AND abstract != ''"
        ).fetchone()[0]
    print(f"  Papers in DB : {total}")
    print(f"  Already done : {done}")
    print(f"  To process   : {pending}" + (f"  (will run {args.limit})" if args.limit else ""))

    if pending == 0:
        print("\n  [Extract] Nothing to process — run 'python main.py fetch' first,")
        print("  or use --no-resume flag if you want to re-extract already-done papers.")
        return

    from extractor.triple_extractor import run_extraction
    run_extraction(limit=args.limit)
    print("\n[Extract] DB stats:", db_stats())


def cmd_import_if(args: argparse.Namespace) -> None:
    from utils.db import init_db
    init_db()
    print(f"\n── Import Impact Factors from {args.excel} ──────────────────")
    from utils.if_importer import import_impact_factors
    import_impact_factors(args.excel, if_year=args.if_year)


def cmd_build(args: argparse.Namespace) -> None:
    from utils.db import init_db, db_stats
    init_db()
    print("\n── Step 4: Build Knowledge Graph ─────────────────────────────")
    from graph.kg_builder import KGBuilder
    from viz.visualize import run_all

    builder = KGBuilder()
    G = builder.build(
        include_authors=args.authors,
        include_citations=not args.no_citations,
        min_citation_count=args.min_citations,
        year_range=(args.year_start, args.year_end) if args.year_start else None,
        study_types=args.study_types.split(",") if args.study_types else None,
    )

    if args.neo4j:
        builder.sync_to_neo4j()

    run_all(G, builder)
    print("\n[Build] DB stats:", db_stats())


def cmd_run_all(args: argparse.Namespace) -> None:
    """Run complete pipeline: fetch → extract → build."""
    print("═" * 60)
    print("  Pathology AI Knowledge Graph — Full Pipeline")
    print("═" * 60)
    t0 = time.time()

    cmd_fetch(args)
    cmd_extract(args)
    cmd_build(args)

    elapsed = time.time() - t0
    print(f"\n✓ Pipeline complete in {elapsed/60:.1f} minutes.")


def cmd_stats(args: argparse.Namespace) -> None:
    from utils.db import init_db, db_stats
    init_db()
    stats = db_stats()
    print("\n── Database Statistics ───────────────────────────────────────")
    for table, count in stats.items():
        print(f"  {table:<20} {count:,} rows")


# ─────────────────────────────────────────────────────────────────────────────
# Argument parser
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kg_paper",
        description="Pathology AI Literature Knowledge Graph Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="Initialize SQLite database")

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch papers from PubMed and Semantic Scholar")
    p_fetch.add_argument("--pubmed-only", action="store_true", help="Skip S2 enrichment")
    p_fetch.add_argument("--s2-only", action="store_true", help="Skip PubMed fetch")
    p_fetch.add_argument("--no-citations", action="store_true", help="Skip S2 citation edges")
    p_fetch.add_argument("--no-resume", action="store_true", help="Re-fetch all (no skip)")

    # extract
    p_extract = sub.add_parser("extract", help="Run LLM extraction on abstracts")
    p_extract.add_argument("--limit", type=int, default=0, help="Limit number of papers (0=all)")

    # import-if
    p_if = sub.add_parser("import-if", help="Import journal Impact Factors from Excel")
    p_if.add_argument("excel", help="Path to Excel file")
    p_if.add_argument("--if-year", type=int, default=None, help="Override IF year")

    # build
    p_build = sub.add_parser("build", help="Build KG and export visualizations")
    p_build.add_argument("--authors", action="store_true", help="Include author nodes")
    p_build.add_argument("--no-citations", action="store_true", help="Exclude citation edges")
    p_build.add_argument("--min-citations", type=int, default=0, help="Minimum citation count filter")
    p_build.add_argument("--year-start", type=int, default=None, help="Filter papers from year")
    p_build.add_argument("--year-end", type=int, default=None, help="Filter papers to year")
    p_build.add_argument("--study-types", type=str, default=None,
                         help="Comma-separated study types to include, e.g. ai_algorithm,review")
    p_build.add_argument("--neo4j", action="store_true", help="Sync to Neo4j after building")

    # run-all
    p_all = sub.add_parser("run-all", help="Run full pipeline end-to-end")
    p_all.add_argument("--pubmed-only", action="store_true")
    p_all.add_argument("--s2-only", action="store_true")
    p_all.add_argument("--no-citations", action="store_true")
    p_all.add_argument("--no-resume", action="store_true")
    p_all.add_argument("--limit", type=int, default=0)
    p_all.add_argument("--authors", action="store_true")
    p_all.add_argument("--min-citations", type=int, default=0)
    p_all.add_argument("--year-start", type=int, default=None)
    p_all.add_argument("--year-end", type=int, default=None)
    p_all.add_argument("--study-types", type=str, default=None)
    p_all.add_argument("--neo4j", action="store_true")

    # stats
    sub.add_parser("stats", help="Print database statistics")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "init":      cmd_init,
        "fetch":     cmd_fetch,
        "extract":   cmd_extract,
        "import-if": cmd_import_if,
        "build":     cmd_build,
        "run-all":   cmd_run_all,
        "stats":     cmd_stats,
    }
    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
