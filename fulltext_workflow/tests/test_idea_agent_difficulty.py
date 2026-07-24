import json

import idea_agent


def _fake_agent(messages, **kwargs):
    role = kwargs["role"]
    if role == "generator":
        yield {
            "type": "tool_result",
            "role": role,
            "name": "feasibility_assess",
            "result": {
                "feasibility_score": 0.83,
                "available_cohort_size": 640,
            },
        }
        messages.append({"role": "assistant", "content": "## 1. Background\nProposal"})
    else:
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps({"overall_score": 8.2, "accept": True}),
            }
        )
    return


def test_stream_emits_difficulty_once_and_enriches_final(monkeypatch):
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _gap: (None, "test"))
    monkeypatch.setattr(idea_agent, "run_tool_agent", _fake_agent)
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *args, **kwargs: ("## 1. Background\nProposal", False),
    )
    monkeypatch.setattr(
        idea_agent,
        "load_supporting_papers_for_keyword",
        lambda _keyword: [{"quartile": "Q1", "impact_factor": 10.0}],
    )
    monkeypatch.setattr(
        idea_agent,
        "load_public_datasets_for_keyword",
        lambda _keyword: ["Camelyon17"],
    )

    events = list(
        idea_agent.stream_idea_agent(
            "NPC survival prediction",
            max_rounds=1,
            target_difficulty="easy",
        )
    )

    assessed_events = [event for event in events if event["type"] == "difficulty_assessed"]
    assert len(assessed_events) == 1
    assessed = assessed_events[0]
    assert assessed["target_difficulty"] == "easy"
    assert assessed["breakdown"]["feasibility_score"] == 0.83
    assert assessed["breakdown"]["available_cohort_size"] == 640

    final = events[-1]
    assert final["type"] == "final"
    assert final["target_difficulty"] == assessed["target_difficulty"]
    assert final["assessed_difficulty"] == assessed["assessed_difficulty"]
    assert final["difficulty_delta"] == assessed["difficulty_delta"]
    assert final["difficulty_color"] == assessed["color"]
    assert final["difficulty_summary"] == assessed["summary_line"]
    assert final["q_coverage_low"] == assessed["q_coverage_low"]
    assert final["difficulty_breakdown"] == assessed["breakdown"]
    assert final["content"].startswith("> **Difficulty**")
    assert final["content"].count("> **Difficulty**") == 1


def _failing_generator(messages, **kwargs):
    yield {"type": "error", "role": kwargs["role"], "message": "generator failed"}
    return


def test_stream_aborted_final_includes_difficulty_fields(monkeypatch):
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _gap: (None, "test"))
    monkeypatch.setattr(idea_agent, "run_tool_agent", _failing_generator)
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *args, **kwargs: ("", False),
    )
    monkeypatch.setattr(idea_agent, "load_supporting_papers_for_keyword", lambda _keyword: [])
    monkeypatch.setattr(idea_agent, "load_public_datasets_for_keyword", lambda _keyword: [])

    events = list(
        idea_agent.stream_idea_agent(
            "NPC survival prediction",
            max_rounds=1,
            target_difficulty="moderate",
        )
    )

    assessed = next(event for event in events if event["type"] == "difficulty_assessed")
    final = events[-1]
    assert final["type"] == "final"
    assert final["aborted"] is True
    assert final["content"] == ""
    assert final["target_difficulty"] == assessed["target_difficulty"]
    assert final["assessed_difficulty"] == assessed["assessed_difficulty"]
    assert final["difficulty_delta"] == assessed["difficulty_delta"]
    assert final["difficulty_color"] == assessed["color"]
    assert final["difficulty_summary"] == assessed["summary_line"]
    assert final["q_coverage_low"] == assessed["q_coverage_low"]
    assert final["difficulty_breakdown"] == assessed["breakdown"]


def test_invalid_target_defaults_to_moderate_and_existing_header_is_not_duplicated(
    monkeypatch,
):
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _gap: (None, "test"))
    monkeypatch.setattr(idea_agent, "run_tool_agent", _fake_agent)
    monkeypatch.setattr(idea_agent, "load_supporting_papers_for_keyword", lambda _keyword: [])
    monkeypatch.setattr(idea_agent, "load_public_datasets_for_keyword", lambda _keyword: [])
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *args, **kwargs: ("> **Difficulty** · existing\n\n## 1. Background\nProposal", False),
    )

    events = list(
        idea_agent.stream_idea_agent(
            "NPC survival prediction",
            max_rounds=1,
            target_difficulty="impossible",
        )
    )

    assessed = next(event for event in events if event["type"] == "difficulty_assessed")
    final = events[-1]
    assert assessed["target_difficulty"] == "moderate"
    assert final["content"].count("> **Difficulty**") == 1


def test_gap_linked_pmids_are_preferred_over_keyword_papers(monkeypatch):
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _gap: (None, "test"))
    monkeypatch.setattr(idea_agent, "run_tool_agent", _failing_generator)
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *args, **kwargs: ("", False),
    )
    monkeypatch.setattr(
        idea_agent,
        "load_supporting_papers_by_pmids",
        lambda pmids: [
            {"pmid": pmids[0], "quartile": "Q1", "impact_factor": 12.0}
        ],
    )
    monkeypatch.setattr(
        idea_agent,
        "load_supporting_papers_for_keyword",
        lambda _keyword: (_ for _ in ()).throw(
            AssertionError("keyword fallback must not run")
        ),
    )
    monkeypatch.setattr(idea_agent, "load_public_datasets_for_keyword", lambda _kw: [])

    events = list(
        idea_agent.stream_idea_agent(
            "NPC survival prediction",
            gap_data={"support_pmids": ["92000002"]},
            max_rounds=1,
        )
    )

    assessed = next(event for event in events if event["type"] == "difficulty_assessed")
    assert assessed["research_bar"] == "hard"
    assert assessed["breakdown"]["support_paper_cnt"] == 1


def test_gap_linked_paper_rows_are_preferred_over_all_loaders(monkeypatch):
    monkeypatch.setattr(idea_agent, "_gap_disease_hint", lambda _gap: (None, "test"))
    monkeypatch.setattr(idea_agent, "run_tool_agent", _failing_generator)
    monkeypatch.setattr(
        idea_agent,
        "_ensure_proposal_draft",
        lambda *args, **kwargs: ("", False),
    )
    fail = lambda *_args: (_ for _ in ()).throw(
        AssertionError("paper loader must not run")
    )
    monkeypatch.setattr(idea_agent, "load_supporting_papers_by_pmids", fail)
    monkeypatch.setattr(idea_agent, "load_supporting_papers_for_keyword", fail)
    monkeypatch.setattr(idea_agent, "load_public_datasets_for_keyword", lambda _kw: [])

    events = list(
        idea_agent.stream_idea_agent(
            "NPC survival prediction",
            gap_data={
                "papers": [
                    {"pmid": "92000004", "quartile": "Q1", "impact_factor": 15.0}
                ]
            },
            max_rounds=1,
        )
    )

    assessed = next(event for event in events if event["type"] == "difficulty_assessed")
    assert assessed["research_bar"] == "hard"
