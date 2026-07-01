"""Backward-compatible wrapper — see fetcher/citation_fetcher.py."""
from fetcher.citation_fetcher import enrich_citations, enrich_from_s2

__all__ = ["enrich_citations", "enrich_from_s2"]
