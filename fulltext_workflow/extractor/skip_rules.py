"""Rules for papers with no substantive content to extract."""
from __future__ import annotations

_SKIP_TITLE_PREFIXES = (
    "correction:",
    "corrigendum:",
    "erratum:",
    "retraction:",
    "withdrawn:",
    "publisher correction:",
    "author correction:",
)


def skip_extraction_reason(
    title: str, abstract: str, pub_types: list[str] | None = None
) -> str | None:
    """Return skip reason for errata/comments; None if extraction should run."""
    pub_types = pub_types or []
    tl = title.lower().strip()
    al = abstract.lower().strip()
    for prefix in _SKIP_TITLE_PREFIXES:
        if tl.startswith(prefix):
            return "erratum/correction notice"
    if tl.startswith("comment on:") and len(abstract.strip()) < 200:
        return "comment/reply (no substantive abstract)"
    blob = " ".join(pub_types).lower()
    if "published erratum" in blob or "retracted publication" in blob:
        if len(abstract.strip()) < 200 or "corrects the article" in al:
            return "published erratum"
    if len(abstract.strip()) < 80 and "corrects the article" in al:
        return "doi correction stub"
    return None
