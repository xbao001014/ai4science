"""Tests for Gap UI shared prefs (window keys, focus gate, empty-viz hint)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.gap_ui_prefs import (
    EMPTY_VIZ_SUGGESTED_WINDOW_DAYS,
    SHARED_MIN_RECENT_KEY,
    SHARED_WINDOW_DAYS_KEY,
    debate_focus_or_error,
    focus_dependency_caption,
    seed_shared_window_state,
    should_offer_wider_window,
    wider_window_value,
)


def test_shared_keys_are_stable():
    assert SHARED_WINDOW_DAYS_KEY == "corpus_window_days"
    assert SHARED_MIN_RECENT_KEY == "corpus_min_recent"


def test_seed_shared_window_prefers_existing_shared():
    state = {
        SHARED_WINDOW_DAYS_KEY: 45,
        SHARED_MIN_RECENT_KEY: 3,
        "hotspot_window_days": 14,
        "viz_window_days": 90,
    }
    seed_shared_window_state(state, default_window=14, default_min_recent=2)
    assert state[SHARED_WINDOW_DAYS_KEY] == 45
    assert state[SHARED_MIN_RECENT_KEY] == 3


def test_seed_shared_window_migrates_legacy_keys():
    state = {"hotspot_window_days": 60, "viz_min_recent": 1}
    seed_shared_window_state(state, default_window=14, default_min_recent=2)
    assert state[SHARED_WINDOW_DAYS_KEY] == 60
    assert state[SHARED_MIN_RECENT_KEY] == 1


def test_seed_shared_window_uses_defaults_when_empty():
    state: dict = {}
    seed_shared_window_state(state, default_window=14, default_min_recent=2)
    assert state[SHARED_WINDOW_DAYS_KEY] == 14
    assert state[SHARED_MIN_RECENT_KEY] == 2


def test_debate_focus_requires_explicit_full_corpus_when_empty():
    focus, err = debate_focus_or_error("", allow_full_corpus=False)
    assert focus is None
    assert err and "焦点" in err

    focus, err = debate_focus_or_error("", allow_full_corpus=True)
    assert focus is None  # None means full-corpus to agent
    assert err is None

    focus, err = debate_focus_or_error("breast cancer", allow_full_corpus=False)
    assert focus == "breast cancer"
    assert err is None


def test_focus_dependency_caption_mentions_tabs():
    text = focus_dependency_caption(has_focus=False)
    assert "可视化" in text
    assert "辩论" in text


def test_empty_viz_offers_wider_window_when_narrow():
    assert should_offer_wider_window(window_days=14, has_focus=True, gaps_empty=True)
    assert not should_offer_wider_window(window_days=60, has_focus=True, gaps_empty=True)
    assert not should_offer_wider_window(window_days=14, has_focus=False, gaps_empty=True)
    assert not should_offer_wider_window(window_days=14, has_focus=True, gaps_empty=False)
    assert wider_window_value(14) == EMPTY_VIZ_SUGGESTED_WINDOW_DAYS
    assert wider_window_value(70) == 70
