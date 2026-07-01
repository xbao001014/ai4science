"""Compare JATS vs PyMuPDF vs MinerU PDF extraction channels."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from compare_test.baseline_loader import (  # noqa: E402
    get_extracted_papers,
    load_jats_triples,
    summarize_triples,
)
from compare_test.config import (  # noqa: E402
    COMPARISON_JSON,
    COMPARISON_JSON_MINERU,
    COMPARISON_REPORT,
    COMPARISON_REPORT_MINERU,
    DEFAULT_PAPER_LIMIT,
    MINERU_BACKEND,
    MINERU_LANG,
)
from compare_test.mineru_extractor import extract_from_mineru_pdf  # noqa: E402
from compare_test.pdf_extractor import extract_from_pdf  # noqa: E402
from compare_test.pdf_fetcher import download_batch, load_manifest  # noqa: E402


def _entity_key(t: dict[str, Any]) -> tuple[str, str, str]:
    return (
        t.get("relation", ""),
        t.get("object_name", "").lower().strip(),
        t.get("object_type", ""),
    )


def _jaccard(a: list[dict], b: list[dict]) -> dict[str, Any]:
    keys_a = {_entity_key(t) for t in a}
    keys_b = {_entity_key(t) for t in b}
    overlap = keys_a & keys_b
    union = keys_a | keys_b
    return {
        "shared": len(overlap),
        "only_a": len(keys_a - keys_b),
        "only_b": len(keys_b - keys_a),
        "jaccard": round(len(overlap) / len(union), 4) if union else 0.0,
    }


def _compare_paper_three_way(
    paper: dict[str, Any],
    jats_triples: list[dict[str, Any]],
    pymupdf_triples: list[dict[str, Any]] | None,
    mineru_triples: list[dict[str, Any]] | None,
    download_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    jats_sum = summarize_triples(jats_triples)
    pymupdf_sum = summarize_triples(pymupdf_triples or [])
    mineru_sum = summarize_triples(mineru_triples or [])

    return {
        "pmid": paper["pmid"],
        "doi": paper.get("doi"),
        "title": (paper.get("title") or "")[:120],
        "jats_fulltext": paper.get("full_text_status") == "available",
        "pdf_download": {
            "success": bool(download_entry and download_entry.get("success")),
            "source": (download_entry or {}).get("source", ""),
            "file": (download_entry or {}).get("file", ""),
            "reason": (download_entry or {}).get("reason", ""),
        },
        "jats_summary": jats_sum,
        "pymupdf_summary": pymupdf_sum,
        "mineru_summary": mineru_sum,
        "overlap_jats_pymupdf": _jaccard(jats_triples, pymupdf_triples or []),
        "overlap_jats_mineru": _jaccard(jats_triples, mineru_triples or []),
        "overlap_pymupdf_mineru": _jaccard(pymupdf_triples or [], mineru_triples or []),
    }


def _format_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def generate_report_three_way(comparisons: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    n = len(comparisons)
    pdf_ok = sum(1 for c in comparisons if c["pdf_download"]["success"])
    mineru_ok = sum(
        1 for c in comparisons if c["pdf_download"]["success"] and c["mineru_summary"]["triple_count"] > 0
    )

    avg = lambda key: sum(c[key]["triple_count"] for c in comparisons) / max(n, 1)
    avg_jats = avg("jats_summary")
    avg_pymupdf = avg("pymupdf_summary")
    avg_mineru = avg("mineru_summary")

    pdf_papers = [c for c in comparisons if c["pdf_download"]["success"]]
    def mean_jaccard(field: str) -> float:
        if not pdf_papers:
            return 0.0
        return sum(c[field]["jaccard"] for c in pdf_papers) / len(pdf_papers)

    lines = [
        "# JATS vs PyMuPDF vs MinerU — Extraction Comparison",
        "",
        f"_Generated: {now}_",
        "",
        "## Run Configuration",
        "",
        f"- Papers compared: **{n}** (JATS fulltext extracted in main workflow)",
        f"- PDF download: ScanSci `oa_first` (Sci-Hub disabled)",
        f"- PyMuPDF: plain text + regex section split",
        f"- MinerU: backend `{meta.get('mineru_backend', 'pipeline')}`, lang `{meta.get('mineru_lang', 'en')}`",
        f"- Isolated output: `fulltext_workflow/compare_test/` (no main DB changes)",
        "",
        "## Aggregate Summary",
        "",
        "| Metric | JATS (PMC XML) | PyMuPDF | MinerU |",
        "|--------|----------------|---------|--------|",
        f"| Full text / parsed | {n}/{n} | {pdf_ok}/{n} PDF | {mineru_ok}/{n} parsed |",
        f"| Avg triples/paper | {avg_jats:.1f} | {avg_pymupdf:.1f} | {avg_mineru:.1f} |",
        f"| Avg lim/paper | {sum(c['jats_summary']['limitation_count'] for c in comparisons)/n:.1f} | "
        f"{sum(c['pymupdf_summary']['limitation_count'] for c in comparisons)/n:.1f} | "
        f"{sum(c['mineru_summary']['limitation_count'] for c in comparisons)/n:.1f} |",
        f"| Jaccard vs JATS (PDF ok) | — | {mean_jaccard('overlap_jats_pymupdf'):.3f} | "
        f"{mean_jaccard('overlap_jats_mineru'):.3f} |",
        f"| Jaccard PyMuPDF vs MinerU | — | — | {mean_jaccard('overlap_pymupdf_mineru'):.3f} |",
        "",
        "## Per-Paper Comparison",
        "",
    ]

    rows = []
    for c in comparisons:
        dl = c["pdf_download"]
        rows.append(
            [
                c["pmid"],
                c["jats_summary"]["triple_count"],
                c["pymupdf_summary"]["triple_count"],
                c["mineru_summary"]["triple_count"],
                "Y" if dl["success"] else "N",
                c["jats_summary"]["limitation_count"],
                c["pymupdf_summary"]["limitation_count"],
                c["mineru_summary"]["limitation_count"],
                f"{c['overlap_jats_pymupdf']['jaccard']:.2f}",
                f"{c['overlap_jats_mineru']['jaccard']:.2f}",
            ]
        )

    lines.append(
        _format_table(
            [
                "PMID",
                "JATS",
                "PyMuPDF",
                "MinerU",
                "PDF?",
                "J lim",
                "Py lim",
                "M lim",
                "J∩Py",
                "J∩M",
            ],
            rows,
        )
    )

    # MinerU uplift over PyMuPDF (PDF-ok papers only)
    lines.extend(["", "## MinerU vs PyMuPDF Uplift (PDF downloaded only)", ""])
    uplift_rows = []
    for c in pdf_papers:
        py_n = c["pymupdf_summary"]["triple_count"]
        m_n = c["mineru_summary"]["triple_count"]
        delta = m_n - py_n
        pct = (delta / py_n * 100) if py_n else (100.0 if m_n else 0.0)
        uplift_rows.append([c["pmid"], py_n, m_n, delta, f"{pct:+.0f}%"])
    lines.append(_format_table(["PMID", "PyMuPDF", "MinerU", "Δ triples", "Δ%"], uplift_rows))

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- **JATS** = Europe PMC structured XML (baseline).",
            "- **PyMuPDF** = ScanSci PDF + plain text + regex sections.",
            "- **MinerU** = same PDF + layout-aware Markdown + heading split.",
            "- Jaccard compares (relation, entity_name, entity_type) tuples.",
            "- MinerU uplift reflects better PDF structure recovery, not LLM prompt changes.",
        ]
    )
    return "\n".join(lines)


def cmd_download(args: argparse.Namespace) -> None:
    papers = get_extracted_papers(limit=args.limit)
    print(f"[Download] {len(papers)} papers")
    stats = download_batch(papers, force=args.force)
    print(f"[Download] Done: {stats['succeeded']}/{stats['total']} PDFs")


def cmd_extract(args: argparse.Namespace) -> None:
    papers = get_extracted_papers(limit=args.limit)
    manifest = load_manifest()
    print(f"[Extract-PyMuPDF] {len(papers)} papers")
    for i, paper in enumerate(papers, 1):
        pmid = paper["pmid"]
        entry = manifest.get("papers", {}).get(pmid, {})
        if not entry.get("success"):
            print(f"  [{i}/{len(papers)}] PMID {pmid} — skip (no PDF)")
            continue
        print(f"  [{i}/{len(papers)}] PMID {pmid} — PyMuPDF extract")
        result = extract_from_pdf(pmid, paper.get("title") or "", entry["file"], force=args.force)
        print(f"           -> {result['section_count']} sec, {len(result['triples'])} triples")


def cmd_extract_mineru(args: argparse.Namespace) -> None:
    import os

    os.environ.setdefault("MINERU_MODEL_SOURCE", "modelscope")

    papers = get_extracted_papers(limit=args.limit)
    manifest = load_manifest()
    backend = args.backend or MINERU_BACKEND
    print(f"[Extract-MinerU] {len(papers)} papers (backend={backend})")
    for i, paper in enumerate(papers, 1):
        pmid = paper["pmid"]
        entry = manifest.get("papers", {}).get(pmid, {})
        if not entry.get("success"):
            print(f"  [{i}/{len(papers)}] PMID {pmid} — skip (no PDF)")
            continue
        print(f"  [{i}/{len(papers)}] PMID {pmid} — MinerU parse + LLM")
        try:
            result = extract_from_mineru_pdf(
                pmid,
                paper.get("title") or "",
                entry["file"],
                force=args.force,
                lang=MINERU_LANG,
                backend=backend,
            )
            print(
                f"           -> {result['section_count']} sec, "
                f"{len(result['triples'])} triples, {result['text_chars']} md chars"
            )
        except Exception as e:
            print(f"           -> ERROR: {e}")


def cmd_compare(args: argparse.Namespace) -> None:
    papers = get_extracted_papers(limit=args.limit)
    manifest = load_manifest()

    pymupdf_cache = _load_json_cache("pdf_extractions.json")
    mineru_cache = _load_json_cache("mineru_extractions.json")

    comparisons = []
    for paper in papers:
        pmid = paper["pmid"]
        jats = load_jats_triples(pmid)
        py_data = pymupdf_cache.get(pmid)
        m_data = mineru_cache.get(pmid)
        dl = manifest.get("papers", {}).get(pmid)
        comparisons.append(
            _compare_paper_three_way(
                paper,
                jats,
                py_data.get("triples") if py_data else None,
                m_data.get("triples") if m_data else None,
                dl,
            )
        )

    meta = {
        "strategy": "oa_first",
        "mineru_backend": MINERU_BACKEND,
        "mineru_lang": MINERU_LANG,
        "paper_limit": args.limit,
    }
    report = generate_report_three_way(comparisons, meta)

    Path(COMPARISON_REPORT_MINERU).parent.mkdir(parents=True, exist_ok=True)
    Path(COMPARISON_REPORT_MINERU).write_text(report, encoding="utf-8")
    Path(COMPARISON_JSON_MINERU).write_text(
        json.dumps({"meta": meta, "comparisons": comparisons}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[Compare] Report: {COMPARISON_REPORT_MINERU}")
    print(f"[Compare] JSON:   {COMPARISON_JSON_MINERU}")


def _load_json_cache(filename: str) -> dict[str, Any]:
    path = Path(__file__).parent / "cache" / filename
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f).get("papers", {})


def cmd_run_all(args: argparse.Namespace) -> None:
    cmd_download(args)
    cmd_extract(args)
    cmd_extract_mineru(args)
    cmd_compare(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="JATS vs PyMuPDF vs MinerU comparison")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--limit", type=int, default=DEFAULT_PAPER_LIMIT)
    common.add_argument("--force", action="store_true")

    sub.add_parser("download", parents=[common], help="Download PDFs via ScanSci").set_defaults(
        func=cmd_download
    )
    sub.add_parser("extract", parents=[common], help="LLM extract via PyMuPDF").set_defaults(
        func=cmd_extract
    )
    p_mineru = sub.add_parser("extract-mineru", parents=[common], help="MinerU parse + LLM")
    p_mineru.add_argument("--backend", default=None, help="MinerU backend (default: pipeline)")
    p_mineru.set_defaults(func=cmd_extract_mineru)
    sub.add_parser("compare", parents=[common], help="Three-way comparison report").set_defaults(
        func=cmd_compare
    )
    sub.add_parser("run-all", parents=[common], help="Full pipeline incl. MinerU").set_defaults(
        func=cmd_run_all
    )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
