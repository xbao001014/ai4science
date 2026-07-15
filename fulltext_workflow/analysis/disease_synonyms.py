"""Shared disease concepts for focus expansion and Fangxin feasibility mapping."""
from __future__ import annotations

import re
from dataclasses import dataclass

HISTOLOGY_CLASSES: dict[str, list[str]] = {
    "malignant_neoplasm": [
        "carcinoma", "cancer", "neoplasm", "neoplasms", "tumor", "tumour",
    ],
    "lymphoma": ["lymphoma", "lymphomas", "lymphomatous"],
}

_POLYP_TOKENS = ["polyp", "polyps", "adenoma", "adenomas"]
_ADENOMA_TOKENS = ["adenoma", "adenomas"]
_ULCER_TOKENS = ["ulcer", "ulcers"]


def _escape_sql_like(value: str) -> str:
    return value.replace("'", "''")


@dataclass(frozen=True)
class DiseaseConcept:
    id: str
    canonical: str
    phrases: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()
    histology_class: str = "malignant_neoplasm"
    abbreviations: tuple[str, ...] = ()
    zh: tuple[str, ...] = ()
    feasibility_keyword_zh: str = ""
    mock_disease_id: str = ""
    fangxin_disease_code: str = ""
    umls_cui: str = ""
    polyp_tokens: tuple[str, ...] = ()
    morphology_tokens: tuple[str, ...] = ()


def _concept(
    *,
    id: str,
    canonical: str,
    phrases: list[str],
    sites: list[str] | None = None,
    histology_class: str = "malignant_neoplasm",
    abbreviations: list[str] | None = None,
    zh: list[str] | None = None,
    feasibility_keyword_zh: str = "",
    mock_disease_id: str = "",
    fangxin_disease_code: str = "",
    umls_cui: str = "",
    polyp_tokens: list[str] | None = None,
    morphology_tokens: list[str] | None = None,
) -> DiseaseConcept:
    return DiseaseConcept(
        id=id,
        canonical=canonical,
        phrases=tuple(phrases),
        sites=tuple(sites or []),
        histology_class=histology_class,
        abbreviations=tuple(abbreviations or []),
        zh=tuple(zh or []),
        feasibility_keyword_zh=feasibility_keyword_zh or (zh[0] if zh else ""),
        mock_disease_id=mock_disease_id,
        fangxin_disease_code=fangxin_disease_code,
        umls_cui=umls_cui,
        polyp_tokens=tuple(polyp_tokens or []),
        morphology_tokens=tuple(morphology_tokens or []),
    )


