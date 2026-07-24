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
    "special issue:",
    "special issue ",
    "special section:",
    "in this issue:",
    "editor's note:",
    "editors' note:",
    "from the editor:",
)

# Substring matches on lowercased title (non-primary research shells).
_SKIP_TITLE_CONTAINS = (
    "meeting report",
    "workshop report",
    "conference report",
    "conference proceedings",
    "proceeding of the",
    "proceedings of the",
)

# PubMed publication types that rarely yield pathology-AI KG triples.
_SKIP_PUB_TYPES = (
    "editorial",
    "news",
    "interview",
    "newspaper article",
    "patient education handout",
    "published erratum",
    "retracted publication",
    "expression of concern",
)

# Short letters/comments: skip when abstract is too thin for schema extraction.
_SHORT_COMMENT_PUB_TYPES = ("letter", "comment", "commentary")
_SHORT_COMMENT_ABS_MAX = 400
_THIN_ABSTRACT_MAX = 250


def skip_extraction_reason(
    title: str, abstract: str, pub_types: list[str] | None = None
) -> str | None:
    """Return skip reason for non-extractable shells; None if extraction should run."""
    pub_types = pub_types or []
    tl = title.lower().strip()
    al = abstract.lower().strip()
    abs_len = len(abstract.strip())
    blob = " ".join(pub_types).lower()

    for prefix in _SKIP_TITLE_PREFIXES:
        if tl.startswith(prefix):
            if prefix.startswith("special"):
                return "special issue / section notice"
            if "editor" in prefix or "in this issue" in prefix:
                return "editor note"
            return "erratum/correction notice"

    for needle in _SKIP_TITLE_CONTAINS:
        if needle in tl:
            return "meeting/workshop/proceedings report"

    if (
        "this meeting brought together" in al
        or "this workshop brought together" in al
        or "workshop on translational" in al
    ):
        return "meeting/workshop summary"

    if tl.startswith("comment on:") and abs_len < 200:
        return "comment/reply (no substantive abstract)"

    for pt in _SKIP_PUB_TYPES:
        if pt in blob:
            if pt in ("published erratum", "retracted publication"):
                if abs_len < 200 or "corrects the article" in al:
                    return "published erratum"
                continue
            return f"non-extractable pub_type ({pt})"

    for pt in _SHORT_COMMENT_PUB_TYPES:
        if pt in blob and abs_len < _SHORT_COMMENT_ABS_MAX:
            return f"short {pt} (thin abstract)"

    if abs_len < 80 and "corrects the article" in al:
        return "doi correction stub"

    # Anecdotal / viewpoint stubs: very short abstract, no research framing.
    if abs_len <= _THIN_ABSTRACT_MAX and any(
        w in al for w in ("anecdotal", "viewpoint", "commentary", "opinion")
    ):
        return "thin commentary/viewpoint"

    return None


def skip_nonsubstantive_fulltext(
    abstract: str,
    sections: list[dict] | None,
    *,
    min_body_chars: int = 800,
) -> str | None:
    """Skip when fulltext is essentially abstract + boilerplate (e.g. COI only)."""
    if not sections:
        return None
    body = 0
    for sec in sections:
        st = (sec.get("section_type") or "").lower()
        content = (sec.get("content") or "").strip()
        if not content:
            continue
        if st == "abstract":
            continue
        # Ignore tiny boilerplate chunks often labeled `other`
        if st == "other" and len(content) < 120:
            continue
        body += len(content)
    if body < min_body_chars and len(abstract.strip()) <= _THIN_ABSTRACT_MAX:
        return "non-substantive fulltext (thin body)"
    return None
