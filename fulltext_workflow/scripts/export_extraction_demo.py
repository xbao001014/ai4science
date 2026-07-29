"""Export offline HTML: fulltext sections ↔ extracted elements."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from viz.extraction_demo import (  # noqa: E402
    DemoExportError,
    load_demo_papers,
    parse_pmid_list,
    render_extraction_demo_html,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pmids", default="", help="Comma-separated PMIDs")
    parser.add_argument(
        "--pmid-file",
        default=str(ROOT / "data" / "demo_extraction_pmids.txt"),
    )
    parser.add_argument("--db", default="", help="SQLite path")
    parser.add_argument(
        "--out",
        default=str(ROOT / "output" / "extraction_demo.html"),
    )
    args = parser.parse_args(argv)

    try:
        if args.pmids.strip():
            pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]
        else:
            try:
                pmids = parse_pmid_list(Path(args.pmid_file).read_text(encoding="utf-8"))
            except OSError as e:
                raise DemoExportError(f"Cannot read PMID file {args.pmid_file}: {e}") from e
        papers = load_demo_papers(pmids, db_path=args.db or None)
        html = render_extraction_demo_html(papers)
    except DemoExportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({len(papers)} papers, {out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
