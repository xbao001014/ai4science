"""Download PDFs via ScanSci PDF (isolated output dir)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from compare_test.config import DOWNLOAD_MANIFEST, PDF_DIR, SCANSCI_STRATEGY


def load_manifest() -> dict[str, Any]:
    return _load_manifest()


def _load_manifest() -> dict[str, Any]:
    path = Path(DOWNLOAD_MANIFEST)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {"papers": {}}


def _save_manifest(data: dict[str, Any]) -> None:
    path = Path(DOWNLOAD_MANIFEST)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def download_paper_pdf(
    pmid: str,
    doi: str,
    *,
    force: bool = False,
    delay_sec: float = 1.0,
) -> dict[str, Any]:
    """Download one paper PDF via ScanSci. Returns manifest entry."""
    Path(PDF_DIR).mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    existing = manifest["papers"].get(pmid)
    if existing and existing.get("success") and not force:
        pdf_path = existing.get("file", "")
        if pdf_path and Path(pdf_path).exists():
            return existing

    if not doi:
        entry = {
            "success": False,
            "pmid": pmid,
            "doi": "",
            "reason": "no_doi",
            "source": "none",
        }
        manifest["papers"][pmid] = entry
        _save_manifest(manifest)
        return entry

    from scansci_pdf.sources import download

    # Disable Sci-Hub; use OA-first multi-source racing
    os.environ.setdefault("SCANSCI_PDF_SCIHUB_ENABLED", "false")
    result = download(
        doi,
        output_dir=PDF_DIR,
        strategy=SCANSCI_STRATEGY,
        scihub_enabled=False,
        rename=False,
    )

    entry = {
        "success": bool(result.get("success")),
        "pmid": pmid,
        "doi": doi,
        "file": result.get("file", ""),
        "source": result.get("source", "none"),
        "size_kb": result.get("size_kb"),
        "reason": result.get("reason", ""),
        "strategy": SCANSCI_STRATEGY,
    }
    manifest["papers"][pmid] = entry
    _save_manifest(manifest)

    if delay_sec > 0:
        time.sleep(delay_sec)
    return entry


def download_batch(
    papers: list[dict[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any]:
    results = []
    for i, paper in enumerate(papers, 1):
        pmid = paper["pmid"]
        doi = paper.get("doi") or ""
        print(f"  [{i}/{len(papers)}] ScanSci PDF: PMID {pmid} ({doi[:40]}...)")
        entry = download_paper_pdf(pmid, doi, force=force)
        status = "OK" if entry.get("success") else f"FAIL ({entry.get('reason', '?')})"
        print(f"           -> {status} source={entry.get('source')}")
        results.append(entry)

    ok = sum(1 for r in results if r.get("success"))
    return {
        "total": len(results),
        "succeeded": ok,
        "failed": len(results) - ok,
        "results": results,
    }