# Fangxin pathology API DiseaseCode catalog (from landscape bootstrap).
DISEASE_CONCEPTS: tuple[DiseaseConcept, ...] = (
    _concept(
        id="gastric_adenocarcinoma",
        canonical="gastric adenocarcinoma",
        phrases=[
            "gastric adenocarcinoma", "gastric cancer", "stomach cancer",
            "gastric carcinoma", "gc-adc",
        ],
        sites=["gastric", "stomach"],
        zh=["胃癌", "胃腺癌", "胃"],
        feasibility_keyword_zh="胃腺癌",
        mock_disease_id="GC-ADC",
    ),
    _concept(
        id="lung_adenocarcinoma",
        canonical="lung adenocarcinoma",
        phrases=[
            "lung adenocarcinoma", "lung cancer", "nsclc",
            "non-small cell lung cancer", "pulmonary adenocarcinoma",
            "pulmonary cancer",
        ],
        sites=["lung", "pulmonary"],
        zh=["肺腺癌", "肺癌", "非小细胞"],
        feasibility_keyword_zh="肺癌",
        mock_disease_id="NSCLC-ADC",
        fangxin_disease_code="F_FA",
    ),
    _concept(
        id="lung_precancerous",
        canonical="lung precancerous lesion",
        phrases=[
            "lung precancerous", "pulmonary precancerous",
            "preneoplastic lung", "atypical adenomatous hyperplasia",
        ],
        sites=["lung", "pulmonary"],
        histology_class="",
        zh=["癌前病变", "肺癌前病变"],
        feasibility_keyword_zh="癌前病变",
        fangxin_disease_code="F_AQBB",
    ),
    _concept(
        id="colorectal_adenocarcinoma",
        canonical="colorectal adenocarcinoma",
        phrases=[
            "colorectal adenocarcinoma", "colorectal cancer", "colon cancer",
            "rectal cancer", "crc", "bowel cancer",
        ],
        sites=["colorectal", "colon", "rectal", "colonic", "bowel"],
        zh=["结直肠腺癌", "结直肠癌", "结肠癌", "直肠癌", "结直肠", "肠癌"],
        feasibility_keyword_zh="肠癌",
        mock_disease_id="CRC-ADC",
        fangxin_disease_code="C_CA",
    ),
    _concept(
        id="colorectal_polyp",
        canonical="colorectal polyp",
        phrases=[
            "colorectal polyp", "colorectal polyps", "colonic polyp",
            "colon polyp", "intestinal polyp",
        ],
        sites=["colorectal", "colonic", "colon", "rectal", "intestinal"],
        histology_class="",
        polyp_tokens=list(_POLYP_TOKENS),
        zh=["肠息肉", "结肠息肉", "直肠息肉", "结直肠息肉"],
        feasibility_keyword_zh="肠息肉",
        fangxin_disease_code="C_XR",
    ),
    _concept(
        id="colorectal_adenoma",
        canonical="colorectal adenoma",
        phrases=[
            "colorectal adenoma", "colonic adenoma", "colon adenoma",
            "intestinal adenoma", "tubular adenoma", "villous adenoma",
        ],
        sites=["colorectal", "colonic", "colon", "rectal", "intestinal"],
        histology_class="",
        morphology_tokens=list(_ADENOMA_TOKENS),
        zh=["肠腺瘤", "结肠腺瘤", "直肠腺瘤", "结直肠腺瘤"],
        feasibility_keyword_zh="肠腺瘤",
        fangxin_disease_code="C_CXL",
    ),
    _concept(
        id="colitis",
        canonical="colitis",
        phrases=[
            "colitis", "enteritis", "inflammatory bowel disease",
            "ulcerative colitis", "crohn disease", "crohn's disease",
        ],
        sites=["colonic", "colon", "intestinal", "bowel"],
        histology_class="",
        zh=["肠炎", "结肠炎", "炎症性肠病"],
        feasibility_keyword_zh="肠炎",
        fangxin_disease_code="C_CY",
    ),
    _concept(
        id="intestinal_lymphoma",
        canonical="intestinal lymphoma",
        phrases=[
            "intestinal lymphoma", "bowel lymphoma", "colonic lymphoma",
            "gastrointestinal lymphoma",
        ],
        sites=["intestinal", "bowel", "colonic", "colon"],
        histology_class="lymphoma",
        zh=["肠道淋巴瘤", "肠淋巴瘤", "结肠淋巴瘤"],
        feasibility_keyword_zh="肠道淋巴瘤",
        fangxin_disease_code="C_CDLBL",
    ),
    _concept(
        id="hepatocellular_carcinoma",
        canonical="hepatocellular carcinoma",
        phrases=[
            "hepatocellular carcinoma", "liver cancer", "hcc",
            "hepatic carcinoma",
        ],
        sites=["liver", "hepatic", "hepatocellular"],
        zh=["肝细胞癌", "肝癌", "肝细胞"],
        feasibility_keyword_zh="肝细胞癌",
        mock_disease_id="HCC",
    ),
    _concept(
        id="breast_carcinoma",
        canonical="breast carcinoma",
        phrases=[
            "breast cancer", "breast carcinoma", "breast invasive ductal carcinoma",
            "brca", "mammary carcinoma",
        ],
        sites=["breast", "mammary"],
        zh=["乳腺癌", "乳腺"],
        feasibility_keyword_zh="乳腺",
        mock_disease_id="BRCA-IDC",
    ),
    _concept(
        id="nasopharyngeal_carcinoma",
        canonical="nasopharyngeal carcinoma",
        phrases=[
            "nasopharyngeal carcinoma", "nasopharyngeal cancer",
            "carcinoma of the nasopharynx", "nasopharynx cancer",
        ],
        sites=["nasopharyngeal", "nasopharynx"],
        abbreviations=["npc"],
        zh=["鼻咽癌", "鼻咽"],
        feasibility_keyword_zh="鼻咽癌",
        fangxin_disease_code="BY_BNAI",
    ),
    _concept(
        id="gastric_polyp",
        canonical="gastric polyp",
        phrases=["gastric polyp", "gastric polyps", "stomach polyp", "stomach polyps"],
        sites=["gastric", "stomach"],
        histology_class="",
        polyp_tokens=list(_POLYP_TOKENS),
        zh=["胃息肉"],
        feasibility_keyword_zh="胃息肉",
        fangxin_disease_code="W_XR",
    ),
    _concept(
        id="gastric_ulcer",
        canonical="gastric ulcer",
        phrases=[
            "gastric ulcer", "stomach ulcer", "peptic ulcer",
            "peptic ulcer disease",
        ],
        sites=["gastric", "stomach"],
        histology_class="",
        morphology_tokens=list(_ULCER_TOKENS),
        zh=["胃溃疡", "消化性溃疡"],
        feasibility_keyword_zh="胃溃疡",
        fangxin_disease_code="W_KY",
    ),
    _concept(
        id="gastric_lymphoma",
        canonical="gastric lymphoma",
        phrases=["gastric lymphoma", "stomach lymphoma"],
        sites=["gastric", "stomach"],
        histology_class="lymphoma",
        zh=["胃淋巴瘤"],
        feasibility_keyword_zh="胃淋巴瘤",
        fangxin_disease_code="W_LBL",
    ),
    _concept(
        id="gastric_gist_hyperplasia",
        canonical="gastric gist or epithelial hyperplasia",
        phrases=[
            "gastrointestinal stromal tumor", "gist",
            "gastric epithelial hyperplasia", "gastric hyperplasia",
            "stromal tumor stomach",
        ],
        sites=["gastric", "stomach", "gastrointestinal"],
        histology_class="",
        zh=["胃间质", "胃上皮异常增生", "上皮异常增生", "胃间质瘤"],
        feasibility_keyword_zh="胃间质/上皮异常增生",
        fangxin_disease_code="W_WJZSPYCZS",
    ),
    _concept(
        id="gastric_non_neoplastic",
        canonical="gastric non-neoplastic lesion",
        phrases=[
            "gastric non-neoplastic", "benign gastric lesion",
            "non-neoplastic gastric",
        ],
        sites=["gastric", "stomach"],
        histology_class="",
        zh=["胃非肿瘤性病变", "非肿瘤性病变"],
        feasibility_keyword_zh="非肿瘤性病变",
        fangxin_disease_code="W_FZLXBB",
    ),
)

