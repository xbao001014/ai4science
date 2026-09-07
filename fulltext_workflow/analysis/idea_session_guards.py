"""Session guards for idea_agent: V-01 baseline freeze + tool result cache."""
from __future__ import annotations

import json
from typing import Any, Callable

from analysis.feasibility_tools import normalize_feasibility_field_lists

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
    tokens: set[str] = set()
    for raw in values:
        tok = _norm_token(raw)
        if not tok:
            continue
        tokens.add(_fold(tok))
    return sorted(tokens)


def canonicalize_feasibility_args(**kwargs: Any) -> dict[str, Any]:
    labels = kwargs.get("required_labels")
    markers = kwargs.get("required_molecular_markers")
    anns = kwargs.get("required_annotations")
    normalized = normalize_feasibility_field_lists(
        labels if isinstance(labels, list) else None,
        markers if isinstance(markers, list) else None,
        anns if isinstance(anns, list) else None,
    )
    follow = kwargs.get("min_followup_months")
    try:
        follow_i = int(follow) if follow is not None and str(follow).strip() != "" else 0
    except (TypeError, ValueError):
        follow_i = 0
    return {
        "disease_id": _fold(_norm_token(kwargs.get("disease_id") or "")),
        "task_type": _fold(
            _norm_token(kwargs.get("task_type") or "survival_prediction")
        ),
        "required_labels": _canon_list(normalized["required_labels"]),
        "required_molecular_markers": _canon_list(
            normalized["required_molecular_markers"]
        ),
        "required_annotations": _canon_list(normalized["required_annotations"]),
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


def _canonical_args_json(args: dict[str, Any]) -> str:
    def _norm(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {str(k): _norm(obj[k]) for k in sorted(obj)}
        if isinstance(obj, (list, tuple)):
            return [_norm(x) for x in obj]
        if obj is None:
            return None
        if isinstance(obj, str):
            return obj.strip()
        return obj

    return json.dumps(_norm(args), ensure_ascii=False, sort_keys=True, default=str)


def cache_key(name: str, args: dict[str, Any]) -> str:
    return f"{name}::{_canonical_args_json(args)}"


class ToolResultCache:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0

    def get(self, name: str, args: dict[str, Any]) -> Any | None:
        key = cache_key(name, args)
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def put(self, name: str, args: dict[str, Any], result: Any) -> None:
        if isinstance(result, dict):
            if "error" in result:
                return
            self._store[cache_key(name, args)] = result
        elif result:
            self._store[cache_key(name, args)] = result

    def snapshot(self, *, max_value_chars: int = 4000) -> dict[str, Any]:
        entries: dict[str, Any] = {}
        for key, value in self._store.items():
            raw = json.dumps(value, ensure_ascii=False, default=str)
            entries[key] = (
                value
                if len(raw) <= max_value_chars
                else {"truncated": True, "preview": raw[:max_value_chars]}
            )
        return {"hits": self.hits, "misses": self.misses, "entries": entries}


def wrap_tools_with_cache(
    tools: dict[str, Callable[..., Any]],
    cache: ToolResultCache,
) -> dict[str, Callable[..., Any]]:
    import inspect

    wrapped: dict[str, Callable[..., Any]] = {}
    for name, fn in tools.items():

        def _make(tool_name: str, f: Callable[..., Any]):
            def _wrapped(**kwargs: Any) -> Any:
                hit = cache.get(tool_name, kwargs)
                if hit is not None:
                    return hit
                # get() already counted a miss; call underlying
                result = f(**kwargs)
                cache.put(tool_name, kwargs, result)
                return result

            try:
                _wrapped.__signature__ = inspect.signature(f)  # type: ignore[attr-defined]
            except (TypeError, ValueError):
                pass
            _wrapped.__name__ = getattr(f, "__name__", tool_name)
            return _wrapped

        wrapped[name] = _make(name, fn)
    return wrapped


def _is_successful_feasibility(result: Any) -> bool:
    if not isinstance(result, dict) or "error" in result:
        return False
    raw = result.get("feasibility_score")
    if raw is None or str(raw).strip() == "":
        return False
    try:
        float(raw)
    except (TypeError, ValueError):
        return False
    return True


class IdeaSessionGuards:
    def __init__(self) -> None:
        self.cache = ToolResultCache()
        self.baseline: dict[str, Any] | None = None
        self.relaxed_seen = False
        self.last_spec_relation: str | None = None

    def wrap_tools(
        self, tools: dict[str, Callable[..., Any]]
    ) -> dict[str, Callable[..., Any]]:
        import inspect

        cached = wrap_tools_with_cache(tools, self.cache)
        if "feasibility_assess" not in tools:
            return cached

        underlying = tools["feasibility_assess"]

        def feasibility_assess(**kwargs: Any) -> Any:
            attempted = canonicalize_feasibility_args(**kwargs)
            if self.baseline is None:
                hit = self.cache.get("feasibility_assess", attempted)
                if hit is not None:
                    result = hit
                else:
                    result = underlying(**kwargs)
                    self.cache.put("feasibility_assess", attempted, result)
                if _is_successful_feasibility(result):
                    self.baseline = attempted
                self.last_spec_relation = "same" if self.baseline is not None else None
                return result

            relation = compare_feasibility_specs(self.baseline, attempted)
            self.last_spec_relation = relation
            if relation == "relaxed":
                self.relaxed_seen = True
                return {
                    "error": "feasibility_spec_relaxed",
                    "baseline": dict(self.baseline),
                    "attempted": attempted,
                    "relaxed_fields": relaxed_fields(self.baseline, attempted),
                }

            result = self.cache.get("feasibility_assess", attempted)
            if result is None:
                result = underlying(**kwargs)
                self.cache.put("feasibility_assess", attempted, result)
            return result

        try:
            feasibility_assess.__signature__ = inspect.signature(underlying)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            pass

        out = dict(cached)
        out["feasibility_assess"] = feasibility_assess
        return out

    def snapshot(self) -> dict[str, Any]:
        return {
            "baseline": dict(self.baseline) if self.baseline is not None else None,
            "relaxed_seen": self.relaxed_seen,
            "last_spec_relation": self.last_spec_relation,
            "cache": self.cache.snapshot(),
        }
