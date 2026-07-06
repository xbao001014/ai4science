"""CLI entry for the isolated full-text workflow sandbox."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import config

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def cmd_init(_args: argparse.Namespace) -> None:
    from db.schema import init_db
    init_db()


def cmd_enrich_s2(_args: argparse.Namespace) -> None:
    from db.schema import db_stats, init_db
    from fetcher.citation_fetcher import enrich_citations

    init_db()
    enrich_citations()
    print("\n[Enrich-Citations] Stats:", db_stats())


def cmd_import_if(args: argparse.Namespace) -> None:
    from db.schema import db_stats, init_db
    from utils.if_importer import import_impact_factors

    init_db()
    excel_path = getattr(args, "excel", None) or config.JCR_IF_PATH
    if_year = args.if_year if args.if_year is not None else config.JCR_IF_YEAR
    if not Path(excel_path).exists():
        raise FileNotFoundError(
            f"IF file not found: {excel_path}\n"
            f"Place jcr.csv at data/jcr.csv or pass a path: main.py import-if <path>"
        )
    import_impact_factors(excel_path, if_year=if_year)
    print("\n[Import-IF] Stats:", db_stats())


def cmd_fetch(args: argparse.Namespace) -> None:
    from db.schema import db_stats, init_db
    from fetcher.pubmed_fetcher import fetch_all_queries

    init_db()
    since_days = args.since_days if args.since_days is not None else None
    fetch_all_queries(resume=not args.no_resume, since_days=since_days)
    print("\n[Fetch] Stats:", db_stats())


def cmd_fetch_fulltext(_args: argparse.Namespace) -> None:
    from db.schema import db_stats, init_db
    from fetcher.fulltext_fetcher import fetch_all_fulltext

    init_db()
    fetch_all_fulltext(cache_xml=True)
    print("\n[Fetch-Fulltext] Stats:", db_stats())


def cmd_extract(args: argparse.Namespace) -> None:
    from db.schema import db_stats, get_papers_for_extraction, init_db
    from extractor.section_extractor import run_extraction

    init_db()
    if args.all_sections:
        config.EXTRACT_CORE_ONLY = False
    elif args.core_only:
        config.EXTRACT_CORE_ONLY = True
    if args.section_workers is not None:
        config.EXTRACT_SECTION_WORKERS = max(1, args.section_workers)
    if args.paper_workers is not None:
        config.EXTRACT_PAPER_WORKERS = max(1, args.paper_workers)

    limit = args.limit if args.limit is not None else None
    preview = get_papers_for_extraction(limit=0 if limit == 0 else (limit or 9999))
    label = "all" if limit == 0 else (limit or config.DEFAULT_EXTRACT_LIMIT)
    print(f"  Papers queued: {len(preview)} (limit={label})")
    run_extraction(limit=limit)
    print("\n[Extract] Stats:", db_stats())


def cmd_build(_args: argparse.Namespace) -> None:
    from db.schema import init_db
    from graph.kg_builder import KGBuilder
    from viz.visualize import run_all

    init_db()
    builder = KGBuilder()
    G = builder.build()
    builder.export_gexf()
    builder.export_stats_csv()
    run_all(G)


def cmd_viz(_args: argparse.Namespace) -> None:
    from db.schema import init_db
    from graph.kg_builder import KGBuilder
    from viz.visualize import run_all

    init_db()
    builder = KGBuilder()
    G = builder.build()
    run_all(G)


def cmd_analyze(_args: argparse.Namespace) -> None:
    from analysis.gap_tools import generate_report
    from db.schema import init_db

    init_db()
    generate_report()


def cmd_compute_gap_lifecycle(args: argparse.Namespace) -> None:
    from analysis.gap_lifecycle import run_gap_lifecycle
    from db.schema import init_db

    init_db()
    stats = run_gap_lifecycle(
        force=not args.no_force,
        temporal_only=args.temporal_only,
        verbose=True,
    )
    print("\n[Gap-Lifecycle] Summary:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


def cmd_gap_debate(args: argparse.Namespace) -> None:
    from gap_agent import run_gap_debate_agent, save_report

    from db.schema import init_db

    init_db()
    report = run_gap_debate_agent(
        focus=args.focus or None,
        top_n=args.top,
        max_debate_rounds=args.rounds,
        verbose=args.verbose,
    )
    if args.output and report:
        save_report(report, args.output, focus=args.focus)
        print(f"[Gap-Debate] Saved to {args.output}")


def cmd_watch_fetch(args: argparse.Namespace) -> None:
    from utils.fetch_progress import watch_fetch_progress

    watch_fetch_progress(
        interval=args.interval,
        once=args.once,
        clear=not args.no_clear,
    )


def cmd_stats(_args: argparse.Namespace) -> None:
    from db.schema import db_stats, init_db

    init_db()
    stats = db_stats()
    print("\n=== Full-Text Workflow Stats ===")
    for k, v in stats.items():
        print(f"  {k:25s}: {v}")


def cmd_bootstrap_landscape(args: argparse.Namespace) -> None:
    from db.schema import init_db, landscape_count
    from feasibility.landscape import bootstrap_landscape, check_api_connectivity

    init_db()
    if args.force:
        pre = check_api_connectivity()
        if not pre["ok"]:
            print(f"[Bootstrap] API unreachable ({pre['host']}): {pre['error']}")
            print(
                "[Bootstrap] Tip: verify network/VPN/DNS can resolve "
                f"{pre['host']}, then retry."
            )
    result = bootstrap_landscape(force=args.force)
    if result.get("skipped"):
        print(f"[Bootstrap] Skipped: {result['reason']} ({result['disease_count']} diseases)")
    elif result.get("api_error") and result.get("loaded", 0) == 0:
        kept = result.get("kept_existing")
        print(f"[Bootstrap] Loaded 0 diseases (API error).")
        if kept:
            print(
                f"[Bootstrap] Kept existing cache: {landscape_count()} diseases "
                "(not cleared because reload failed)."
            )
        else:
            print(f"[Bootstrap] {result['api_error']}")
    else:
        print(
            f"[Bootstrap] Loaded {result.get('loaded', result['disease_count'])} diseases: "
            f"{result.get('disease_ids', [])}"
        )
        if result.get("errors"):
            print(f"[Bootstrap] {len(result['errors'])} disease(s) skipped (see above).")
    print(f"[Bootstrap] landscape_count={landscape_count()}")


def cmd_idea_pipeline(args: argparse.Namespace) -> None:
    from pipeline import run_idea_pipeline, save_pipeline_report

    report, _results = run_idea_pipeline(
        focus=args.focus or None,
        top_n=args.top,
        debate_rounds=args.rounds,
        idea_rounds=args.idea_rounds,
        gap_report_path=args.gap_report,
        skip_debate=args.skip_debate,
        skip_ideas=args.skip_ideas,
        verbose=args.verbose,
    )
    out = args.output or f"{config.OUTPUT_DIR}/idea_pipeline_report.md"
    save_pipeline_report(report, out)


def cmd_compute_weekly_hotspots(args: argparse.Namespace) -> None:
    from analysis.weekly_hotspot import compute_weekly_hotspots
    from db.schema import init_db

    init_db()
    payload = compute_weekly_hotspots(
        window_days=args.days,
        prior_days=args.prior_days,
    )
    print("\n[Weekly-Hotspot] Summary:")
    print(f"  week_id          : {payload['week_id']}")
    print(f"  window_days      : {payload['window_days']}")
    print(f"  papers_ingested  : {payload['papers_ingested']}")
    print(f"  emerging_methods : {len(payload['emerging_methods'])}")
    print(f"  heating_diseases : {len(payload['heating_diseases'])}")
    print(f"  hot_combos       : {len(payload['hot_combos'])}")
    print(f"  new_limitations  : {len(payload['new_limitations'])}")
    if payload["emerging_methods"]:
        top = payload["emerging_methods"][0]
        print(f"  top_method       : {top['name']} (score={top['emerging_score']})")


def cmd_hotspot_report(args: argparse.Namespace) -> None:
    from analysis.weekly_hotspot import save_hotspot_report
    from db.schema import init_db

    init_db()
    path, payload = save_hotspot_report(
        args.output,
        window_days=args.days,
        prior_days=args.prior_days,
        persist=not args.no_persist,
    )
    print(f"[Hotspot-Report] Saved to {path}")
    print(f"  papers_ingested={payload['papers_ingested']}, week={payload['week_id']}")
    if payload.get("snapshot_rows") is not None:
        print(f"  snapshot_rows={payload['snapshot_rows']}")
    wow = payload.get("week_over_week") or {}
    if wow.get("has_baseline"):
        print(f"  week_over_week vs {wow['previous_week_id']}: OK")
    else:
        print(f"  week_over_week: no baseline ({wow.get('previous_week_id', '?')})")


def cmd_hotspot_brief(args: argparse.Namespace) -> None:
    from analysis.hotspot_brief import save_hotspot_brief
    from db.schema import init_db

    init_db()
    if not config.OPENAI_API_KEY:
        print("[Hotspot-Brief] OPENAI_API_KEY / DASHSCOPE_API_KEY not set.")
        sys.exit(1)
    path, text, payload = save_hotspot_brief(
        args.output,
        window_days=args.days,
        prior_days=args.prior_days,
        persist=not args.no_persist,
    )
    print(f"[Hotspot-Brief] Saved to {path}")
    print(f"  model={config.LLM_MODEL_AGENT}, week={payload['week_id']}")
    print(f"  opportunities={len(payload.get('emerging_gap_opportunities', []))}")


def cmd_run_all(args: argparse.Namespace) -> None:
    print("=" * 60)
    print(f"  Full-Text Workflow — {config.search_scope_label()}")
    print("=" * 60)
    t0 = time.time()

    cmd_fetch(args)
    cmd_fetch_fulltext(args)
    cmd_extract(args)
    cmd_build(args)
    cmd_analyze(args)
    cmd_stats(args)

    print(f"\nDone in {(time.time() - t0) / 60:.1f} minutes.")


def cmd_run_db(args: argparse.Namespace) -> None:
    """Populate SQLite only: fetch → citations/IF → fulltext → extract."""
    print("=" * 60)
    print(f"  Database Pipeline — {config.search_scope_label()}")
    print("  fetch → enrich-s2 → import-if → fetch-fulltext → extract")
    print("=" * 60)
    t0 = time.time()

    cmd_fetch(args)
    if not args.skip_enrich:
        cmd_enrich_s2(args)
        cmd_import_if(args)
    else:
        print("\n[run-db] Skipping enrich-s2 and import-if (--skip-enrich).")
    cmd_fetch_fulltext(args)
    cmd_extract(args)
    cmd_stats(args)

    print(f"\n[run-db] Done in {(time.time() - t0) / 60:.1f} minutes.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Isolated full-text KG workflow ({config.search_scope_label()})"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize database")

    p_fetch = sub.add_parser("fetch", help="Fetch PubMed metadata")
    p_fetch.add_argument("--no-resume", action="store_true")
    p_fetch.add_argument(
        "--since-days",
        type=int,
        default=None,
        metavar="N",
        help="Only papers indexed in PubMed within last N days (EDAT). "
        "Default from FETCH_EDAT_DAYS env (0=off). Weekly: --since-days 14",
    )

    sub.add_parser(
        "enrich-s2",
        help="Enrich citation counts (OpenAlex default; S2 if available)",
    )

    p_if = sub.add_parser(
        "import-if",
        help="Import journal Impact Factors from default data/jcr.csv or a custom file",
    )
    p_if.add_argument(
        "excel",
        nargs="?",
        default=None,
        help=f"Path to IF spreadsheet (default: {config.JCR_IF_PATH})",
    )
    p_if.add_argument(
        "--if-year",
        type=int,
        default=None,
        help=f"IF year label (default: {config.JCR_IF_YEAR})",
    )

    sub.add_parser("fetch-fulltext", help="Fetch full text: JATS → PDF/MinerU fallback")

    p_ext = sub.add_parser("extract", help="LLM section extraction")
    p_ext.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max papers (default 30; 0 = all pending)",
    )
    p_ext.add_argument(
        "--core-only",
        action="store_true",
        default=None,
        help="Only methods/results/discussion/limitations/future_work (faster)",
    )
    p_ext.add_argument(
        "--all-sections",
        action="store_true",
        help="Include introduction/other sections (slower, default off via EXTRACT_CORE_ONLY)",
    )
    p_ext.add_argument(
        "--section-workers",
        type=int,
        default=None,
        help="Parallel LLM calls per paper (default from EXTRACT_SECTION_WORKERS)",
    )
    p_ext.add_argument(
        "--paper-workers",
        type=int,
        default=None,
        help="Parallel papers (default from EXTRACT_PAPER_WORKERS)",
    )

    sub.add_parser("build", help="Build KG, export GEXF/CSV, and HTML visualizations")
    sub.add_parser("viz", help="Regenerate HTML visualizations from existing DB")
    sub.add_parser("analyze", help="Generate static gap report (no LLM)")
    p_lifecycle = sub.add_parser(
        "compute-gap-lifecycle",
        help="Compute limitation temporal profiles and resolution signals",
    )
    p_lifecycle.add_argument(
        "--no-force",
        action="store_true",
        help="Skip clearing existing limitation_temporal before recompute",
    )
    p_lifecycle.add_argument(
        "--temporal-only",
        action="store_true",
        help="Only compute/write limitation_temporal (skip resolution; much faster)",
    )

    p_hotspot = sub.add_parser(
        "compute-weekly-hotspots",
        help="Compute recent-ingest research hotspots (stdout summary)",
    )
    p_hotspot.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"Recent ingest window in days (default: {config.HOTSPOT_WINDOW_DAYS})",
    )
    p_hotspot.add_argument(
        "--prior-days",
        type=int,
        default=None,
        help=f"Prior comparison window (default: {config.HOTSPOT_PRIOR_WINDOW_DAYS})",
    )

    p_hotspot_report = sub.add_parser(
        "hotspot-report",
        help="Generate weekly hotspot markdown report",
    )
    p_hotspot_report.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"Recent ingest window (default: {config.HOTSPOT_WINDOW_DAYS})",
    )
    p_hotspot_report.add_argument(
        "--prior-days",
        type=int,
        default=None,
        help=f"Prior comparison window (default: {config.HOTSPOT_PRIOR_WINDOW_DAYS})",
    )
    p_hotspot_report.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path (default: output/weekly_hotspot_{week_id}.md)",
    )
    p_hotspot_report.add_argument(
        "--no-persist",
        action="store_true",
        help="Skip writing snapshot to DB (no week-over-week next run)",
    )

    p_brief = sub.add_parser(
        "hotspot-brief",
        help="LLM weekly hotspot trend brief (qwen3.7-plus / LLM_MODEL_AGENT)",
    )
    p_brief.add_argument("--days", type=int, default=None)
    p_brief.add_argument("--prior-days", type=int, default=None)
    p_brief.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path (default: output/weekly_hotspot_brief_{week_id}.md)",
    )
    p_brief.add_argument("--no-persist", action="store_true")

    p_debate = sub.add_parser("gap-debate", help="LLM debate multi-agent gap analysis")
    p_debate.add_argument("--focus", "-f", default=None)
    p_debate.add_argument("--top", "-n", type=int, default=6)
    p_debate.add_argument("--rounds", "-r", type=int, default=2)
    p_debate.add_argument("--output", "-o", default=None)
    p_debate.add_argument("--verbose", "-v", action="store_true")

    p_landscape = sub.add_parser(
        "bootstrap-landscape",
        help="Load pathology data landscape from Fangxin API into SQLite (Phase 0)",
    )
    p_landscape.add_argument("--force", action="store_true", help="Reload even if already populated")

    p_pipeline = sub.add_parser(
        "idea-pipeline",
        help="End-to-end: gap debate → feasibility → hypothesis generation",
    )
    p_pipeline.add_argument("--focus", "-f", default=None)
    p_pipeline.add_argument("--top", "-n", type=int, default=3)
    p_pipeline.add_argument("--rounds", "-r", type=int, default=2, help="Gap debate rounds")
    p_pipeline.add_argument("--idea-rounds", type=int, default=3, help="Generator x Critic rounds")
    p_pipeline.add_argument("--gap-report", default=None, help="Existing gap report markdown path")
    p_pipeline.add_argument("--skip-debate", action="store_true")
    p_pipeline.add_argument("--skip-ideas", action="store_true", help="Feasibility only, no LLM proposals")
    p_pipeline.add_argument("--output", "-o", default=None)
    p_pipeline.add_argument("--verbose", "-v", action="store_true")

    sub.add_parser("stats", help="Print database statistics")

    p_watch = sub.add_parser(
        "watch-fetch",
        help="Live PubMed fetch progress (poll DB; run in a second terminal)",
    )
    p_watch.add_argument(
        "--interval",
        "-i",
        type=int,
        default=10,
        help="Refresh interval in seconds (default: 10)",
    )
    p_watch.add_argument(
        "--once",
        action="store_true",
        help="Print one snapshot and exit",
    )
    p_watch.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear screen between refreshes",
    )

    p_all = sub.add_parser("run-all", help="Run complete pipeline")
    p_all.add_argument("--no-resume", action="store_true")
    p_all.add_argument("--limit", type=int, default=30, help="Extraction limit")

    p_db = sub.add_parser(
        "run-db",
        help="Database pipeline: fetch → enrich-s2 → import-if → fetch-fulltext → extract",
    )
    p_db.add_argument("--no-resume", action="store_true")
    p_db.add_argument(
        "--since-days",
        type=int,
        default=None,
        metavar="N",
        help="Only papers indexed in PubMed within last N days (EDAT)",
    )
    p_db.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip enrich-s2 and import-if (citations/IF)",
    )
    p_db.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Extraction limit (default 0 = all pending)",
    )
    p_db.add_argument(
        "--core-only",
        action="store_true",
        default=None,
        help="Only core sections (faster)",
    )
    p_db.add_argument(
        "--all-sections",
        action="store_true",
        help="Include introduction/other sections",
    )
    p_db.add_argument("--section-workers", type=int, default=None)
    p_db.add_argument("--paper-workers", type=int, default=None)
    p_db.add_argument(
        "--if-year",
        type=int,
        default=None,
        help=f"IF year for import-if (default: {config.JCR_IF_YEAR})",
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "init": cmd_init,
        "fetch": cmd_fetch,
        "enrich-s2": cmd_enrich_s2,
        "import-if": cmd_import_if,
        "fetch-fulltext": cmd_fetch_fulltext,
        "extract": cmd_extract,
        "build": cmd_build,
        "viz": cmd_viz,
        "analyze": cmd_analyze,
        "compute-gap-lifecycle": cmd_compute_gap_lifecycle,
        "compute-weekly-hotspots": cmd_compute_weekly_hotspots,
        "hotspot-report": cmd_hotspot_report,
        "hotspot-brief": cmd_hotspot_brief,
        "gap-debate": cmd_gap_debate,
        "bootstrap-landscape": cmd_bootstrap_landscape,
        "idea-pipeline": cmd_idea_pipeline,
        "stats": cmd_stats,
        "watch-fetch": cmd_watch_fetch,
        "run-all": cmd_run_all,
        "run-db": cmd_run_db,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