_CONCEPT_BY_ID = {c.id: c for c in DISEASE_CONCEPTS}
_FANGXIN_BY_CODE = {
    c.fangxin_disease_code: c for c in DISEASE_CONCEPTS if c.fangxin_disease_code
}


def list_fangxin_disease_codes() -> list[dict[str, str]]:
    """Fangxin DiseaseCode entries linked to concepts (for docs / UI)."""
    return [
        {
            "disease_code": c.fangxin_disease_code,
            "concept_id": c.id,
            "name_zh": c.feasibility_keyword_zh,
            "canonical": c.canonical,
        }
        for c in DISEASE_CONCEPTS
        if c.fangxin_disease_code
    ]


def _normalize_match_text(text: str) -> str:
    return " ".join(text.strip().split())


def _latin_fold(text: str) -> str:
    return text.lower().strip()


def _iter_match_strings(concept: DiseaseConcept) -> list[tuple[str, str]]:
    """Return (match_string, kind) for resolve; kind used for tie-break."""
    out: list[tuple[str, str]] = []
    for z in concept.zh:
        out.append((z, "zh"))
    for p in concept.phrases:
        out.append((p, "phrase"))
    out.append((concept.canonical, "canonical"))
    for a in concept.abbreviations:
        out.append((a, "abbrev"))
    return out


