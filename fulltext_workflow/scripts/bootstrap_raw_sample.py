"""Load N papers from raw/ fulltext caches into SQLite, then optionally extract.

Prefer JATS under raw/pmc_xml/; fall back to MinerU markdown under raw/mineru_output/.
Metadata is fetched from PubMed by PMID (efetch).

Example:
  python scripts/bootstrap_raw_sample.py --limit 30 --extract --core-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from db.schema import (
    db_stats,
    delete_paper_sections,
    init_db,
    insert_sections,
    mark_fulltext_status,
    upsert_paper,
)
from fetcher.mineru_parser import split_markdown_into_sections
from fetcher.pmc_fetcher import parse_pmc_jats
from fetcher.pubmed_fetcher import _fetch_batch


def _pmids_with_jats() -> list[str]:
    root = Path(config.RAW_PMC_DIR)
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.xml") if p.stem.isdigit())


def _pmids_with_mineru() -> list[str]:
    root = Path(config.MINERU_OUTPUT_DIR)
    if not root.is_dir():
        return []
    out: list[str] = []
    for d in root.iterdir():
        if not d.is_dir() or not d.name.isdigit():
            continue
        if list(d.glob("*.md")):
            out.append(d.name)
    return sorted(out)


def _load_jats_sections(pmid: str) -> list[dict] | None:
    path = Path(config.RAW_PMC_DIR) / f"{pmid}.xml"
    if not path.is_file():
        return None
    xml_bytes = path.read_bytes()
    _pmc_id, sections = parse_pmc_jats(xml_bytes)
    return sections or None


def _load_mineru_sections(pmid: str) -> list[dict] | None:
    base = Path(config.MINERU_OUTPUT_DIR) / pmid
    if not base.is_dir():
        return None
    mds = sorted(base.glob("*.md"))
    if not mds:
        return None
    md_text = mds[0].read_text(encoding="utf-8", errors="replace")
    sections = split_markdown_into_sections(md_text)
    return sections or None


def bootstrap(limit: int = 30, prefer: str = "jats") -> list[str]:
    init_db()
    jats = _pmids_with_jats()
    mineru = _pmids_with_mineru()
    mineru_only = [p for p in mineru if p not in set(jats)]

    if prefer == "mineru":
        ordered = mineru + [p for p in jats if p not in set(mineru)]
    else:
        ordered = jats + mineru_only

    if not ordered:
        raise SystemExit("No PMIDs found under raw/pmc_xml or raw/mineru_output.")

    selected = ordered[:limit]
    print(
        f"[bootstrap] candidates jats={len(jats)} mineru={len(mineru)}; "
        f"loading {len(selected)} (prefer={prefer})"
    )

    loaded: list[str] = []
    batch_size = 20
    for i in range(0, len(selected), batch_size):
        batch = selected[i : i + batch_size]
        articles = _fetch_batch(batch)
        by_pmid = {a["pmid"]: a for a in articles if a.get("pmid")}

        for pmid in batch:
            art = by_pmid.get(pmid)
            if not art:
                print(f"  [skip] PMID {pmid}: PubMed metadata missing")
                continue

            source = "jats" if pmid in set(jats) else "mineru"
            sections = (
                _load_jats_sections(pmid)
                if source == "jats"
                else _load_mineru_sections(pmid)
            )
            if not sections:
                print(f"  [skip] PMID {pmid}: no parseable sections ({source})")
                continue

            art["source_queries"] = [f"raw_sample_{source}"]
            art["full_text_status"] = "pending"
            paper_id = upsert_paper(art)
            delete_paper_sections(paper_id)
            insert_sections(paper_id, sections)
            status = "available" if source == "jats" else "pdf_available"
            mark_fulltext_status(paper_id, status)
            loaded.append(pmid)
            print(f"  [ok] PMID {pmid}  sections={len(sections)}  via={source}")

    print(f"[bootstrap] loaded {len(loaded)} / {len(selected)} papers")
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--prefer",
        choices=("jats", "mineru"),
        default="jats",
        help="Prefer JATS XML or MinerU markdown when both exist",
    )
    parser.add_argument("--extract", action="store_true", help="Run LLM extract after load")
    parser.add_argument("--core-only", action="store_true", default=True)
    parser.add_argument(
        "--all-sections",
        action="store_true",
        help="Extract all section types (overrides --core-only)",
    )
    args = parser.parse_args()

    loaded = bootstrap(limit=args.limit, prefer=args.prefer)
    if not loaded:
        raise SystemExit("Nothing loaded; abort extract.")

    if args.extract:
        import config as cfg
        from extractor.section_extractor import run_extraction

        if args.all_sections:
            cfg.EXTRACT_CORE_ONLY = False
        else:
            cfg.EXTRACT_CORE_ONLY = True
        print(f"[bootstrap] extract limit={len(loaded)} core_only={cfg.EXTRACT_CORE_ONLY}")
        run_extraction(limit=len(loaded))

    stats = db_stats()
    print("\n=== DB stats after bootstrap ===")
    for k in (
        "papers",
        "sections",
        "entities",
        "relations",
        "fulltext_jats",
        "fulltext_mineru_pdf",
        "extracted",
    ):
        print(f"  {k:24s}: {stats.get(k, 0)}")


if __name__ == "__main__":
    main()
