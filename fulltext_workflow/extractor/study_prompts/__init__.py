"""Study-type prompt packs: assemble Pass 1 / Pass 2 system prompts."""
from __future__ import annotations

from extractor.study_prompts.packs import PACKS, StudyTypePack
from extractor.study_prompts.shared import (
    DEFAULT_SECTION_HINT,
    RECONCILE_SHARED_CORE,
    SECTION_HINTS,
    SECTION_SHARED_CORE,
)

__all__ = [
    "PACKS",
    "StudyTypePack",
    "SECTION_SHARED_CORE",
    "RECONCILE_SHARED_CORE",
    "SECTION_HINTS",
    "build_section_system",
    "build_reconcile_system",
]


def build_section_system(section_type: str, study_type: str | None) -> str:
    st = (study_type or "other").lower()
    pack = PACKS.get(st, PACKS["other"])
    hint = SECTION_HINTS.get(section_type, DEFAULT_SECTION_HINT)
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
