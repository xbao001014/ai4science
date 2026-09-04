"""stream_idea_agent must reject accept when V-01 spec was relaxed."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import idea_agent  # noqa: E402


@pytest.mark.parametrize(
    "relaxed_event",
    [
        {
            "type": "tool_result",
            "role": "critic",
            "name": "feasibility_assess",
            "result": {
                "error": "feasibility_spec_relaxed",
                "relaxed_fields": ["required_annotations"],
            },
        },
        {
            "type": "tool_error",
            "role": "critic",
            "name": "feasibility_assess",
            "error": "feasibility_spec_relaxed",
        },
    ],
)
def test_stream_forces_accept_false_on_relaxed_feasibility(
    monkeypatch, relaxed_event
):
    def fake_build_bundle(role: str):
        if role == "generator":
            return {"noop": lambda **k: {}}, [
                {
                    "type": "function",
                    "function": {
                        "name": "noop",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        return {"feasibility_assess": lambda **k: {}}, [
            {
                "type": "function",
                "function": {
                    "name": "feasibility_assess",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def fake_bind(tools, _gap):
        return tools

    def fake_run_tool_agent(*, messages, tools, tool_schemas, role, **_kwargs):
        if role == "generator":
            messages.append(
                {"role": "assistant", "content": "## 1. Background\nDraft"}
            )
            if False:
                yield {}
            return
        yield relaxed_event
        messages.append(
            {
                "role": "assistant",
                "content": (
                    '```json\n{"overall_score": 9.0, "accept": true, '
                    '"feasibility_score": 0.9, "available_cohort_size": 1000, '
                    '"dimension_scores": {}, "strengths": [], '
                    '"critical_issues": [], "kg_verification": "", '
                    '"data_feasibility_verification": "", '
                    '"revision_priority": ""}\n```'
                ),
            }
        )
        if False:
            yield {}

    monkeypatch.setattr(idea_agent, "build_idea_role_tool_bundle", fake_build_bundle)
    monkeypatch.setattr(idea_agent, "bind_idea_tools", fake_bind)
    monkeypatch.setattr(idea_agent, "run_tool_agent", fake_run_tool_agent)
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _t: ("C_CA", "test"))
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *a, **k: ("## 1. Background\nDraft", False),
    )
    monkeypatch.setattr(
        idea_agent, "load_supporting_papers_for_keyword", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        idea_agent, "load_public_datasets_for_keyword", lambda *_a, **_k: []
    )

    events = list(
        idea_agent.stream_idea_agent(
            gap_text="colorectal cancer spatial transcriptomics",
            max_rounds=1,
            accept_score=8.0,
        )
    )
    feedback = [e for e in events if e.get("type") == "feedback"]
    assert feedback, events
    assert feedback[0]["accept"] is False


def test_relaxed_attempt_only_blocks_the_current_critic_round(monkeypatch):
    critic_round = {"n": 0}

    def fake_build_bundle(role: str):
        if role == "generator":
            return {"noop": lambda **k: {}}, [
                {"type": "function", "function": {"name": "noop", "parameters": {}}}
            ]
        return {
            "feasibility_assess": lambda **k: {"feasibility_score": 0.9}
        }, [
            {
                "type": "function",
                "function": {"name": "feasibility_assess", "parameters": {}},
            }
        ]

    def fake_run_tool_agent(*, messages, tools, role, **_kwargs):
        if role == "generator":
            messages.append({"role": "assistant", "content": "## 1. Background\nDraft"})
            return

        critic_round["n"] += 1
        if critic_round["n"] == 1:
            tools["feasibility_assess"](
                disease_id="C_CA",
                required_annotations=["tumor_region"],
            )
            blocked = tools["feasibility_assess"](
                disease_id="C_CA",
                required_annotations=[],
            )
            assert blocked["error"] == "feasibility_spec_relaxed"
            yield {
                "type": "tool_error",
                "name": "feasibility_assess",
                "error": "feasibility_spec_relaxed",
            }
        # Each round must carry fresh successful evidence under the acceptance
        # contract. The first round remains blocked by its relaxation attempt.
        yield {"type": "tool_result", "name": "feasibility_assess",
               "result": {"feasibility_score": 0.9, "available_cohort_size": 1000}}
        yield {"type": "tool_result", "name": "public_dataset_assess",
               "result": {"datasets": []}}
        messages.append(
            {
                "role": "assistant",
                "content": (
                    '{"overall_score": 9.0, "accept": true, '
                    '"feasibility_score": 0.9, "available_cohort_size": 1000}'
                ),
            }
        )

    monkeypatch.setattr(idea_agent, "build_idea_role_tool_bundle", fake_build_bundle)
    monkeypatch.setattr(idea_agent, "bind_idea_tools", lambda tools, _gap: tools)
    monkeypatch.setattr(idea_agent, "run_tool_agent", fake_run_tool_agent)
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _t: ("C_CA", "test"))
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *a, **k: ("## 1. Background\nDraft", False),
    )
    monkeypatch.setattr(
        idea_agent, "load_supporting_papers_for_keyword", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        idea_agent, "load_public_datasets_for_keyword", lambda *_a, **_k: []
    )

    events = list(
        idea_agent.stream_idea_agent(
            gap_text="colorectal cancer spatial transcriptomics",
            max_rounds=2,
            accept_score=8.0,
        )
    )
    feedback = [event for event in events if event.get("type") == "feedback"]
    assert [event["accept"] for event in feedback] == [False, True]


def test_prompts_mention_feasibility_baseline_freeze():
    assert "feasibility" in idea_agent.CRITIC_SYSTEM_PROMPT.lower()
    generator = idea_agent.GENERATOR_SYSTEM_PROMPT.lower()
    assert "relax" in generator or "removing labels" in generator
    critic = idea_agent.CRITIC_SYSTEM_PROMPT.lower()
    assert "baseline" in critic or "first successful" in critic
