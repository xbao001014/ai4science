"""Tests for Dataset access_class resolution."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor.dataset_access import (  # noqa: E402
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
    assert resolve_dataset_access("some rare bank", access_hint="public") == "public"


def test_default_unknown():
    assert resolve_dataset_access("custom slide set 2024") == "unknown"


def test_stronger_access_precedence():
    assert stronger_access("unknown", "private") == "private"
    assert stronger_access("private", "public") == "public"
    assert stronger_access("public", "private") == "public"
