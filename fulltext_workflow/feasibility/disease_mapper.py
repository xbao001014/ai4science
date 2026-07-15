"""Map research gap text / KG disease names to pathology disease_id (DiseaseCode)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Protocol

# Keyword fragments -> API search keyword (Chinese preferred)
DISEASE_SEARCH_KEYWORDS: dict[str, str] = {
    "gc-adc": "胃腺癌",
    "gastric": "胃腺癌",
    "stomach": "胃腺癌",
    "胃": "胃腺癌",
    "胃癌": "胃腺癌",
    "胃腺癌": "胃腺癌",
    "nsclc": "肺腺癌",
    "lung adenocarcinoma": "肺腺癌",
    "lung cancer": "肺",
    "肺腺癌": "肺腺癌",
    "非小细胞": "肺腺癌",
    "crc": "结直肠",
    "colorectal": "结直肠",
    "colon": "结直肠",
    "结直肠": "结直肠腺癌",
    "结肠癌": "结直肠",
    "hcc": "肝细胞癌",
    "hepatocellular": "肝细胞癌",
    "liver cancer": "肝细胞癌",
    "肝癌": "肝细胞癌",
    "肝细胞": "肝细胞癌",
    "brca": "乳腺",
    "breast": "乳腺",
    "乳腺": "乳腺",
    "乳腺癌": "乳腺",
    "nasopharyngeal carcinoma": "鼻咽癌",
    "nasopharyngeal cancer": "鼻咽癌",
    "nasopharyngeal": "鼻咽",
    "nasopharynx": "鼻咽",
    "npc": "鼻咽癌",
    "鼻咽癌": "鼻咽癌",
    "鼻咽": "鼻咽",
}

# Legacy mock IDs kept for unit tests (PATHOLOGY_DATA_PROVIDER=mock)
DISEASE_ALIASES: dict[str, str] = {
    "gc-adc": "GC-ADC",
    "gastric": "GC-ADC",
    "stomach": "GC-ADC",
    "胃": "GC-ADC",
    "胃癌": "GC-ADC",
    "胃腺癌": "GC-ADC",
    "nsclc": "NSCLC-ADC",
    "lung adenocarcinoma": "NSCLC-ADC",
    "lung cancer": "NSCLC-ADC",
    "肺腺癌": "NSCLC-ADC",
    "非小细胞": "NSCLC-ADC",
    "crc": "CRC-ADC",
    "colorectal": "CRC-ADC",
    "colon": "CRC-ADC",
    "结直肠": "CRC-ADC",
    "结肠癌": "CRC-ADC",
    "hcc": "HCC",
    "hepatocellular": "HCC",
    "liver cancer": "HCC",
    "肝癌": "HCC",
    "肝细胞": "HCC",
    "brca": "BRCA-IDC",
    "breast": "BRCA-IDC",
    "乳腺": "BRCA-IDC",
    "乳腺癌": "BRCA-IDC",
    "bilateral breast": "BRCA-IDC",
    "multifocal breast": "BRCA-IDC",
}

DISEASE_NAMES: dict[str, tuple[str, str]] = {
    "GC-ADC": ("胃腺癌", "Gastric Adenocarcinoma"),
    "NSCLC-ADC": ("肺腺癌", "Lung Adenocarcinoma"),
    "CRC-ADC": ("结直肠腺癌", "Colorectal Adenocarcinoma"),
    "HCC": ("肝细胞癌", "Hepatocellular Carcinoma"),
    "BRCA-IDC": ("乳腺浸润性导管癌", "Breast Invasive Ductal Carcinoma"),
}


class DiseaseSearchClient(Protocol):
    def search_diseases(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]: ...


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _pick_best_disease(candidates: list[dict[str, Any]], keyword: str) -> dict[str, Any] | None:
    if not candidates:
        return None
    best = candidates[0]
    best_score = -1.0
    for item in candidates:
        name = item.get("name_zh") or item.get("DiseaseNameZh") or ""
        score = _similarity(keyword, name)
        cases = item.get("total_cases") or 0
        score += min(cases, 1000) / 10000.0
        if score > best_score:
            best_score = score
            best = item
    return best


def _disease_id_from_record(record: dict[str, Any]) -> str:
    return str(record.get("disease_id") or record.get("DiseaseCode") or "")


def _map_via_api_search(
    gap_text: str,
    client: DiseaseSearchClient,
) -> tuple[str | None, float, str]:
    text = gap_text.lower().strip()
    # Longest alias first so "nasopharyngeal carcinoma" beats "nasopharyngeal"
    for alias, keyword in sorted(
        DISEASE_SEARCH_KEYWORDS.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if alias in text:
            matches = client.search_diseases(keyword, limit=10)
            best = _pick_best_disease(matches, keyword)
            if best:
                did = _disease_id_from_record(best)
                return did, 0.92, f"API search: {keyword} -> {best.get('name_zh', did)}"
    tokens = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", gap_text)
    for token in tokens:
        key = token.lower()
        keyword = DISEASE_SEARCH_KEYWORDS.get(key) or (
            token if re.search(r"[\u4e00-\u9fff]", token) else None
        )
        if not keyword:
            continue
        matches = client.search_diseases(keyword, limit=5)
        best = _pick_best_disease(matches, keyword)
        if best:
            did = _disease_id_from_record(best)
            return did, 0.85, f"API token search: {token} -> {did}"
    return None, 0.0, "no API disease match"


def _map_via_text_matches(gap_text: str) -> tuple[str | None, float, str]:
    """V1.1 §7.5 — resolve via text_disease_match + disease dict when API is available."""
    try:
        from feasibility.http_api import HttpPathologyApi
        from feasibility.v11_queries import resolve_disease_by_mention
        import config

        if (config.PATHOLOGY_DATA_PROVIDER or "api").lower() == "mock":
            return None, 0.0, "mock provider"
        api = HttpPathologyApi()
        # Prefer Chinese disease tokens from gap text
        tokens = re.findall(r"[\u4e00-\u9fff]{2,8}", gap_text)
        for token in tokens[:6]:
            hits = resolve_disease_by_mention(api, token, limit=80)
            if hits:
                top = hits[0]
                conf = 0.88 if top.get("source") == "text_disease_match" else 0.75
                if top.get("confidence") is not None:
                    try:
                        conf = max(conf, min(0.95, float(top["confidence"])))
                    except (TypeError, ValueError):
                        pass
                return (
                    str(top["disease_code"]),
                    conf,
                    f"V1.1 text match: {token} -> {top.get('disease_name_zh')}",
                )
    except Exception:
        pass
    return None, 0.0, "no text match"


def map_gap_to_disease(
    gap_text: str,
    known_diseases: list[str] | None = None,
    client: DiseaseSearchClient | None = None,
) -> tuple[str | None, float, str]:
    """
    Map gap title/text to a pathology disease_id (DiseaseCode on live API).

    Returns (disease_id, confidence 0-1, match_reason).
    """
    text = gap_text.lower().strip()
    if not text:
        return None, 0.0, "empty input"

    if client is not None:
        api_result = _map_via_api_search(gap_text, client)
        if api_result[0]:
            return api_result
        text_result = _map_via_text_matches(gap_text)
        if text_result[0]:
            return text_result

    for alias, disease_id in sorted(
        DISEASE_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if alias in text:
            return disease_id, 0.95, f"alias match: {alias}"

    if known_diseases:
        best_id: str | None = None
        best_score = 0.0
        best_name = ""
        for kg_name in known_diseases:
            for disease_id, (zh, en) in DISEASE_NAMES.items():
                for candidate in (kg_name, zh, en):
                    score = _similarity(kg_name, candidate)
                    if score > best_score:
                        best_score = score
                        best_id = disease_id
                        best_name = kg_name
        if best_id and best_score >= 0.55:
            return best_id, best_score, f"KG entity fuzzy: {best_name}"

    for disease_id, (zh, en) in DISEASE_NAMES.items():
        if zh in gap_text or en.lower() in text:
            return disease_id, 0.9, f"name match: {disease_id}"

    tokens = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", gap_text)
    for token in tokens:
        key = token.lower()
        if key in DISEASE_ALIASES:
            did = DISEASE_ALIASES[key]
            return did, 0.85, f"token alias: {token}"

    if client is not None:
        text_result = _map_via_text_matches(gap_text)
        if text_result[0]:
            return text_result
        broad = client.search_diseases(gap_text[:20], limit=3)
        best = _pick_best_disease(broad, gap_text)
        if best:
            did = _disease_id_from_record(best)
            return did, 0.35, f"API broad fallback: {did}"

    return None, 0.0, "no disease mapping"


def extract_disease_from_gap_section(gap_section: str) -> str | None:
    """Try to extract disease mention from a gap markdown section."""
    m = re.search(r"\*\*研究问题\*\*[：:]\s*(.+?)(?:\n|\*\*)", gap_section, re.DOTALL)
    if m:
        return m.group(1).strip()[:200]
    return gap_section[:200] if gap_section else None
