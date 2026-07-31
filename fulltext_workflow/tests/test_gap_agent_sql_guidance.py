"""Tests for gap-agent SQL fallback guidance."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gap_agent import (  # noqa: E402
    MODERATOR_SYSTEM_PROMPT,
    OPTIMIST_SYSTEM_PROMPT,
    SKEPTIC_SYSTEM_PROMPT,
)


def test_optimist_prompt_does_not_offer_sql_fallback():
    assert "execute_kg_sql" not in OPTIMIST_SYSTEM_PROMPT


def test_optimist_prompt_stays_within_available_tools():
    assert "emerging_gap_opportunities" in OPTIMIST_SYSTEM_PROMPT
    assert "improvement_suggestions_by_topic" in OPTIMIST_SYSTEM_PROMPT
    assert "study_type_relation_stats" not in OPTIMIST_SYSTEM_PROMPT


def test_skeptic_prompt_prefers_sql_for_targeted_verification():
    assert "execute_kg_sql" in SKEPTIC_SYSTEM_PROMPT
    assert "targeted verification" in SKEPTIC_SYSTEM_PROMPT
    assert "focus_expansion" in SKEPTIC_SYSTEM_PROMPT


def test_moderator_prompt_limits_sql_to_conflict_resolution():
    assert "execute_kg_sql" in MODERATOR_SYSTEM_PROMPT
    assert "only to resolve conflicts" in MODERATOR_SYSTEM_PROMPT
    assert "focus_expansion" in MODERATOR_SYSTEM_PROMPT


def test_sql_fallback_guidance_requires_parens_for_mixed_and_or():
    for prompt in (SKEPTIC_SYSTEM_PROMPT, MODERATOR_SYSTEM_PROMPT):
        lower = prompt.lower()
        assert "parenthes" in lower or "(...)" in prompt
        assert "and" in lower and "or" in lower
