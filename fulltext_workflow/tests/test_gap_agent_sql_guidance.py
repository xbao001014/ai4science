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


def test_optimist_prompt_says_curated_tools_first():
    assert "Use curated tools first" in OPTIMIST_SYSTEM_PROMPT
    assert "execute_kg_sql" in OPTIMIST_SYSTEM_PROMPT


def test_skeptic_prompt_prefers_sql_for_targeted_verification():
    assert "execute_kg_sql" in SKEPTIC_SYSTEM_PROMPT
    assert "targeted verification" in SKEPTIC_SYSTEM_PROMPT


def test_moderator_prompt_limits_sql_to_conflict_resolution():
    assert "execute_kg_sql" in MODERATOR_SYSTEM_PROMPT
    assert "only to resolve conflicts" in MODERATOR_SYSTEM_PROMPT
