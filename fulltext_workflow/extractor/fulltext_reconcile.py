"""Pass 2 fulltext reconcile: assemble truncated text and parse LLM JSON."""
from __future__ import annotations

from typing import Any

from extractor.improvement_actions import parse_recommendation_rows
from extractor.study_prompts.shared import RECONCILE_SHARED_CORE

_SECTION_PRIORITY: tuple[str, ...] = (
    "methods",
    "results",
    "discussion",
    "limitations",
    "future_work",
    "abstract",
    "introduction",
    "other",
)
_PRIORITY_RANK = {name: idx for idx, name in enumerate(_SECTION_PRIORITY)}
_VALID_DATASET_ACTIONS = frozenset({"keep", "merge", "drop"})
_VALID_DATASET_ROLES = frozenset({"experimental", "release", "pretrain", "drop"})
_ROLE_TO_RELATION = {
    "experimental": "USES_DATASET",
    "release": "RELEASES_DATASET",
    "pretrain": "PRETRAINS_ON",
}
_META_KEEP_REASON_SUBSTRINGS = ("self-analysis", "pooled analysis by the authors")

# Alias to shared core (study-type packs append via build_reconcile_system).
RECONCILE_SYSTEM = RECONCILE_SHARED_CORE


def _section_rank(section_type: str) -> int:
    return _PRIORITY_RANK.get(section_type.lower(), len(_SECTION_PRIORITY))


def _field(sec: dict[str, Any], key: str, default: str = "") -> str:
    val = sec.get(key, default)
    if val is None:
        return default
    return val if isinstance(val, str) else str(val)


def assemble_reconcile_text(sections: list[dict], *, max_chars: int) -> str:
    """Concatenate sections in priority order, truncating to max_chars."""
    if max_chars <= 0:
        return ""

    ordered = sorted(sections, key=lambda s: _section_rank(_field(s, "section_type")))
    parts: list[str] = []
    used = 0

    for sec in ordered:
        content = _field(sec, "content").strip()
        if not content:
            continue
        section_type = _field(sec, "section_type") or "other"
        block = f"## {section_type}\n{content}"
        sep = 2 if parts else 0
        if used + sep + len(block) <= max_chars:
            parts.append(block)
            used += sep + len(block)
            continue
        budget = max_chars - used - sep
        if budget > 0:
            if len(block) <= budget:
                parts.append(block)
            else:
                ellipsis = "\n...\n"
                if budget <= len(ellipsis):
                    parts.append(block[:budget])
                else:
                    remain = budget - len(ellipsis)
                    head_len = remain // 2
                    tail_len = remain - head_len
                    parts.append(block[:head_len] + ellipsis + block[-tail_len:])
        break

    return "\n\n".join(parts)


def _parse_dataset_rows(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        action = str(row.get("action") or "").strip().lower()
        if action not in _VALID_DATASET_ACTIONS:
            continue
        role_raw = str(row.get("role") or "").strip().lower()
        role = role_raw if role_raw in _VALID_DATASET_ROLES else "experimental"
        out.append(
            {
                "name": name,
                "access": str(row.get("access") or "unknown").strip().lower() or "unknown",
                "action": action,
                "role": role,
                "reason": str(row.get("reason") or "").strip(),
            }
        )
    return out


def _parse_name_quote_rows(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "quote": str(row.get("quote") or "").strip(),
            }
        )
    return out


