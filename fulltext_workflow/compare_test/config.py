"""Isolated paths for JATS vs ScanSci PDF channel comparison (does not touch main workflow)."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_WORKFLOW = _ROOT.parent

# Read-only source DB
MAIN_DB_PATH = str(_WORKFLOW / "data" / "kg_fulltext.db")

# Isolated outputs
OUTPUT_DIR = str(_ROOT / "output")
PDF_DIR = str(_ROOT / "pdfs")
CACHE_DIR = str(_ROOT / "cache")

DOWNLOAD_MANIFEST = str(_ROOT / "output" / "download_manifest.json")
PDF_EXTRACTION_CACHE = str(_ROOT / "cache" / "pdf_extractions.json")
MINERU_OUTPUT_DIR = str(_ROOT / "mineru_output")
MINERU_EXTRACTION_CACHE = str(_ROOT / "cache" / "mineru_extractions.json")
COMPARISON_REPORT = str(_ROOT / "output" / "comparison_report.md")
COMPARISON_REPORT_MINERU = str(_ROOT / "output" / "comparison_report_mineru.md")
COMPARISON_JSON = str(_ROOT / "output" / "comparison_summary.json")
COMPARISON_JSON_MINERU = str(_ROOT / "output" / "comparison_summary_mineru.json")

DEFAULT_PAPER_LIMIT = 30
SCANSCI_STRATEGY = "oa_first"  # legal-first; Sci-Hub disabled in fetcher
MINERU_BACKEND = "pipeline"  # CPU-friendly; set hybrid-auto-engine if GPU available
MINERU_LANG = "en"
