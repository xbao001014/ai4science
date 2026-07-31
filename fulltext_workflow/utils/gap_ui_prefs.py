"""Shared Gap UI preferences (window keys, focus gate, empty-viz hints)."""
from __future__ import annotations

from typing import Any, MutableMapping

# Hotspot + visualization bind to the same Streamlit session keys.
# Widgets live once in the sidebar (Streamlit forbids duplicate keys across tabs).
SHARED_WINDOW_DAYS_KEY = "corpus_window_days"
SHARED_MIN_RECENT_KEY = "corpus_min_recent"

_LEGACY_WINDOW_KEYS = ("hotspot_window_days", "viz_window_days")
_LEGACY_MIN_RECENT_KEYS = ("hotspot_min_recent", "viz_min_recent")

EMPTY_VIZ_SUGGESTED_WINDOW_DAYS = 60


def _first_int(state: MutableMapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key not in state:
            continue
        try:
            return int(state[key])
        except (TypeError, ValueError):
            continue
    return None


def seed_shared_window_state(
    state: MutableMapping[str, Any],
    *,
    default_window: int,
    default_min_recent: int,
) -> None:
    """Ensure shared keys exist; migrate legacy per-tab keys when needed."""
    if SHARED_WINDOW_DAYS_KEY not in state:
        migrated = _first_int(state, _LEGACY_WINDOW_KEYS)
        state[SHARED_WINDOW_DAYS_KEY] = (
            migrated if migrated is not None else int(default_window)
        )
    if SHARED_MIN_RECENT_KEY not in state:
        migrated = _first_int(state, _LEGACY_MIN_RECENT_KEYS)
        state[SHARED_MIN_RECENT_KEY] = (
            migrated if migrated is not None else int(default_min_recent)
        )


def debate_focus_or_error(
    focus_text: str,
    *,
    allow_full_corpus: bool,
) -> tuple[str | None, str | None]:
    """
    Resolve debate focus.

    Returns (focus_for_agent, error_message).
    focus_for_agent is None when running full corpus (explicit) or on error.
    """
    text = (focus_text or "").strip()
    if text:
        return text, None
    if allow_full_corpus:
        return None, None
    return None, "请填写研究焦点，或勾选「焦点为空时按全库辩论」。"


def focus_dependency_caption(*, has_focus: bool) -> str:
    if has_focus:
        return (
            "焦点已设：可视化 / 证据可按焦点筛选；辩论与提案将使用该焦点。"
        )
    return (
        "焦点依赖：可视化需焦点；辩论默认可选（空则须显式「按全库」）；"
        "提案需先有报告空白标题。"
    )


def should_offer_wider_window(
    *,
    window_days: int,
    has_focus: bool,
    gaps_empty: bool,
) -> bool:
    return bool(
        has_focus
        and gaps_empty
        and int(window_days) < EMPTY_VIZ_SUGGESTED_WINDOW_DAYS
    )


def wider_window_value(current_window_days: int) -> int:
    return max(int(current_window_days), EMPTY_VIZ_SUGGESTED_WINDOW_DAYS)