def resolve_disease_concept(focus: str | None) -> DiseaseConcept | None:
    if not focus or not str(focus).strip():
        return None
    raw = _normalize_match_text(str(focus))
    folded = _latin_fold(raw)

    best: DiseaseConcept | None = None
    best_len = -1
    best_rank = 99

    rank_order = {"zh": 0, "phrase": 1, "canonical": 2, "abbrev": 3}

    for concept in DISEASE_CONCEPTS:
        for match_str, kind in _iter_match_strings(concept):
            if not match_str:
                continue
            if kind == "zh":
                if raw == match_str or match_str in raw:
                    mlen = len(match_str)
                    rnk = rank_order[kind]
                    if mlen > best_len or (mlen == best_len and rnk < best_rank):
                        best_len = mlen
                        best_rank = rnk
                        best = concept
            elif kind == "abbrev":
                if re.search(rf"\b{re.escape(match_str)}\b", folded, re.I):
                    mlen = len(match_str)
                    rnk = rank_order[kind]
                    if mlen > best_len or (mlen == best_len and rnk < best_rank):
                        best_len = mlen
                        best_rank = rnk
                        best = concept
            else:
                mfold = _latin_fold(match_str)
                if folded == mfold or mfold in folded or folded in mfold:
                    mlen = len(match_str)
                    rnk = rank_order[kind]
                    if mlen > best_len or (mlen == best_len and rnk < best_rank):
                        best_len = mlen
                        best_rank = rnk
                        best = concept
    return best


def expand_focus_terms(focus: str | None) -> dict:
    concept = resolve_disease_concept(focus)
    if not concept:
        return {
            "concept_id": None,
            "canonical": None,
            "phrases": [],
            "sites": [],
            "histology": [],
            "abbreviations": [],
            "zh": [],
            "umls_cui": None,
            "fangxin_disease_code": None,
        }
    histology: list[str] = []
    if concept.histology_class:
        histology = list(HISTOLOGY_CLASSES.get(concept.histology_class, []))
    phrases = sorted({
        concept.canonical.lower(),
        *(p.lower() for p in concept.phrases),
    })
    return {
        "concept_id": concept.id,
        "canonical": concept.canonical,
        "phrases": phrases,
        "sites": list(concept.sites),
        "histology": histology,
        "abbreviations": list(concept.abbreviations),
        "zh": list(concept.zh),
        "umls_cui": concept.umls_cui or None,
        "polyp_tokens": list(concept.polyp_tokens),
        "morphology_tokens": list(concept.morphology_tokens),
        "fangxin_disease_code": concept.fangxin_disease_code or None,
    }


def _secondary_tokens(concept: DiseaseConcept) -> tuple[str, ...]:
    return concept.polyp_tokens or concept.morphology_tokens


def _like_or(column: str, terms: list[str]) -> str:
    if not terms:
        return "0=1"
    parts = [
        f"LOWER({column}) LIKE LOWER('%{_escape_sql_like(t)}%')"
        for t in terms
    ]
    return "(" + " OR ".join(parts) + ")"