def _parse_binding_rows(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        method = str(row.get("method") or "").strip()
        disease = str(row.get("disease") or "").strip()
        if not method or not disease:
            continue
        out.append(
            {
                "method": method,
                "disease": disease,
                "dataset": str(row.get("dataset") or "").strip(),
                "quote": str(row.get("quote") or "").strip(),
            }
        )
    return out


def _parse_limitation_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        canonical = str(row.get("canonical") or "").strip()
        if not canonical:
            continue
        merges_raw = row.get("merges")
        merges: list[str] = []
        if isinstance(merges_raw, list):
            merges = [str(m).strip() for m in merges_raw if str(m).strip()]
        out.append(
            {
                "canonical": canonical,
                "merges": merges,
                "quote": str(row.get("quote") or "").strip(),
            }
        )
    return out


def parse_reconcile_payload(raw: dict) -> dict:
    """Validate and normalize Pass 2 reconcile JSON."""
    if not isinstance(raw, dict):
        raw = {}
    return {
        "datasets": _parse_dataset_rows(raw.get("datasets")),
        "bindings": _parse_binding_rows(raw.get("bindings")),
        "limitations": _parse_limitation_rows(raw.get("limitations")),
        "surveyed_methods": _parse_name_quote_rows(raw.get("surveyed_methods")),
        "covered_diseases": _parse_name_quote_rows(raw.get("covered_diseases")),
        "recommendations": parse_recommendation_rows(raw.get("recommendations")),
    }


def call_reconcile_llm(
    text: str, entity_summary: str, *, study_type: str | None = None
) -> dict:
    from extractor.llm_client import llm_call_structured
    from extractor.study_prompts import build_reconcile_system

    st = study_type or "unknown"
    user = (
        f"STUDY TYPE: {st}\n"
        f"ENTITY SUMMARY (Pass1):\n{entity_summary}\n\nFULLTEXT:\n{text}"
    )
    return parse_reconcile_payload(
        llm_call_structured(build_reconcile_system(study_type), user)
    )


def _pass1_dataset_names(pmid: str) -> set[str]:
    from db.schema import list_relations_for_pmid
    from extractor.dataset_access import normalize_dataset_name
    from extractor.study_policy import DATASET_RELATIONS

    names: set[str] = set()
    for rel_name in DATASET_RELATIONS:
        for rel in list_relations_for_pmid(pmid, rel_name):
            if rel["status"] != "active":
                continue
            names.add(normalize_dataset_name(rel["object_name"]))
    return names


def _is_meta_keep_exception(row: dict[str, str], study_type: str | None) -> bool:
    if (study_type or "").lower() != "meta_analysis":
        return False
    if row.get("action") != "keep":
        return False
    if (row.get("role") or "experimental") != "experimental":
        return False
    reason = (row.get("reason") or "").lower()
    return any(s in reason for s in _META_KEEP_REASON_SUBSTRINGS)


def _relation_for_role(role: str) -> str:
    return _ROLE_TO_RELATION.get(role, "USES_DATASET")


def _dataset_mode_is_none(study_type: str | None) -> bool:
    """Clear-all-datasets path: matrix when enabled, else legacy review/meta."""
    import config

    if not config.STUDY_POLICY_ENABLED:
        return (study_type or "").lower() in ("review", "meta_analysis")
    from extractor.study_policy import get_policy

    return get_policy(study_type).dataset_mode == "none"


def _gated_relation_for_role(role: str, study_type: str | None) -> str:
    """Map role→relation, gating RELEASES/PRETRAINS by enable_new / dataset_mode."""
    import config

    target = _relation_for_role(role)
    if target == "USES_DATASET" or role == "drop":
        return target
    if not config.STUDY_POLICY_ENABLED:
        # Kill-switch: skip enable_new matrix; keep role→relation mapping.
        return target
    from extractor.study_policy import get_policy

    policy = get_policy(study_type)
    if target == "RELEASES_DATASET":
        if (
            "RELEASES_DATASET" in policy.enable_new
            or policy.dataset_mode == "release_ok"
        ):
            return target
        return "USES_DATASET"
    if target == "PRETRAINS_ON":
        if "PRETRAINS_ON" in policy.enable_new or policy.dataset_mode == "pretrain_ok":
            return target
        return "USES_DATASET"
    return target


def _should_apply_survey_cover(study_type: str | None) -> bool:
    import config

    st = (study_type or "").lower()
    if not config.STUDY_POLICY_ENABLED:
        return st in ("review", "meta_analysis")
    from extractor.study_policy import get_policy

    if st in ("review", "meta_analysis"):
        return True
    policy = get_policy(study_type)
    return bool(
        {"SURVEYS_METHOD", "COVERS_DISEASE"} & policy.enable_new
    )


def summarize_pass1_entities(pmid: str) -> str:
    """Distinct active entity names by type from Pass 1 relations for a PMID."""
    from db.schema import get_conn

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT e.type, e.name
               FROM relations r
               JOIN entities e ON e.id = r.object_id
               WHERE r.source_pmid=? AND r.status='active'
               ORDER BY e.type, e.name""",
            (pmid,),
        ).fetchall()

    by_type: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["type"], row["name"])
        if key in seen:
            continue
        seen.add(key)
        by_type.setdefault(row["type"], []).append(row["name"])

    return "\n".join(
        f"{etype}: {', '.join(names)}" for etype, names in sorted(by_type.items())
    )


def _dataset_name_matches(object_name: str, payload_name: str) -> bool:
    from extractor.dataset_access import normalize_dataset_name

    return normalize_dataset_name(object_name) == normalize_dataset_name(payload_name)


def _limitation_name_matches(object_name: str, merge_name: str) -> bool:
    from extractor.entity_normalize import normalize_entity_name

    return normalize_entity_name(object_name, "Limitation") == normalize_entity_name(
        merge_name, "Limitation"
    )


def _list_all_dataset_relations(pmid: str) -> list:
    from db.schema import list_relations_for_pmid
    from extractor.study_policy import DATASET_RELATIONS

    rows: list = []
    for rel_name in DATASET_RELATIONS:
        rows.extend(list_relations_for_pmid(pmid, rel_name))
    return rows


def _apply_dataset_actions(
    paper_id: int,
    pmid: str,
    datasets: list[dict[str, str]],
    *,
    study_type: str | None = None,
) -> None:
    from db.schema import (
        insert_relation,
        list_relations_for_pmid,
        supersede_relation,
        upsert_entity,
    )
    from extractor.dataset_access import (
        is_literature_platform,
        is_public_dataset_alias,
        normalize_dataset_name,
        resolve_dataset_access,
    )
    from extractor.study_policy import DATASET_RELATIONS

    # Reviews/meta (dataset_mode=none): clear all dataset-class edges except meta keep.
    if _dataset_mode_is_none(study_type):
        pass1_names = _pass1_dataset_names(pmid)
        exceptions = [
            r
            for r in datasets
            if _is_meta_keep_exception(r, study_type)
            and not is_literature_platform(r["name"])
            and normalize_dataset_name(r["name"]) in pass1_names
        ]
        exception_canons = {
            normalize_dataset_name(r["name"]) for r in exceptions
        }
        for rel_name in DATASET_RELATIONS:
            for rel in list_relations_for_pmid(pmid, rel_name):
                if rel["status"] != "active":
                    continue
                if (
                    rel_name == "USES_DATASET"
                    and normalize_dataset_name(rel["object_name"]) in exception_canons
                ):
                    continue
                supersede_relation(rel["id"], None)
        for row in exceptions:
            canon = normalize_dataset_name(row["name"])
            access = resolve_dataset_access(
                row["name"], access_hint=row.get("access", "unknown")
            )
            entity_id = upsert_entity(canon, "Dataset", access_class=access)
            has_active = any(
                r["status"] == "active"
                and r["relation"] == "USES_DATASET"
                and (
                    r["object_id"] == entity_id
                    or normalize_dataset_name(r["object_name"]) == canon
                )
                for r in list_relations_for_pmid(pmid, "USES_DATASET")
            )
            if not has_active:
                insert_relation(
                    "Paper",
                    paper_id,
                    "USES_DATASET",
                    "Dataset",
                    entity_id,
                    source_pmid=pmid,
                    extraction_pass="fulltext_reconcile",
                    status="active",
                )
        return

    existing = _list_all_dataset_relations(pmid)
    pass1_names = _pass1_dataset_names(pmid)

    for row in datasets:
        name = row["name"]
        action = row["action"]
        role = row.get("role") or "experimental"
        access_hint = row.get("access", "unknown")
        canon = normalize_dataset_name(name)

        if role == "drop":
            action = "drop"

        if is_literature_platform(name):
            for rel in existing:
                if rel["status"] != "active":
                    continue
                if _dataset_name_matches(rel["object_name"], name):
                    supersede_relation(rel["id"], None)
            continue

        # Curated public benchmarks must survive Pass 2; treat LLM "drop" as keep.
        if action == "drop" and is_public_dataset_alias(name):
            action = "keep"
            if role == "drop":
                role = "experimental"

        target_rel = _gated_relation_for_role(role, study_type)

        if action == "drop":
            for rel in existing:
                if rel["status"] != "active":
                    continue
                if _dataset_name_matches(rel["object_name"], name):
                    # Never supersede a curated public alias edge.
                    if is_public_dataset_alias(rel["object_name"]):
                        continue
                    supersede_relation(rel["id"], None)

        elif action == "keep":
            # Do not invent survey-only datasets absent from Pass 1.
            if canon not in pass1_names:
                continue
            access = resolve_dataset_access(name, access_hint=access_hint)
            entity_id = upsert_entity(canon, "Dataset", access_class=access)
            has_active = any(
                r["status"] == "active"
                and r["relation"] == target_rel
                and (
                    r["object_id"] == entity_id
                    or normalize_dataset_name(r["object_name"]) == canon
                )
                for r in list_relations_for_pmid(pmid, target_rel)
            )
            if not has_active:
                insert_relation(
                    "Paper",
                    paper_id,
                    target_rel,
                    "Dataset",
                    entity_id,
                    source_pmid=pmid,
                    extraction_pass="fulltext_reconcile",
                    status="active",
                )

        elif action == "merge":
            # Merge only among / into names already present in Pass 1.
            related_in_pass1 = canon in pass1_names or any(
                _dataset_name_matches(n, name) or n == canon for n in pass1_names
            )
            if not related_in_pass1:
                continue
            access = resolve_dataset_access(canon, access_hint=access_hint)
            entity_id = upsert_entity(canon, "Dataset", access_class=access)
            # Only collapse same-relation alias edges; keep other DATASET_RELATIONS
            # (e.g. USES_DATASET coexists with RELEASES_DATASET / PRETRAINS_ON).
            for rel in existing:
                if rel["status"] != "active":
                    continue
                if rel["relation"] != target_rel:
                    continue
                if rel["object_id"] == entity_id:
                    continue
                if _dataset_name_matches(rel["object_name"], name) or (
                    normalize_dataset_name(rel["object_name"]) == canon
                ):
                    supersede_relation(rel["id"], entity_id)
            insert_relation(
                "Paper",
                paper_id,
                target_rel,
                "Dataset",
                entity_id,
                source_pmid=pmid,
                extraction_pass="fulltext_reconcile",
                status="active",
            )


def _apply_survey_cover(
    paper_id: int,
    pmid: str,
    surveyed: list[dict[str, str]],
    covered: list[dict[str, str]],
    *,
    study_type: str | None = None,
) -> None:
    if not _should_apply_survey_cover(study_type):
        return
    from db.schema import insert_relation, upsert_entity
    from extractor.entity_normalize import normalize_entity_name

    for row in surveyed:
        name = normalize_entity_name(row["name"], "Method")
        if not name:
            continue
        entity_id = upsert_entity(name, "Method")
        insert_relation(
            "Paper",
            paper_id,
            "SURVEYS_METHOD",
            "Method",
            entity_id,
            source_pmid=pmid,
            evidence_quote=row.get("quote") or "",
            evidence_section="fulltext_reconcile",
            extraction_pass="fulltext_reconcile",
            status="active",
        )
    for row in covered:
        name = normalize_entity_name(row["name"], "Disease")
        if not name:
            continue
        entity_id = upsert_entity(name, "Disease")
        insert_relation(
            "Paper",
            paper_id,
            "COVERS_DISEASE",
            "Disease",
            entity_id,
            source_pmid=pmid,
            evidence_quote=row.get("quote") or "",
            evidence_section="fulltext_reconcile",
            extraction_pass="fulltext_reconcile",
            status="active",
        )


def _apply_limitation_merges(
    paper_id: int,
    pmid: str,
    limitations: list[dict[str, Any]],
) -> None:
    from db.schema import (
        insert_relation,
        list_relations_for_pmid,
        supersede_relation,
        upsert_entity,
    )
    from extractor.entity_normalize import normalize_entity_name

    existing = list_relations_for_pmid(pmid, "REPORTS_LIMITATION")

    for lim in limitations:
        canonical_name = normalize_entity_name(lim["canonical"], "Limitation")
        canonical_id = upsert_entity(canonical_name, "Limitation")
        merge_names = [
            m
            for m in (lim.get("merges") or [])
            if not _limitation_name_matches(m, canonical_name)
        ]
        for merge_name in merge_names:
            for rel in existing:
                if rel["status"] != "active":
                    continue
                # Never supersede the canonical survivor itself.
                if rel["object_id"] == canonical_id:
                    continue
                if _limitation_name_matches(rel["object_name"], merge_name):
                    supersede_relation(rel["id"], canonical_id)
        # Always leave an active canonical edge (reactivate if needed).
        insert_relation(
            "Paper",
            paper_id,
            "REPORTS_LIMITATION",
            "Limitation",
            canonical_id,
            source_pmid=pmid,
            evidence_quote=lim.get("quote") or "",
            evidence_section="fulltext_reconcile",
            extraction_pass="fulltext_reconcile",
            status="active",
        )


def _apply_bindings(
    pmid: str,
    bindings: list[dict[str, str]],
    *,
    study_type: str | None = None,
) -> None:
    from db.schema import upsert_entity, upsert_paper_entity_binding
    from extractor.dataset_access import (
        is_literature_platform,
        normalize_dataset_name,
        resolve_dataset_access,
    )
    from extractor.entity_normalize import normalize_entity_name

    survey = (study_type or "").lower() in ("review", "meta_analysis")
    pass1_names = set() if survey else _pass1_dataset_names(pmid)

    for row in bindings:
        method = normalize_entity_name(row.get("method") or "", "Method")
        disease = normalize_entity_name(row.get("disease") or "", "Disease")
        if not method and not disease:
            continue
        method_id = upsert_entity(method, "Method") if method else None
        disease_id = upsert_entity(disease, "Disease") if disease else None
        dataset_id = None
        dataset_name = (row.get("dataset") or "").strip()
        if (
            dataset_name
            and not survey
            and not is_literature_platform(dataset_name)
        ):
            canon = normalize_dataset_name(dataset_name)
            if canon in pass1_names:
                access = resolve_dataset_access(canon)
                dataset_id = upsert_entity(canon, "Dataset", access_class=access)
        upsert_paper_entity_binding(
            pmid,
            method_entity_id=method_id,
            disease_entity_id=disease_id,
            dataset_entity_id=dataset_id,
            evidence_quote=row.get("quote") or "",
        )


def _apply_recommendations(pmid: str, recommendations: list[dict[str, Any]]) -> None:
    from db.schema import replace_paper_improvement_suggestions, upsert_entity
    from extractor.entity_normalize import normalize_entity_name

    rows: list[dict[str, Any]] = []
    for rec in recommendations:
        lim_name = normalize_entity_name(rec.get("limitation") or "", "Limitation")
        lim_id = upsert_entity(lim_name, "Limitation") if lim_name else None
        rows.append(
            {
                "limitation_entity_id": lim_id,
                "action_type": rec["action_type"],
                "suggestion": rec["suggestion"],
                "evidence_quote": rec.get("evidence_quote") or "",
                "evidence_section": rec.get("evidence_section") or "",
                "grounding": rec["grounding"],
                "confidence": rec.get("confidence", 0.5),
            }
        )
    # Always replace so re-reconcile clears stale actives even when empty.
    replace_paper_improvement_suggestions(pmid, rows)


def apply_reconcile_payload(
    paper_id: int,
    pmid: str,
    payload: dict,
    *,
    study_type: str | None = None,
) -> None:
    """Persist Pass 2 reconcile decisions: datasets, survey/cover, limitations, recommendations, bindings."""
    normalized = parse_reconcile_payload(payload)
    _apply_dataset_actions(
        paper_id, pmid, normalized["datasets"], study_type=study_type
    )
    _apply_survey_cover(
        paper_id,
        pmid,
        normalized["surveyed_methods"],
        normalized["covered_diseases"],
        study_type=study_type,
    )
    _apply_limitation_merges(paper_id, pmid, normalized["limitations"])
    _apply_recommendations(pmid, normalized["recommendations"])
    _apply_bindings(pmid, normalized["bindings"], study_type=study_type)
