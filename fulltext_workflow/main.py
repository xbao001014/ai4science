"""CLI entry for the isolated full-text workflow sandbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

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
    from fetcher.source_fetcher import fetch_arxiv, fetch_europepmc

    init_db()
    since_days = args.since_days if args.since_days is not None else None
    sources = [part.strip().lower() for part in getattr(args, "sources", config.LITERATURE_SOURCES).split(",") if part.strip()]
    invalid = set(sources) - {"pubmed", "europepmc", "arxiv"}
    if invalid:
        raise ValueError(f"Unknown literature source(s): {', '.join(sorted(invalid))}")
    days = since_days if since_days is not None else config.FETCH_EDAT_DAYS
    if "pubmed" in sources:
        fetch_all_queries(resume=not args.no_resume, since_days=days)
    if "europepmc" in sources:
        print("[Europe PMC]", fetch_europepmc(
            since_days=days, group_name=getattr(args, "group", None),
            limit_per_group=getattr(args, "source_limit_per_group", None),
        ))
    if "arxiv" in sources:
        print("[arXiv]", fetch_arxiv(
            since_days=days, group_name=getattr(args, "group", None),
            limit_per_group=getattr(args, "source_limit_per_group", None),
        ))
    print("\n[Fetch] Stats:", db_stats())


def cmd_fetch_fulltext(args: argparse.Namespace) -> None:
    from db.schema import db_stats, init_db
    from fetcher.fulltext_fetcher import fetch_all_fulltext

    init_db()
    if getattr(args, "no_retry", False) and getattr(args, "force_retry", False):
        raise SystemExit("Use only one of --no-retry / --force-retry")
    retry = not getattr(args, "no_retry", False)
    force_retry = bool(getattr(args, "force_retry", False))
    pdf_limit = getattr(args, "pdf_retry_limit", None)
    skip_pdf = bool(getattr(args, "skip_pdf", False))
    fetch_all_fulltext(
        cache_xml=True,
        retry=retry,
        force_retry=force_retry,
        pdf_retry_limit=pdf_limit,
        skip_pdf=skip_pdf,
    )
    print("\n[Fetch-Fulltext] Stats:", db_stats())


def _load_pmid_list(path_str: str) -> list[str]:
    path = Path(path_str)
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def cmd_extract(args: argparse.Namespace) -> None:
    from db.schema import db_stats, get_papers_by_pmids, get_papers_for_extraction, init_db
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

    upgrade = getattr(args, "upgrade_reextract", False)
    no_upgrade = getattr(args, "no_upgrade_reextract", False)
    if upgrade and no_upgrade:
        raise SystemExit("Use only one of --upgrade-reextract / --no-upgrade-reextract")
    if upgrade:
        config.FULLTEXT_UPGRADE_REEXTRACT = True
    elif no_upgrade:
        config.FULLTEXT_UPGRADE_REEXTRACT = False

    limit = args.limit if args.limit is not None else None
    pmids = _load_pmid_list(args.pmid_list) if args.pmid_list else None
    if pmids:
        preview = get_papers_by_pmids(pmids)
        label = f"pmid-list ({len(pmids)} requested)"
    else:
        preview = get_papers_for_extraction(limit=0 if limit == 0 else (limit or 9999))
        label = "all" if limit == 0 else (limit or config.DEFAULT_EXTRACT_LIMIT)
    print(f"  Papers queued: {len(preview)} (limit={label})")
    run_extraction(
        limit=limit,
        pmids=pmids,
        force_reextract=bool(args.force_reextract),
    )
    print("\n[Extract] Stats:", db_stats())


def cmd_reconcile(args: argparse.Namespace) -> None:
    from db.schema import db_stats, get_conn, get_papers_by_pmids, init_db
    from extractor.section_extractor import _run_reconcile_for_paper

    init_db()
    if args.pmid_list:
        requested = _load_pmid_list(args.pmid_list)
        all_papers = get_papers_by_pmids(requested)
        by_pmid = {p["pmid"]: p for p in all_papers}
        papers = [p for p in all_papers if p["extraction_done"] == 1]
        skipped = [
            pmid
            for pmid in requested
            if pmid not in by_pmid or by_pmid[pmid]["extraction_done"] != 1
        ]
        if skipped:
            print(
                f"[Reconcile] Skipped {len(skipped)} PMID(s) without Pass 1: {skipped}"
            )
    else:
        with get_conn() as conn:
            papers = conn.execute(
                """SELECT * FROM papers
                   WHERE extraction_done=1
                     AND COALESCE(reconcile_status, 'pending') IN ('pending', 'failed')
                     AND full_text_status IN ('available', 'pdf_available')
                   ORDER BY year DESC"""
            ).fetchall()

    print(f"[Reconcile] {len(papers)} paper(s)")
    for paper in papers:
        paper_id = paper["id"]
        pmid = paper["pmid"] or ""
        print(f"\n  [Reconcile] PMID {pmid} (status={paper['reconcile_status']})")
        _run_reconcile_for_paper(
            paper, paper_id, pmid, study_type=paper["study_type"] if "study_type" in paper.keys() else None
        )
    print("\n[Reconcile] Stats:", db_stats())


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
    from analysis.ops_memory import persist_debate_report

    from db.schema import init_db

    init_db()
    debate_meta: dict = {}
    report = run_gap_debate_agent(
        focus=args.focus or None,
        top_n=args.top,
        max_debate_rounds=args.rounds,
        verbose=args.verbose,
        use_ops_memory=not args.no_ops_memory,
        result_meta=debate_meta,
        resume_session_id=args.resume_session or None,
    )
    if args.output and report:
        save_report(
            report,
            args.output,
            focus=debate_meta.get("focus") or args.focus,
        )
        print(f"[Gap-Debate] Saved to {args.output}")
    if report and not args.no_ops_persist:
        rid = persist_debate_report(
            report,
            focus=debate_meta.get("focus") or args.focus or None,
            source="gap-debate",
            gap_report_path=args.output or "",
            enabled=True,
            validation_status=debate_meta.get(
                "validation_status", "needs_verification"
            ),
            debate_session_id=debate_meta.get("session_id", ""),
        )
        if rid:
            print(f"[Gap-Debate] Ops memory run_id={rid}")


def cmd_embedding_preflight(args: argparse.Namespace) -> None:
    """Validate Phase A configuration; network is opt-in via --live-probe."""
    from analysis.embedding_client import EmbeddingClient, EmbeddingItem
    from analysis.embedding_service import embed_with_cache
    from db.schema import init_db

    init_db()
    errors = config.validate_embedding_config()
    key, key_source = config.embedding_key_and_source()
    host = urlparse(config.EMBEDDING_API_BASE).hostname or "invalid"
    summary = {
        "provider": config.EMBEDDING_PROVIDER,
        "base_host": host,
        "model": config.EMBEDDING_MODEL,
        "dimensions": config.EMBEDDING_DIMENSIONS,
        "batch_size": config.EMBEDDING_BATCH_SIZE,
        "enabled": config.EMBEDDING_ENABLED,
        "key_source": key_source,
        "key_configured": bool(key),
        "network_called": False,
        "config_errors": errors,
    }
    if errors:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit("Embedding configuration is invalid")
    if not args.live_probe:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if not config.EMBEDDING_ENABLED:
        raise SystemExit("Set EMBEDDING_ENABLED=1 before using --live-probe")
    if not key:
        raise SystemExit("A Bailian embedding API key is required for --live-probe")

    probe_texts = (
        "method: convolutional neural network",
        "method: multiple instance learning",
    )
    items = [
        EmbeddingItem(
            item_id=f"probe-{index}",
            input_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            text=text,
        )
        for index, text in enumerate(probe_texts, start=1)
    ]
    client = EmbeddingClient(
        api_key=key,
        api_base=config.EMBEDDING_API_BASE,
        model=config.EMBEDDING_MODEL,
        dimensions=config.EMBEDDING_DIMENSIONS,
        batch_size=config.EMBEDDING_BATCH_SIZE,
    )
    result = embed_with_cache(
        client,
        items,
        provider=config.EMBEDDING_PROVIDER,
        model=config.EMBEDDING_MODEL,
        dimensions=config.EMBEDDING_DIMENSIONS,
        job_type="live_probe",
        context_quality="probe",
    )
    summary.update(
        {
            "network_called": result.requested_items > 0,
            "job_id": result.job_id,
            "vectors": len(result.vectors),
            "cache_hits": result.cache_hits,
            "requested_items": result.requested_items,
            "actual_tokens": result.actual_tokens,
        }
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_embedding_plan(args: argparse.Namespace) -> None:
    """Build a no-network Method embedding scope and cost estimate."""
    from analysis.embedding_inputs import build_embedding_plan
    from db.schema import init_db

    if not args.dry_run:
        raise SystemExit("Phase A embedding-plan requires --dry-run")
    init_db()
    errors = config.validate_embedding_config()
    if errors:
        raise SystemExit("; ".join(errors))
    plan = build_embedding_plan(limit=args.limit)
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))


def _require_live_embedding() -> str:
    errors = config.validate_embedding_config()
    if errors:
        raise SystemExit("; ".join(errors))
    if not config.EMBEDDING_ENABLED:
        raise SystemExit("Set EMBEDDING_ENABLED=1 before external Embedding calls")
    key, _ = config.embedding_key_and_source()
    if not key:
        raise SystemExit("A Bailian embedding API key is required")
    return key


def cmd_method_family_init(args: argparse.Namespace) -> None:
    from analysis.embedding_client import EmbeddingClient
    from analysis.method_taxonomy import ensure_prototype_centroids, sync_family_catalog
    from db.schema import init_db

    init_db()
    count = sync_family_catalog()
    result: dict = {"families": count, "taxonomy_version": config.METHOD_TAXONOMY_VERSION}
    if args.embed_prototypes:
        key = _require_live_embedding()
        client = EmbeddingClient(api_key=key)
        centroids, embedding_stats = ensure_prototype_centroids(client)
        result.update(embedding_stats)
        result["centroids"] = len(centroids)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_shadow(args: argparse.Namespace) -> None:
    from analysis.embedding_client import EmbeddingClient, EmbeddingItem
    from analysis.embedding_inputs import load_method_embedding_inputs
    from analysis.embedding_service import embed_with_cache
    from analysis.method_taxonomy import (
        ensure_prototype_centroids,
        load_prototype_centroids_from_cache,
        shadow_classify_cached_methods,
        sync_family_catalog,
    )
    from db.schema import init_db

    init_db()
    sync_family_catalog()
    inputs = load_method_embedding_inputs(limit=args.limit)
    prototype_stats: dict = {}
    if args.sync:
        key = _require_live_embedding()
        client = EmbeddingClient(api_key=key)
        centroids, prototype_stats = ensure_prototype_centroids(client)
        method_items = [
            EmbeddingItem(
                item_id=str(item.method_entity_id),
                input_sha256=item.input_sha256,
                text=item.text,
            )
            for item in inputs
        ]
        method_result = embed_with_cache(
            client,
            method_items,
            provider=config.EMBEDDING_PROVIDER,
            model=config.EMBEDDING_MODEL,
            dimensions=config.EMBEDDING_DIMENSIONS,
            job_type="method_shadow_sync",
            item_type="method",
            context_quality="mixed",
        )
        prototype_stats["method_job_id"] = method_result.job_id
        prototype_stats["method_cache_hits"] = method_result.cache_hits
        prototype_stats["method_requested_items"] = method_result.requested_items
    else:
        centroids = load_prototype_centroids_from_cache()
        if not centroids:
            raise SystemExit("Prototype cache is incomplete; run method-family-init --embed-prototypes")
    summary = shadow_classify_cached_methods(inputs, centroids)
    summary["embedding"] = prototype_stats
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_batch(args: argparse.Namespace) -> None:
    from analysis.embedding_batch import BailianEmbeddingBatch
    from analysis.embedding_inputs import load_method_embedding_inputs
    from analysis.embedding_store import cached_hashes
    from analysis.method_taxonomy import (
        load_prototype_centroids_from_cache,
        shadow_classify_cached_methods,
        sync_family_catalog,
    )
    from db.schema import init_db

    init_db()
    key = _require_live_embedding()
    client = BailianEmbeddingBatch(api_key=key)
    if args.action == "submit":
        sync_family_catalog()
        inputs = load_method_embedding_inputs(limit=args.limit)
        hits = cached_hashes(
            [item.input_sha256 for item in inputs],
            provider=config.EMBEDDING_PROVIDER,
            model=config.EMBEDDING_MODEL,
            dimensions=config.EMBEDDING_DIMENSIONS,
        )
        missing = [item for item in inputs if item.input_sha256 not in hits]
        result = client.submit(missing)
    elif args.action == "status":
        if not args.job_id:
            raise SystemExit("--job-id is required for status")
        result = client.status(args.job_id)
    else:
        if not args.job_id:
            raise SystemExit("--job-id is required for ingest")
        result = client.ingest(args.job_id, cleanup_remote_files=not args.keep_remote_files)
        centroids = load_prototype_centroids_from_cache()
        if not centroids:
            raise SystemExit("Batch was ingested, but prototype cache is incomplete")
        inputs = load_method_embedding_inputs(limit=args.limit)
        result["classification"] = shadow_classify_cached_methods(inputs, centroids)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_gold_export(args: argparse.Namespace) -> None:
    from analysis.method_taxonomy import export_gold_template
    from db.schema import init_db

    init_db()
    output = args.output or str(
        Path(config.OUTPUT_DIR) / f"method_family_gold_{config.METHOD_TAXONOMY_VERSION}.csv"
    )
    result = export_gold_template(output, size=args.size)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_gold_validate(args: argparse.Namespace) -> None:
    from analysis.method_family_gold import (
        GoldValidationError,
        assign_deterministic_split,
        gold_summary,
        load_and_validate_gold_csv,
    )

    try:
        validation = assign_deterministic_split(
            load_and_validate_gold_csv(
                args.input,
                expected_sha256=args.expected_sha256,
                expected_rows=args.expected_rows,
            )
        )
    except (GoldValidationError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(gold_summary(validation), ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_gold_import(args: argparse.Namespace) -> None:
    from analysis.method_family_gold import GoldValidationError, import_gold_set
    from db.schema import init_db

    init_db()
    try:
        result = import_gold_set(
            args.input,
            reviewer=args.reviewer,
            expected_sha256=args.expected_sha256,
            expected_rows=args.expected_rows,
        )
    except (GoldValidationError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_calibrate(args: argparse.Namespace) -> None:
    from analysis.method_family_gold import calibrate_gold_set
    from db.schema import init_db

    init_db()
    output = args.output or str(
        Path(config.OUTPUT_DIR) / f"method_family_calibration_{args.gold_set_id}.json"
    )
    try:
        result = calibrate_gold_set(args.gold_set_id, output_path=output)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    result["output"] = str(Path(output).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_rules_evaluate(args: argparse.Namespace) -> None:
    from analysis.method_family_rules import evaluate_and_freeze_ruleset
    from db.schema import init_db

    init_db()
    output = args.output or str(
        Path(config.OUTPUT_DIR) / f"method_family_rules_{args.gold_set_id}.json"
    )
    try:
        result = evaluate_and_freeze_ruleset(args.gold_set_id, output_path=output)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    result["output"] = str(Path(output).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_policy_preview(args: argparse.Namespace) -> None:
    from analysis.method_family_rules import build_policy_preview
    from db.schema import init_db

    init_db()
    output = args.output or str(
        Path(config.OUTPUT_DIR) / f"method_family_policy_preview_{args.gold_set_id}.json"
    )
    try:
        result = build_policy_preview(
            args.gold_set_id,
            args.calibration_id,
            args.ruleset_id,
            output_path=output,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    result["output"] = str(Path(output).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_review_queue(args: argparse.Namespace) -> None:
    from analysis.method_family_review_queue import build_coverage_review_queue
    from db.schema import init_db

    init_db()
    output = args.output or str(
        Path(config.OUTPUT_DIR) / f"method_family_review_queue_{args.gold_set_id}.csv"
    )
    report_output = args.report_output or str(Path(output).with_suffix(".json"))
    try:
        result = build_coverage_review_queue(
            args.gold_set_id,
            args.calibration_id,
            args.ruleset_id,
            output_path=output,
            report_output_path=report_output,
            target_paper_coverage=args.target_paper_coverage,
            max_rows=args.max_rows,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    result["output"] = str(Path(output).resolve())
    result["report_output"] = str(Path(report_output).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_gold_extension_import(args: argparse.Namespace) -> None:
    from analysis.method_family_review_queue import (
        CoverageGoldValidationError,
        import_coverage_gold_extension,
    )
    from db.schema import init_db

    init_db()
    output = args.output or str(
        Path(config.OUTPUT_DIR)
        / f"method_family_gold_extension_{args.queue_id}_{args.rank_start}-{args.rank_end}.json"
    )
    try:
        result = import_coverage_gold_extension(
            args.input,
            queue_id=args.queue_id,
            reviewer=args.reviewer,
            rank_start=args.rank_start,
            rank_end=args.rank_end,
            expected_sha256=args.expected_sha256,
            output_path=output,
        )
    except (CoverageGoldValidationError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    result["output"] = str(Path(output).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_blind_export(args: argparse.Namespace) -> None:
    from analysis.method_family_blind import export_blind_set
    from db.schema import init_db

    init_db()
    output = args.output or str(
        Path(config.OUTPUT_DIR) / f"method_family_blind_{config.METHOD_TAXONOMY_VERSION}.csv"
    )
    try:
        result = export_blind_set(
            args.gold_set_id,
            output_path=output,
            size=args.size,
            generation=args.generation,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_blind_import(args: argparse.Namespace) -> None:
    from analysis.method_family_blind import BlindValidationError, import_blind_submission
    from db.schema import init_db

    init_db()
    try:
        result = import_blind_submission(
            args.input,
            blind_set_id=args.blind_set_id,
            reviewer=args.reviewer,
            expected_sha256=args.expected_sha256,
            output_path=args.output,
        )
    except (BlindValidationError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_blind_promote(args: argparse.Namespace) -> None:
    from analysis.method_family_supervised import promote_blind_evaluation
    from db.schema import init_db

    init_db()
    try:
        result = promote_blind_evaluation(
            args.evaluation_id,
            promoted_by=args.promoted_by,
            output_path=args.output,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_model_train(args: argparse.Namespace) -> None:
    from analysis.method_family_supervised import train_supervised_model
    from db.schema import init_db

    init_db()
    try:
        result = train_supervised_model(
            args.gold_set_id,
            args.ruleset_id,
            output_path=args.output,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_model_preview(args: argparse.Namespace) -> None:
    from analysis.method_family_supervised import preview_production_coverage
    from db.schema import init_db

    init_db()
    try:
        result = preview_production_coverage(args.model_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_blind_evaluate(args: argparse.Namespace) -> None:
    from analysis.method_family_supervised import evaluate_blind_submission
    from db.schema import init_db

    init_db()
    try:
        result = evaluate_blind_submission(
            args.model_id,
            args.submission_id,
            output_path=args.output,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_release_build(args: argparse.Namespace) -> None:
    from analysis.method_family_supervised import build_release
    from db.schema import init_db

    init_db()
    try:
        result = build_release(
            args.model_id,
            args.evaluation_id,
            manual_override=args.manual_override,
            approved_by=args.approved_by,
            approval_reason=args.approval_reason,
            minimum_paper_coverage=args.minimum_paper_coverage,
            output_path=args.output,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_method_family_release_activate(args: argparse.Namespace) -> None:
    from analysis.method_family_supervised import activate_release
    from db.schema import init_db

    init_db()
    try:
        result = activate_release(args.release_id, activated_by=args.activated_by)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_backfill_date_precision(args: argparse.Namespace) -> None:
    from db.schema import init_db
    from fetcher.pubmed_fetcher import backfill_date_precision

    init_db()
    result = backfill_date_precision(limit=args.limit)
    print(
        f"[Backfill-DatePrecision] pending={result['pending']} "
        f"updated={result['updated']} failed={result['failed']}"
    )


def cmd_backfill_method_roles(args: argparse.Namespace) -> None:
    from analysis.method_role import backfill_method_roles
    from db.schema import init_db

    init_db()
    counts = backfill_method_roles(force=args.force)
    roles = ("backbone", "aggregator", "classical_ml", "tool", "unknown")
    total = sum(counts.get(role, 0) for role in roles)
    unknown_rate = counts.get("unknown", 0) / total if total else 0.0
    formatted_counts = " ".join(f"{role}={counts.get(role, 0)}" for role in roles)
    print(
        f"[Backfill-MethodRoles] total={total} {formatted_counts} "
        f"unknown_rate={unknown_rate:.1%} force={args.force}"
    )


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
    from feasibility.landscape import bootstrap_landscape

    init_db()
    result = bootstrap_landscape(force=args.force)
    if result.get("skipped"):
        print(f"[Bootstrap] Skipped: {result['reason']} ({result['disease_count']} diseases)")
    elif result.get("api_error") and result.get("loaded", 0) == 0:
        kept = result.get("kept_existing")
        host = result.get("host") or "pathology API"
        print(f"[Bootstrap] Loaded 0 diseases (API error).")
        if kept:
            print(
                f"[Bootstrap] Kept existing cache: {landscape_count()} diseases "
                "(not cleared because reload failed)."
            )
        else:
            print(f"[Bootstrap] {result['api_error']}")
            print(
                f"[Bootstrap] Tip: verify network/VPN/DNS can resolve {host}, then retry."
            )
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
        use_ops_memory=not args.no_ops_memory,
        persist_ops_memory=not args.no_ops_persist,
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
    print(f"  papers_in_window : {payload.get('papers_in_window', payload['papers_ingested'])}")
    print(f"  excluded_year    : {payload.get('papers_excluded_low_precision', 0)}")
    print(f"  time_axis        : {payload.get('time_axis', 'pub_date')}")
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
    print(
        f"  papers_in_window={payload.get('papers_in_window', payload['papers_ingested'])}, "
        f"week={payload['week_id']}, axis={payload.get('time_axis', 'pub_date')}"
    )
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


def cmd_task_quality_audit(args: argparse.Namespace) -> None:
    import os
    from datetime import datetime

    from analysis.task_quality import run_task_quality_audit
    from db.schema import init_db

    init_db()
    limit = args.limit if args.limit is not None else 20
    report = run_task_quality_audit(limit_examples=limit)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out = args.output or os.path.join(
        config.OUTPUT_DIR,
        f"task_quality_audit_{datetime.now().strftime('%Y%m%d')}.md",
    )
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    # stdout summary counts
    print(f"[Task-Quality-Audit] Saved to {out}")
    for line in report.splitlines():
        if line.startswith("| reject |") or line.startswith("| weak |") or line.startswith("| ok |"):
            print(f"  {line.strip()}")
        if line.startswith("**Total Task entities:**"):
            print(f"  {line.strip()}")
        if line.startswith("- Papers with PERFORMS_TASK:"):
            print(f"  {line.strip()}")


def cmd_method_cluster_audit(args: argparse.Namespace) -> None:
    import os
    from datetime import datetime

    from analysis.method_synonyms import run_method_cluster_audit
    from db.schema import init_db

    init_db()
    report = run_method_cluster_audit(limit=args.limit)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out = args.output or os.path.join(
        config.OUTPUT_DIR,
        f"method_cluster_audit_{datetime.now().strftime('%Y%m%d')}.md",
    )
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[Method-Cluster-Audit] Saved to {out}")
    for line in report.splitlines():
        if line.startswith("- Method entities:") or line.startswith("- Suggested candidates shown:"):
            print(f"  {line}")


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

    p_embedding_preflight = sub.add_parser(
        "embedding-preflight",
        help="Validate Bailian embedding configuration (offline by default)",
    )
    p_embedding_preflight.add_argument(
        "--live-probe",
        action="store_true",
        help="Explicitly send two fixed public test strings to Bailian",
    )

    p_embedding_plan = sub.add_parser(
        "embedding-plan",
        help="Estimate active Method embedding scope, cache hits, and cost",
    )
    p_embedding_plan.add_argument(
        "--dry-run",
        action="store_true",
        help="Required in Phase A; never calls the external API",
    )
    p_embedding_plan.add_argument(
        "--only-active",
        action="store_true",
        help="Use active APPLIES_METHOD entities (the only Phase A scope)",
    )
    p_embedding_plan.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit Methods by stable entity-id order (testing only)",
    )

    p_family_init = sub.add_parser(
        "method-family-init",
        help="Initialize the versioned 13-family taxonomy and optional prototypes",
    )
    p_family_init.add_argument(
        "--embed-prototypes",
        action="store_true",
        help="Embed curated family descriptions/seeds using Bailian",
    )

    p_family_shadow = sub.add_parser(
        "method-family-shadow",
        help="Write top-k family candidates as review-only shadow assignments",
    )
    p_family_shadow.add_argument("--limit", type=int, default=None)
    p_family_shadow.add_argument(
        "--sync",
        action="store_true",
        help="Synchronously embed missing inputs (use only for a small sample)",
    )

    p_family_batch = sub.add_parser(
        "method-family-batch",
        help="Submit, inspect, or ingest a Bailian Batch shadow backfill",
    )
    p_family_batch.add_argument("action", choices=("submit", "status", "ingest"))
    p_family_batch.add_argument("--job-id", default=None)
    p_family_batch.add_argument("--limit", type=int, default=None)
    p_family_batch.add_argument(
        "--keep-remote-files",
        action="store_true",
        help="Keep the created Bailian input/output files after successful ingest",
    )

    p_family_gold = sub.add_parser(
        "method-family-gold-export",
        help="Export a deterministic stratified CSV for human family labels",
    )
    p_family_gold.add_argument("--size", type=int, default=400)
    p_family_gold.add_argument("--output", "-o", default=None)

    p_family_gold_validate = sub.add_parser(
        "method-family-gold-validate",
        help="Validate and preview the immutable Gold normalization/split",
    )
    p_family_gold_validate.add_argument("--input", required=True)
    p_family_gold_validate.add_argument("--expected-sha256", default=None)
    p_family_gold_validate.add_argument("--expected-rows", type=int, default=400)

    p_family_gold_import = sub.add_parser(
        "method-family-gold-import",
        help="Idempotently import a validated Gold CSV and deterministic split",
    )
    p_family_gold_import.add_argument("--input", required=True)
    p_family_gold_import.add_argument("--reviewer", required=True)
    p_family_gold_import.add_argument("--expected-sha256", default=None)
    p_family_gold_import.add_argument("--expected-rows", type=int, default=400)

    p_family_calibrate = sub.add_parser(
        "method-family-calibrate",
        help="Create an immutable offline embedding threshold report",
    )
    p_family_calibrate.add_argument("--gold-set-id", required=True)
    p_family_calibrate.add_argument("--output", "-o", default=None)

    p_family_rules = sub.add_parser(
        "method-family-rules-evaluate",
        help="Evaluate strict name rules on Gold calibration/holdout and freeze the report",
    )
    p_family_rules.add_argument("--gold-set-id", required=True)
    p_family_rules.add_argument("--output", "-o", default=None)

    p_family_preview = sub.add_parser(
        "method-family-policy-preview",
        help="Preview Gold > strict rule > calibrated embedding coverage without accepting rows",
    )
    p_family_preview.add_argument("--gold-set-id", required=True)
    p_family_preview.add_argument("--calibration-id", required=True)
    p_family_preview.add_argument("--ruleset-id", required=True)
    p_family_preview.add_argument("--output", "-o", default=None)

    p_family_queue = sub.add_parser(
        "method-family-review-queue",
        help="Export a greedy manual-label queue that maximizes uncovered paper coverage",
    )
    p_family_queue.add_argument("--gold-set-id", required=True)
    p_family_queue.add_argument("--calibration-id", required=True)
    p_family_queue.add_argument("--ruleset-id", required=True)
    p_family_queue.add_argument("--target-paper-coverage", type=float, default=0.80)
    p_family_queue.add_argument("--max-rows", type=int, default=2000)
    p_family_queue.add_argument("--output", "-o", default=None)
    p_family_queue.add_argument("--report-output", default=None)

    p_family_extension = sub.add_parser(
        "method-family-gold-extension-import",
        help="Validate and immutably import an annotated review-queue rank range",
    )
    p_family_extension.add_argument("--input", required=True)
    p_family_extension.add_argument("--queue-id", required=True)
    p_family_extension.add_argument("--reviewer", required=True)
    p_family_extension.add_argument("--rank-start", type=int, default=1)
    p_family_extension.add_argument("--rank-end", type=int, required=True)
    p_family_extension.add_argument("--expected-sha256", default=None)
    p_family_extension.add_argument("--output", "-o", default=None)

    p_family_blind_export = sub.add_parser(
        "method-family-blind-export",
        help="Freeze an independent stratified blind set without visible model suggestions",
    )
    p_family_blind_export.add_argument("--gold-set-id", required=True)
    p_family_blind_export.add_argument("--size", type=int, default=200)
    p_family_blind_export.add_argument("--generation", type=int, default=1)
    p_family_blind_export.add_argument("--output", "-o", default=None)

    p_family_blind_import = sub.add_parser(
        "method-family-blind-import",
        help="Validate and freeze a complete independent blind-label submission",
    )
    p_family_blind_import.add_argument("--input", required=True)
    p_family_blind_import.add_argument("--blind-set-id", required=True)
    p_family_blind_import.add_argument("--reviewer", required=True)
    p_family_blind_import.add_argument("--expected-sha256", default=None)
    p_family_blind_import.add_argument("--output", "-o", default=None)

    p_family_blind_promote = sub.add_parser(
        "method-family-blind-promote",
        help="Retire a completed blind evaluation into future training data",
    )
    p_family_blind_promote.add_argument("--evaluation-id", required=True)
    p_family_blind_promote.add_argument("--promoted-by", required=True)
    p_family_blind_promote.add_argument("--output", "-o", default=None)

    p_family_model_train = sub.add_parser(
        "method-family-model-train",
        help="Train a deterministic local supervised classifier from Gold and extensions",
    )
    p_family_model_train.add_argument("--gold-set-id", required=True)
    p_family_model_train.add_argument("--ruleset-id", required=True)
    p_family_model_train.add_argument("--output", "-o", default=None)

    p_family_model_preview = sub.add_parser(
        "method-family-model-preview",
        help="Read-only production coverage preview for a trained model",
    )
    p_family_model_preview.add_argument("--model-id", required=True)

    p_family_blind_evaluate = sub.add_parser(
        "method-family-blind-evaluate",
        help="Evaluate a frozen model on an imported independent blind submission",
    )
    p_family_blind_evaluate.add_argument("--model-id", required=True)
    p_family_blind_evaluate.add_argument("--submission-id", required=True)
    p_family_blind_evaluate.add_argument("--output", "-o", default=None)

    p_family_release_build = sub.add_parser(
        "method-family-release-build",
        help="Build an immutable release after the blind gate has passed",
    )
    p_family_release_build.add_argument("--model-id", required=True)
    p_family_release_build.add_argument("--evaluation-id", required=True)
    p_family_release_build.add_argument(
        "--manual-override",
        action="store_true",
        help="Allow an explicitly approved release when the blind gate is waived",
    )
    p_family_release_build.add_argument("--approved-by", default=None)
    p_family_release_build.add_argument("--approval-reason", default=None)
    p_family_release_build.add_argument(
        "--minimum-paper-coverage", type=float, default=0.80
    )
    p_family_release_build.add_argument("--output", "-o", default=None)

    p_family_release_activate = sub.add_parser(
        "method-family-release-activate",
        help="Activate a validated immutable Method-family release",
    )
    p_family_release_activate.add_argument("--release-id", required=True)
    p_family_release_activate.add_argument("--activated-by", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch PubMed, Europe PMC and arXiv metadata")
    p_fetch.add_argument("--no-resume", action="store_true")
    p_fetch.add_argument("--sources", default=config.LITERATURE_SOURCES,
                         help="Comma-separated: pubmed,europepmc,arxiv")
    p_fetch.add_argument("--group", default=None,
                         help="Restrict Europe PMC/arXiv to one enabled query group")
    p_fetch.add_argument("--source-limit-per-group", type=int, default=None,
                         help="Cap Europe PMC/arXiv results per group (smoke tests)")
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

    p_ft = sub.add_parser(
        "fetch-fulltext",
        help="Fetch full text: JATS → PDF/MinerU fallback (retries cooled-down unavailable)",
    )
    p_ft.add_argument(
        "--no-retry",
        action="store_true",
        help="Do not requeue unavailable/jats_unavailable; only process pending",
    )
    p_ft.add_argument(
        "--force-retry",
        action="store_true",
        help="Requeue all unavailable/jats_unavailable ignoring cooldown",
    )
    p_ft.add_argument(
        "--pdf-retry-limit",
        type=int,
        default=None,
        help="Max PDF/MinerU attempts this run (default: config FULLTEXT_PDF_RETRY_LIMIT; 0=unlimited)",
    )
    p_ft.add_argument(
        "--skip-pdf",
        action="store_true",
        help="Skip Tier 2 ScanSci PDF + MinerU (JATS only; leave jats_unavailable deferred)",
    )

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
    p_ext.add_argument(
        "--pmid-list",
        type=str,
        default=None,
        help="Text file, one PMID per line",
    )
    p_ext.add_argument(
        "--force-reextract",
        action="store_true",
        help="Clear relations/bindings for target PMIDs before Pass1+2",
    )
    p_ext.add_argument(
        "--upgrade-reextract",
        action="store_true",
        help="Force enable abstract→fulltext upgrade clear+reextract",
    )
    p_ext.add_argument(
        "--no-upgrade-reextract",
        action="store_true",
        help="Disable abstract→fulltext upgrade clear+reextract for this run",
    )

    p_reconcile = sub.add_parser(
        "reconcile",
        help="Pass-2 fulltext reconcile only (requires Pass1)",
    )
    p_reconcile.add_argument(
        "--pmid-list",
        type=str,
        default=None,
        help="Text file, one PMID per line (default: pending/failed with fulltext)",
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
        help="Compute recent-publication research hotspots (stdout summary)",
    )
    p_hotspot.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"Recent publication window in days (default: {config.HOTSPOT_WINDOW_DAYS})",
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
        help=f"Recent publication window (default: {config.HOTSPOT_WINDOW_DAYS})",
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

    p_task_audit = sub.add_parser(
        "task-quality-audit",
        help="Read-only Task entity quality audit (markdown report)",
    )
    p_task_audit.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path (default: output/task_quality_audit_{YYYYMMDD}.md)",
    )
    p_task_audit.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max examples per tier in the report (default: 20)",
    )

    p_method_audit = sub.add_parser(
        "method-cluster-audit",
        help="Read-only Method synonym cluster audit (markdown report)",
    )
    p_method_audit.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path (default: output/method_cluster_audit_{YYYYMMDD}.md)",
    )
    p_method_audit.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max near-duplicate candidates in the report (default: 50)",
    )

    p_debate = sub.add_parser("gap-debate", help="LLM debate multi-agent gap analysis")
    p_debate.add_argument("--focus", "-f", default=None)
    p_debate.add_argument("--top", "-n", type=int, default=6)
    p_debate.add_argument("--rounds", "-r", type=int, default=2)
    p_debate.add_argument("--output", "-o", default=None)
    p_debate.add_argument("--verbose", "-v", action="store_true")
    p_debate.add_argument(
        "--resume-session",
        default=None,
        help="Resume an incomplete debate from its persisted session checkpoint",
    )
    p_debate.add_argument(
        "--no-ops-memory",
        action="store_true",
        help="Do not inject ops memory into debate prompts",
    )
    p_debate.add_argument(
        "--no-ops-persist",
        action="store_true",
        help="Do not write ops_* rows after debate",
    )

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
    p_pipeline.add_argument(
        "--no-ops-memory",
        action="store_true",
        help="Do not inject ops memory into debate prompts",
    )
    p_pipeline.add_argument(
        "--no-ops-persist",
        action="store_true",
        help="Do not write ops_* rows after debate/proposals",
    )

    sub.add_parser("stats", help="Print database statistics")

    p_backfill_dp = sub.add_parser(
        "backfill-date-precision",
        help="Re-fetch PubMed dates for papers missing date_precision",
    )
    p_backfill_dp.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max papers to backfill (0 = all missing)",
    )

    p_backfill_roles = sub.add_parser(
        "backfill-method-roles",
        help="Classify and persist roles for Method entities",
    )
    p_backfill_roles.add_argument(
        "--force",
        action="store_true",
        help="Overwrite hint-derived roles even when rules classify them as unknown",
    )

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
        "embedding-preflight": cmd_embedding_preflight,
        "embedding-plan": cmd_embedding_plan,
        "method-family-init": cmd_method_family_init,
        "method-family-shadow": cmd_method_family_shadow,
        "method-family-batch": cmd_method_family_batch,
        "method-family-gold-export": cmd_method_family_gold_export,
        "method-family-gold-validate": cmd_method_family_gold_validate,
        "method-family-gold-import": cmd_method_family_gold_import,
        "method-family-calibrate": cmd_method_family_calibrate,
        "method-family-rules-evaluate": cmd_method_family_rules_evaluate,
        "method-family-policy-preview": cmd_method_family_policy_preview,
        "method-family-review-queue": cmd_method_family_review_queue,
        "method-family-gold-extension-import": cmd_method_family_gold_extension_import,
        "method-family-blind-export": cmd_method_family_blind_export,
        "method-family-blind-import": cmd_method_family_blind_import,
        "method-family-blind-promote": cmd_method_family_blind_promote,
        "method-family-model-train": cmd_method_family_model_train,
        "method-family-model-preview": cmd_method_family_model_preview,
        "method-family-blind-evaluate": cmd_method_family_blind_evaluate,
        "method-family-release-build": cmd_method_family_release_build,
        "method-family-release-activate": cmd_method_family_release_activate,
        "fetch": cmd_fetch,
        "enrich-s2": cmd_enrich_s2,
        "import-if": cmd_import_if,
        "fetch-fulltext": cmd_fetch_fulltext,
        "extract": cmd_extract,
        "reconcile": cmd_reconcile,
        "build": cmd_build,
        "viz": cmd_viz,
        "analyze": cmd_analyze,
        "compute-gap-lifecycle": cmd_compute_gap_lifecycle,
        "compute-weekly-hotspots": cmd_compute_weekly_hotspots,
        "hotspot-report": cmd_hotspot_report,
        "hotspot-brief": cmd_hotspot_brief,
        "task-quality-audit": cmd_task_quality_audit,
        "method-cluster-audit": cmd_method_cluster_audit,
        "gap-debate": cmd_gap_debate,
        "bootstrap-landscape": cmd_bootstrap_landscape,
        "idea-pipeline": cmd_idea_pipeline,
        "stats": cmd_stats,
        "backfill-date-precision": cmd_backfill_date_precision,
        "backfill-method-roles": cmd_backfill_method_roles,
        "watch-fetch": cmd_watch_fetch,
        "run-all": cmd_run_all,
        "run-db": cmd_run_db,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
