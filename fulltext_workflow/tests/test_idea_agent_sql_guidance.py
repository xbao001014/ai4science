"""Tests for idea-agent SQL fallback guidance."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import idea_agent  # noqa: E402
from analysis.gap_tools import tool_execute_kg_sql  # noqa: E402


def test_idea_agent_prompt_mentions_execute_kg_sql():
    assert "execute_kg_sql" in idea_agent.CRITIC_SYSTEM_PROMPT
    assert "execute_kg_sql" not in idea_agent.GENERATOR_SYSTEM_PROMPT
    assert "free-form SQL" in idea_agent.GENERATOR_SYSTEM_PROMPT


def test_idea_agent_prompt_keeps_sql_as_fallback():
    assert "Use curated tools first" in idea_agent.CRITIC_SYSTEM_PROMPT
    assert "custom join" in idea_agent.CRITIC_SYSTEM_PROMPT


def test_idea_agent_registers_sql_fallback_tool_and_schema():
    assert idea_agent.IDEA_TOOLS["execute_kg_sql"] is tool_execute_kg_sql
    schema_names = {
        tool["function"]["name"] for tool in idea_agent.IDEA_TOOL_SCHEMAS
    }
    assert "execute_kg_sql" in schema_names