def concept_match_sql_clause(column: str, concept: DiseaseConcept) -> str:
    """Phrase-first OR expansion for a resolved disease concept."""
    phrases = sorted({
        concept.canonical,
        *concept.phrases,
    }, key=len, reverse=True)
    clauses = [_like_or(column, phrases)]

    secondary = _secondary_tokens(concept)
    if secondary and concept.sites:
        site_part = _like_or(column, list(concept.sites))
        morph_part = _like_or(column, list(secondary))
        clauses.append(f"({site_part} AND {morph_part})")
    elif concept.sites and concept.histology_class:
        hist = HISTOLOGY_CLASSES.get(concept.histology_class, [])
        if hist:
            site_part = _like_or(column, list(concept.sites))
            hist_part = _like_or(column, hist)
            clauses.append(f"({site_part} AND {hist_part})")

    for abbr in concept.abbreviations:
        safe = _escape_sql_like(abbr)
        site_part = _like_or(column, list(concept.sites)) if concept.sites else ""
        hist = HISTOLOGY_CLASSES.get(concept.histology_class, [])
        hist_part = _like_or(column, hist) if hist else ""
        if site_part and hist_part:
            clauses.append(
                f"(LOWER({column}) LIKE LOWER('% {safe} %') AND ({site_part} OR {hist_part}))"
            )
            clauses.append(
                f"(LOWER({column}) LIKE LOWER('{safe} %') AND ({site_part} OR {hist_part}))"
            )
            clauses.append(
                f"(LOWER({column}) LIKE LOWER('% {safe}') AND ({site_part} OR {hist_part}))"
            )

    return " OR ".join(clauses)


def _alias_entries_for_concept(concept: DiseaseConcept) -> list[tuple[str, str]]:
    """(alias, target) pairs from one concept."""
    entries: list[tuple[str, str]] = []
    for z in concept.zh:
        entries.append((z, ""))
    for p in concept.phrases:
        entries.append((p.lower(), ""))
    for a in concept.abbreviations:
        entries.append((a.lower(), ""))
    entries.append((concept.canonical.lower(), ""))
    if not concept.polyp_tokens and not concept.morphology_tokens:
        for s in concept.sites:
            entries.append((s.lower(), ""))
    return entries


def build_search_keyword_map() -> dict[str, str]:
    """Alias fragment -> feasibility_keyword_zh for disease_mapper API search."""
    out: dict[str, str] = {}
    for concept in DISEASE_CONCEPTS:
        kw = concept.feasibility_keyword_zh
        if not kw:
            continue
        for alias, _ in _alias_entries_for_concept(concept):
            out[alias] = kw
    return out


def build_mock_alias_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for concept in DISEASE_CONCEPTS:
        if not concept.mock_disease_id:
            continue
        mid = concept.mock_disease_id
        for alias, _ in _alias_entries_for_concept(concept):
            out[alias] = mid
        if not concept.polyp_tokens and not concept.morphology_tokens:
            for s in concept.sites:
                out[s.lower()] = mid
    return out


def build_fangxin_alias_map() -> dict[str, str]:
    """Alias fragment -> Fangxin DiseaseCode (live API / landscape cache)."""
    out: dict[str, str] = {}
    for concept in DISEASE_CONCEPTS:
        code = concept.fangxin_disease_code
        if not code:
            continue
        for alias, _ in _alias_entries_for_concept(concept):
            out[alias] = code
        for s in concept.sites:
            if not concept.polyp_tokens and not concept.morphology_tokens:
                out[s.lower()] = code
    return out


def build_disease_names_map() -> dict[str, tuple[str, str]]:
    """DiseaseCode -> (name_zh, name_en) for mapper fuzzy fallback."""
    out: dict[str, tuple[str, str]] = {
        "GC-ADC": ("胃腺癌", "Gastric Adenocarcinoma"),
        "NSCLC-ADC": ("肺腺癌", "Lung Adenocarcinoma"),
        "CRC-ADC": ("结直肠腺癌", "Colorectal Adenocarcinoma"),
        "HCC": ("肝细胞癌", "Hepatocellular Carcinoma"),
        "BRCA-IDC": ("乳腺浸润性导管癌", "Breast Invasive Ductal Carcinoma"),
    }
    for concept in DISEASE_CONCEPTS:
        code = concept.fangxin_disease_code or concept.mock_disease_id
        if not code or code in out:
            continue
        out[code] = (concept.feasibility_keyword_zh, concept.canonical.title())
    return out
