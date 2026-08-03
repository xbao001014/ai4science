"""Session guards for idea_agent: V-01 baseline freeze + tool result cache."""
from __future__ import annotations

import json
from typing import Any, Callable

_SPEC_KEYS = (
    "disease_id",
    "task_type",
    "required_labels",
    "required_molecular_markers",
    "required_annotations",
    "min_followup_months",
)
_LIST_KEYS = (
    "required_labels",
    "required_molecular_markers",
    "required_annotations",
)


def _norm_token(value: Any) -> str:
    return str(value).strip()


def _fold(value: str) -> str:
    return value.casefold()


def _canon_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    best: dict[str, str] = {}
    for raw in values:
        tok = _norm_token(raw)
        if not tok:
            continue
        key = _fold(tok)
        best.setdefault(key, tok)
    return [best[k] for k in sorted(best)]


def canonicalize_feasibility_args(**kwargs: Any) -> dict[str, Any]:
    labels = kwargs.get("required_labels")
    markers = kwargs.get("required_molecular_markers")
    anns = kwargs.get("required_annotations")
    follow = kwargs.get("min_followup_months")
    try:
        follow_i = int(follow) if follow is not None and str(follow).strip() != "" else 0
    except (TypeError, ValueError):
        follow_i = 0
    return {
        "disease_id": _norm_token(kwargs.get("disease_id") or ""),
        "task_type": _norm_token(kwargs.get("task_type") or "survival_prediction"),
        "required_labels": _canon_list(labels if isinstance(labels, list) else None),
        "required_molecular_markers": _canon_list(
            markers if isinstance(markers, list) else None
        ),
        "required_annotations": _canon_list(anns if isinstance(anns, list) else None),
        "min_followup_months": follow_i,
    }


def _list_set(spec: dict[str, Any], key: str) -> set[str]:
    return {_fold(x) for x in spec.get(key) or []}


def compare_feasibility_specs(baseline: dict, attempted: dict) -> str:
    b = canonicalize_feasibility_args(**baseline)
    a = canonicalize_feasibility_args(**attempted)
    if _fold(b["disease_id"]) != _fold(a["disease_id"]):
        return "relaxed"
    if _fold(b["task_type"]) != _fold(a["task_type"]):
        return "relaxed"
    if int(a["min_followup_months"]) < int(b["min_followup_months"]):
        return "relaxed"

    any_strict = int(a["min_followup_months"]) > int(b["min_followup_months"])
    for key in _LIST_KEYS:
        bs, as_ = _list_set(b, key), _list_set(a, key)
        if not bs.issubset(as_):
            return "relaxed"
        if as_ != bs:
            any_strict = True

    if (
        _fold(b["disease_id"]) == _fold(a["disease_id"])
        and _fold(b["task_type"]) == _fold(a["task_type"])
        and int(a["min_followup_months"]) == int(b["min_followup_months"])
        and all(_list_set(b, k) == _list_set(a, k) for k in _LIST_KEYS)
    ):
        return "same"
    return "tighter" if any_strict else "same"


def relaxed_fields(baseline: dict, attempted: dict) -> list[str]:
    b = canonicalize_feasibility_args(**baseline)
    a = canonicalize_feasibility_args(**attempted)
    fields: list[str] = []
    if _fold(b["disease_id"]) != _fold(a["disease_id"]):
        fields.append("disease_id")
    if _fold(b["task_type"]) != _fold(a["task_type"]):
        fields.append("task_type")
    if int(a["min_followup_months"]) < int(b["min_followup_months"]):
        fields.append("min_followup_months")
    for key in _LIST_KEYS:
        if not _list_set(b, key).issubset(_list_set(a, key)):
            fields.append(key)
    return fields
