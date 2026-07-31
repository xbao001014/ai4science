"""Tests for idea_agent Generator/Critic soft tool slim."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import idea_agent  # noqa: E402
from idea_agent import (  # noqa: E402
    CRITIC_SYSTEM_PROMPT,
    CRITIC_TOOL_NAMES,
    GENERATOR_SYSTEM_PROMPT,
    GENERATOR_TOOL_NAMES,
    build_idea_role_tool_bundle,
)


def test_generator_bundle_size_and_exclusions():
    tools, schemas = build_idea_role_tool_bundle("generator")
    names = [s["function"]["name"] for s in schemas]
    assert names == GENERATOR_TOOL_NAMES
    assert len(names) <= 7
    assert names == [
        "recent_papers_for_topic",
        "methods_for_topic",
        "datasets_for_topic",
        "metrics_for_topic",
        "improvement_suggestions_for_topic",
        "public_dataset_assess",
        "pathology_disease_catalog",
    ]
    assert "execute_kg_sql" not in names
    assert not any(n.startswith("graph_") for n in names)
    assert "author_limitations_for_topic" not in names
    assert set(tools) == set(names)


def test_critic_bundle_has_feasibility_and_sql():
    tools, schemas = build_idea_role_tool_bundle("critic")
    names = [s["function"]["name"] for s in schemas]
    assert names == CRITIC_TOOL_NAMES
    assert len(names) <= 5
    assert names == [
        "feasibility_assess",
        "public_dataset_assess",
        "metrics_for_topic",
        "execute_kg_sql",
        "text_disease_matches",
    ]
    assert "methods_for_topic" not in names
    assert not any(n.startswith("graph_") for n in names)
    assert set(tools) == set(names)


def test_build_idea_role_tool_bundle_unknown_role():
    try:
        build_idea_role_tool_bundle("narrator")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_generator_prompt_uses_budget_not_forced_scan():
    assert "at least 5 tools" not in GENERATOR_SYSTEM_PROMPT
    assert "graph_*" not in GENERATOR_SYSTEM_PROMPT
    assert "≤7" in GENERATOR_SYSTEM_PROMPT or "at most 7" in GENERATOR_SYSTEM_PROMPT.lower()
    assert "improvement_suggestions_for_topic" in GENERATOR_SYSTEM_PROMPT
    assert "public_dataset_assess" in GENERATOR_SYSTEM_PROMPT
    assert "execute_kg_sql" not in GENERATOR_SYSTEM_PROMPT


def test_critic_prompt_limits_sql_and_keeps_feasibility():
    assert "execute_kg_sql" in CRITIC_SYSTEM_PROMPT
    assert "at most 2" in CRITIC_SYSTEM_PROMPT.lower() or "max 2" in CRITIC_SYSTEM_PROMPT.lower()
    assert "feasibility_assess" in CRITIC_SYSTEM_PROMPT
    assert "≤5" in CRITIC_SYSTEM_PROMPT or "at most 5" in CRITIC_SYSTEM_PROMPT.lower()
    assert "graph_*" not in CRITIC_SYSTEM_PROMPT


def test_stream_idea_agent_uses_matching_role_bundles(monkeypatch):
    bundle_calls = []
    agent_calls = []

    def fake_build_bundle(role):
        bundle_calls.append(role)
        return {f"{role}_raw": object()}, [
            {"type": "function", "function": {"name": f"{role}_schema"}}
        ]

    def fake_bind_idea_tools(tools, gap_text):
        name = next(iter(tools))
        return {f"bound_{name}": object()}

    def fake_run_tool_agent(*, messages, tools, tool_schemas, role, **_kwargs):
        agent_calls.append((role, list(tools), tool_schemas))
        if role == "critic":
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "overall_score": 9.0,
                            "accept": True,
                            "feasibility_score": 0.9,
                            "available_cohort_size": 500,
                            "dimension_scores": {},
                            "strengths": [],
                            "critical_issues": [],
                            "kg_verification": "",
                            "data_feasibility_verification": "",
                            "revision_priority": "",
                        }
                    ),
                }
            )
        else:
            messages.append(
                {
                    "role": "assistant",
                    "content": "## 1. Background\nProposal draft",
                }
            )
        if False:
            yield {}

    monkeypatch.setattr(idea_agent, "build_idea_role_tool_bundle", fake_build_bundle)
    monkeypatch.setattr(idea_agent, "bind_idea_tools", fake_bind_idea_tools)
    monkeypatch.setattr(idea_agent, "run_tool_agent", fake_run_tool_agent)
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _t: ("BRCA-IDC", "test"))
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *args, **kwargs: ("## 1. Background\nProposal draft", False),
    )
    monkeypatch.setattr(idea_agent, "load_supporting_papers_for_keyword", lambda *_a, **_k: [])
    monkeypatch.setattr(idea_agent, "load_public_datasets_for_keyword", lambda *_a, **_k: [])

    list(
        idea_agent.stream_idea_agent(
            gap_text="Breast cancer WSI grading gap",
            max_rounds=1,
        )
    )

    assert bundle_calls == ["generator", "critic"]
    assert [c[0] for c in agent_calls] == ["generator", "critic"]
    for role, tools, schemas in agent_calls:
        assert list(tools) == [f"bound_{role}_raw"]
        assert schemas[0]["function"]["name"] == f"{role}_schema"
