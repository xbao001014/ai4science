"""Download paper PDF via ScanSci (OA-first, Sci-Hub disabled)."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import config


def download_pdf(doi: str, pmid: str) -> dict[str, Any]:
    """Download one PDF by DOI. Returns {success, file, source, reason}."""
    if not doi:
        return {"success": False, "file": "", "source": "none", "reason": "no_doi"}

    pdf_dir = Path(config.RAW_PDF_DIR)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    safe_name = doi.replace("/", "_")
    cached = pdf_dir / f"{pmid}_{safe_name}.pdf"
    if cached.exists() and cached.stat().st_size > 1000:
        return {
            "success": True,
            "file": str(cached),
            "source": "local_cache",
            "reason": "",
        }

    os.environ.setdefault("SCANSCI_PDF_SCIHUB_ENABLED", "false")
    from scansci_pdf.sources import download

    result = download(
        doi,
        output_dir=str(pdf_dir),
        strategy=config.SCANSCI_STRATEGY,
        scihub_enabled=False,
        rename=False,
    )

    if not result.get("success"):
        return {
            "success": False,
            "file": "",
            "source": result.get("source", "none"),
            "reason": result.get("reason", "download failed"),
        }

    downloaded = Path(result["file"])
    if downloaded.resolve() != cached.resolve():
        if cached.exists():
            cached.unlink()
        downloaded.rename(cached)

    time.sleep(config.SCANSCI_RATE_DELAY)
    return {
        "success": True,
        "file": str(cached),
        "source": result.get("source", "scansci"),
        "reason": "",
    }
