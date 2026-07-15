"""Unit tests for disease concept resolve/expand."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.disease_synonyms import (  # noqa: E402
    build_fangxin_alias_map,
    concept_match_sql_clause,
    expand_focus_terms,
    list_fangxin_disease_codes,
    resolve_disease_concept,
)


def test_resolve_zh_intestinal_polyp():
    c = resolve_disease_concept("肠息肉")
    assert c is not None
    assert c.id == "colorectal_polyp"


def test_resolve_colon_polyp_aliases():
    assert resolve_disease_concept("结肠息肉").id == "colorectal_polyp"
    assert resolve_disease_concept("结直肠息肉").id == "colorectal_polyp"
    assert resolve_disease_concept("colorectal polyp").id == "colorectal_polyp"


def test_expand_includes_english_phrases_not_only_zh():
    exp = expand_focus_terms("肠息肉")
    phrases = exp["phrases"]
    assert any("colorectal polyp" in p for p in phrases)
    assert any("polyp" in p for p in phrases)


def test_resolve_npc_and_cancer_carcinoma():
    assert resolve_disease_concept("NPC").id == "nasopharyngeal_carcinoma"
    assert resolve_disease_concept("nasopharyngeal cancer").id == "nasopharyngeal_carcinoma"
    assert resolve_disease_concept("nasopharyngeal carcinoma").id == "nasopharyngeal_carcinoma"


def test_unknown_focus_returns_none():
    assert resolve_disease_concept("totally unknown xyzzy disease") is None


def test_polyp_sql_uses_english_not_bare_polyp():
    c = resolve_disease_concept("肠息肉")
    assert c is not None
    clause = concept_match_sql_clause("p.title", c).lower()
    assert "colorectal polyp" in clause
    assert "colorectal" in clause


def test_fangxin_catalog_covers_landscape_codes():
    codes = {row["disease_code"] for row in list_fangxin_disease_codes()}
    expected = {
        "BY_BNAI", "C_CA", "C_CDLBL", "C_CXL", "C_CY", "C_XR",
        "F_AQBB", "F_FA", "W_FZLXBB", "W_KY", "W_LBL", "W_WJZSPYCZS", "W_XR",
    }
    assert expected <= codes


def test_resolve_gastric_polyp_and_adenoma_distinct():
    assert resolve_disease_concept("胃息肉").id == "gastric_polyp"
    assert resolve_disease_concept("肠腺瘤").id == "colorectal_adenoma"
    assert resolve_disease_concept("胃息肉").fangxin_disease_code == "W_XR"
    assert resolve_disease_concept("肠腺瘤").fangxin_disease_code == "C_CXL"


def test_fangxin_alias_map_zh_polyp():
    m = build_fangxin_alias_map()
    assert m["肠息肉"] == "C_XR"
    assert m["鼻咽癌"] == "BY_BNAI"
    assert m["肠癌"] == "C_CA"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
