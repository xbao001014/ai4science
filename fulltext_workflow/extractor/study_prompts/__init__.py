"""Study-type prompt packs: assemble Pass 1 / Pass 2 system prompts."""
from __future__ import annotations

from extractor.study_prompts.packs import PACKS, StudyTypePack
from extractor.study_prompts.shared import (
    RECONCILE_SHARED_CORE,
    REVIEW_META_SECTION_HINTS,
    SECTION_HINTS,
    SECTION_SHARED_CORE,
    section_hint_for,
)

__all__ = [
    "PACKS",
    "StudyTypePack",
    "SECTION_SHARED_CORE",
    "RECONCILE_SHARED_CORE",
    "SECTION_HINTS",
    "REVIEW_META_SECTION_HINTS",
    "section_hint_for",
    "build_section_system",
    "build_reconcile_system",
]


def build_section_system(section_type: str, study_type: str | None) -> str:
    st = (study_type or "other").lower()
    pack = PACKS.get(st, PACKS["other"])
    hint = section_hint_for(section_type, st)
    return (
        f"{SECTION_SHARED_CORE}\n\n"
        f"Study type pack: {pack.study_type}\n"
        f"{pack.section_lens}\n\n"
        f"Section focus: {hint}"
    )


def build_reconcile_system(study_type: str | None) -> str:
    st = (study_type or "other").lower()
    pack = PACKS.get(st, PACKS["other"])
    return (
        f"{RECONCILE_SHARED_CORE}\n\n"
        f"Study type pack: {pack.study_type}\n"
        f"{pack.reconcile_lens}"
    )
