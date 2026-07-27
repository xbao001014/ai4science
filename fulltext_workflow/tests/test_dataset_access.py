"""Tests for Dataset access_class resolution."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor.dataset_access import (  # noqa: E402
    is_literature_platform,
    is_public_dataset_alias,
    normalize_dataset_name,
    resolve_dataset_access,
    stronger_access,
)


def test_public_alias_camelyon():
    assert resolve_dataset_access("Camelyon17") == "public"
    assert normalize_dataset_name("camelyon 17") == "camelyon17"


def test_public_alias_tcga():
    assert resolve_dataset_access("TCGA-BRCA") == "public"


def test_private_cue_in_evidence():
    assert (
        resolve_dataset_access(
            "hospital cohort a",
            evidence_quote="we used an in-house institutional cohort",
        )
        == "private"
    )


def test_private_cue_in_name():
    assert resolve_dataset_access("in-house wsi cohort") == "private"


def test_alias_beats_private_cue():
    # Public list wins even if evidence mentions institutional context nearby
    assert (
        resolve_dataset_access(
            "camelyon17",
            evidence_quote="compared to our institutional cohort",
        )
        == "public"
    )


def test_llm_hint_used_when_unknown():
    assert resolve_dataset_access("some rare bank", access_hint="private") == "private"


def test_literature_platform_blocklist():
    assert is_literature_platform("PubMed")
    assert is_literature_platform("pubmed central")
    assert is_literature_platform("NCBI GEO")
    assert is_literature_platform("Google Scholar")
    assert is_literature_platform("ScienceDirect")
    assert not is_literature_platform("camelyon16")
    assert not is_literature_platform("tcga")


def test_public_dataset_alias_helper():
    assert is_public_dataset_alias("TCGA-LUAD")
    assert is_public_dataset_alias("cptac-crc")
    assert is_public_dataset_alias("midog++")
    assert not is_public_dataset_alias("pubmed")
    assert not is_public_dataset_alias("random hospital slides")

def test_llm_public_hint_unlisted_becomes_unknown():
    assert resolve_dataset_access("some rare bank", access_hint="public") == "unknown"


def test_llm_private_hint_still_honored():
    assert resolve_dataset_access("some rare bank", access_hint="private") == "private"


def test_default_unknown():
    assert resolve_dataset_access("custom slide set 2024") == "unknown"


def test_stronger_access_precedence():
    assert stronger_access("unknown", "private") == "private"
    assert stronger_access("private", "public") == "public"
    assert stronger_access("public", "private") == "public"
