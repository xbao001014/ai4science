"""V1.1 schema query semantics implemented over existing pathology GET APIs.

Maps §7 “常用查询口径” from 数据库接口更新V1.1.pdf onto:
  /diseases/patients, /diseases/slides, /patients/disease-subtypes,
  /patients/disease-attributes, /molecular-results, /text-disease-matches
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from feasibility.http_api import HttpPathologyApi, PathologyHttpError
from feasibility.landscape_builder import aggregate_hospital_stats

_POSITIVE_MARKERS = ("\u9633\u6027", "positive", "+", "\u9633")
_PENDING_STATUS = (
    "\u5f85\u5ba1\u6838",
    "pending",
    "\u5f85\u6838\u9a8c",
    "\u5f85\u786e\u8ba4",
)
_CONFIRMED_STATUS = (
    "\u5df2\u786e\u8ba4",
    "confirmed",
    "\u5df2\u6838\u9a8c",
)


def _patient_id_set(patients: list[dict[str, Any]]) -> set[str]:
    return {str(p["PatientId"]) for p in patients if p.get("PatientId")}


def disease_patient_count(
    api: HttpPathologyApi,
    *,
    disease_code: str,
) -> dict[str, Any]:
    """§7.1 — patient count for a disease (from hospital stats + patient list sample)."""
    stats = aggregate_hospital_stats(
        api.sample_count_by_hospital(disease_code=disease_code)
    )
    patients = api.list_patients(disease_code=disease_code, limit=1000)
    return {
        "disease_code": disease_code,
        "patient_count": stats["patient_count"] or len(patients),
        "specimen_count": stats["specimen_count"],
        "slide_count": stats["slide_count"],
        "hospital_count": stats["hospital_count"],
        "patient_sample_rows": len(patients),
        "query": "V1.1 §7.1 patient_count + S-01 sample-count-by-hospital",
    }


def disease_slide_count(
    api: HttpPathologyApi,
    *,
    disease_code: str,
    stain_type: str | None = None,
) -> dict[str, Any]:
    """§7.2 — slide count for a disease."""
    stats = aggregate_hospital_stats(
        api.sample_count_by_hospital(disease_code=disease_code)
    )
    slides = api.list_slides(
        disease_code=disease_code, stain_type=stain_type, limit=1000
    )
    return {
        "disease_code": disease_code,
        "slide_count": stats["slide_count"],
        "slide_sample_rows": len(slides),
        "stain_type": stain_type,
        "query": "V1.1 §7.2 slide_count",
    }


def subtype_distribution(
    api: HttpPathologyApi,
    *,
    disease_code: str,
    disease_name_zh: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """§7.4 — subtype patient counts for a disease."""
    patients = api.list_patients(disease_code=disease_code, limit=limit)
    pids = _patient_id_set(patients)
    name_zh = disease_name_zh or ""

    rows = api.list_disease_subtypes(limit=limit)
    matched: list[dict[str, Any]] = []
    for row in rows:
        pid = str(row.get("PatientId") or "")
        row_disease = str(row.get("DiseaseNameZh") or "")
        if pid in pids or (name_zh and name_zh in row_disease):
            matched.append(row)

    counter: Counter[str] = Counter()
    for row in matched:
        label = row.get("SubtypeNameZh") or row.get("SubtypeCode") or "(unknown)"
        counter[str(label)] += 1

    distribution = [
        {"subtype_name_zh": name, "patient_count": count}
        for name, count in counter.most_common()
    ]
    return {
        "disease_code": disease_code,
        "patient_scope": len(pids),
        "matched_rows": len(matched),
        "distribution": distribution,
        "query": "V1.1 §7.4 subtype distribution",
    }


def attribute_distribution(
    api: HttpPathologyApi,
    *,
    disease_code: str,
    attribute_keyword: str | None = None,
    disease_name_zh: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """§7.3 — attribute option counts (severity / stage / grade …)."""
    patients = api.list_patients(disease_code=disease_code, limit=limit)
    pids = _patient_id_set(patients)
    name_zh = disease_name_zh or ""
    kw = (attribute_keyword or "").strip().lower()

    rows = api.list_disease_attributes(limit=limit)
    matched: list[dict[str, Any]] = []
    for row in rows:
        pid = str(row.get("PatientId") or "")
        row_disease = str(row.get("DiseaseNameZh") or "")
        if pid not in pids and not (name_zh and name_zh in row_disease):
            continue
        if kw:
            hay = " ".join(
                str(row.get(k) or "")
                for k in ("AttributeCode", "AttributeNameZh", "OptionNameZh", "TextValue")
            ).lower()
            if kw not in hay:
                continue
        matched.append(row)

    by_attr: dict[str, Counter[str]] = {}
    for row in matched:
        attr = row.get("AttributeNameZh") or row.get("AttributeCode") or "(attr)"
        opt = (
            row.get("OptionNameZh")
            or row.get("TextValue")
            or row.get("OptionCode")
            or "(value)"
        )
        by_attr.setdefault(str(attr), Counter())[str(opt)] += 1

    distribution = []
    for attr, counter in sorted(by_attr.items(), key=lambda x: -sum(x[1].values())):
        for opt, count in counter.most_common():
            distribution.append({
                "attribute_name_zh": attr,
                "option_name_zh": opt,
                "patient_count": count,
            })

    return {
        "disease_code": disease_code,
        "attribute_keyword": attribute_keyword,
        "patient_scope": len(pids),
        "matched_rows": len(matched),
        "distribution": distribution,
        "query": "V1.1 §7.3 attribute distribution",
    }


def _is_positive(result: str | None) -> bool:
    text = (result or "").strip().lower()
    if not text:
        return False
    if "\u9634" in text or "negative" in text:
        return False
    return any(m.lower() in text for m in _POSITIVE_MARKERS)


def molecular_positivity(
    api: HttpPathologyApi,
    *,
    disease_code: str,
    biomarker_name: str,
    limit: int = 1000,
) -> dict[str, Any]:
    """§7.8 — positive patient count for a biomarker within a disease cohort."""
    patients = api.list_patients(disease_code=disease_code, limit=limit)
    pids = _patient_id_set(patients)
    rows = api.list_molecular_results(biomarker_name=biomarker_name, limit=limit)

    tested: set[str] = set()
    positive: set[str] = set()
    for row in rows:
        pid = str(row.get("PatientId") or "")
        if pid not in pids:
            continue
        tested.add(pid)
        if _is_positive(row.get("QualitativeResult") or row.get("Interpretation")):
            positive.add(pid)

    return {
        "disease_code": disease_code,
        "biomarker_name": biomarker_name,
        "patient_scope": len(pids),
        "tested_patients": len(tested),
        "positive_patients": len(positive),
        "positivity_rate": round(len(positive) / max(len(tested), 1), 3),
        "query": "V1.1 §7.8 molecular/IHC positivity",
    }


def text_disease_match_summary(
    api: HttpPathologyApi,
    *,
    disease_code: str | None = None,
    pending_only: bool = False,
    limit: int = 1000,
) -> dict[str, Any]:
    """§7.5–7.7 — text disease hit / mapping / pending review summary."""
    rows = api.list_text_disease_matches(disease_code=disease_code, limit=limit)
    if pending_only:
        rows = [
            r for r in rows
            if any(s in str(r.get("VerificationStatus") or "") for s in _PENDING_STATUS)
        ]

    status_counts: Counter[str] = Counter(
        str(r.get("VerificationStatus") or "(unknown)") for r in rows
    )
    method_counts: Counter[str] = Counter(
        str(r.get("MatchMethod") or "(unknown)") for r in rows
    )
    mention_counts: Counter[str] = Counter(
        str(r.get("NormalizedMention") or r.get("RawMention") or "(mention)")
        for r in rows
    )

    return {
        "disease_code": disease_code,
        "pending_only": pending_only,
        "total_matches": len(rows),
        "verification_status": dict(status_counts.most_common()),
        "match_methods": dict(method_counts.most_common()),
        "top_mentions": [
            {"mention": m, "count": c} for m, c in mention_counts.most_common(20)
        ],
        "sample": rows[:20],
        "query": "V1.1 §7.5–7.7 text_disease_match",
    }


def resolve_disease_by_mention(
    api: HttpPathologyApi,
    mention: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """§7.5 approximate: resolve text mention → DiseaseCode via matches + disease dict."""
    mention = (mention or "").strip()
    if not mention:
        return []

    hits: list[dict[str, Any]] = []
    try:
        matches = api.list_text_disease_matches(limit=limit)
    except PathologyHttpError:
        matches = []

    key = mention.lower()
    for row in matches:
        raw = str(row.get("RawMention") or "")
        norm = str(row.get("NormalizedMention") or "")
        if key in raw.lower() or key in norm.lower() or raw.lower() in key or norm.lower() in key:
            hits.append({
                "disease_code": row.get("DiseaseCode"),
                "disease_name_zh": row.get("DiseaseNameZh"),
                "raw_mention": row.get("RawMention"),
                "normalized_mention": row.get("NormalizedMention"),
                "confidence": row.get("Confidence"),
                "verification_status": row.get("VerificationStatus"),
                "source": "text_disease_match",
            })

    try:
        dict_hits = api.list_diseases(keyword=mention, limit=10)
    except PathologyHttpError:
        dict_hits = []
    for row in dict_hits:
        hits.append({
            "disease_code": row.get("DiseaseCode"),
            "disease_name_zh": row.get("DiseaseNameZh"),
            "raw_mention": mention,
            "normalized_mention": row.get("DiseaseNameZh"),
            "confidence": None,
            "verification_status": None,
            "source": "disease_dict",
        })

    # de-dupe by disease_code, prefer text match
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for h in hits:
        code = str(h.get("disease_code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(h)
    return out


def build_v11_landscape_extras(
    api: HttpPathologyApi,
    *,
    disease_code: str,
    disease_name_zh: str | None = None,
) -> dict[str, Any]:
    """Aggregate V1.1 extras for landscape cache / UI."""
    try:
        subtypes = subtype_distribution(
            api, disease_code=disease_code, disease_name_zh=disease_name_zh
        )
    except PathologyHttpError as exc:
        subtypes = {"error": str(exc), "distribution": []}

    try:
        attrs = attribute_distribution(
            api, disease_code=disease_code, disease_name_zh=disease_name_zh
        )
    except PathologyHttpError as exc:
        attrs = {"error": str(exc), "distribution": []}

    try:
        text = text_disease_match_summary(api, disease_code=disease_code, limit=200)
    except PathologyHttpError as exc:
        text = {"error": str(exc), "total_matches": 0}

    molecular_summary: list[dict[str, Any]] = []
    for marker in ("HER2", "EGFR", "MSI", "P16", "Ki-67", "PD-L1"):
        try:
            mol = molecular_positivity(
                api, disease_code=disease_code, biomarker_name=marker, limit=500
            )
            if mol["tested_patients"] > 0:
                molecular_summary.append(mol)
        except PathologyHttpError:
            continue

    return {
        "schema_version": "v1.1",
        "subtype_distribution": subtypes.get("distribution", []),
        "attribute_distribution": attrs.get("distribution", []),
        "text_match_summary": {
            "total_matches": text.get("total_matches", 0),
            "verification_status": text.get("verification_status", {}),
            "top_mentions": text.get("top_mentions", [])[:10],
        },
        "molecular_positivity": [
            {
                "biomarker_name": m["biomarker_name"],
                "tested_patients": m["tested_patients"],
                "positive_patients": m["positive_patients"],
                "positivity_rate": m["positivity_rate"],
            }
            for m in molecular_summary
        ],
        "api_note": (
            "Built over existing GET endpoints. "
            "disease_alias_dict / slide_annotation_ref not yet exposed as REST."
        ),
    }
