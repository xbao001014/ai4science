import gap_agent

from gap_agent import (
    MODERATOR_SYSTEM_PROMPT,
    MODERATOR_TOOL_NAMES,
    OPTIMIST_SYSTEM_PROMPT,
    OPTIMIST_TOOL_NAMES,
    SKEPTIC_SYSTEM_PROMPT,
    SKEPTIC_TOOL_NAMES,
    build_role_tool_bundle,
)


def test_optimist_bundle_size_and_exclusions():
    tools, schemas = build_role_tool_bundle("optimist")
    names = [s["function"]["name"] for s in schemas]
    assert names == OPTIMIST_TOOL_NAMES
    assert len(names) <= 6
    assert "method_disease_combo_gap" not in names
    assert not any(n.startswith("graph_") for n in names)
    assert "execute_kg_sql" not in names
    assert set(tools) == set(names)


def test_skeptic_bundle_has_sql_not_scanners():
    tools, schemas = build_role_tool_bundle("skeptic")
    names = [s["function"]["name"] for s in schemas]
    assert names == SKEPTIC_TOOL_NAMES
    assert "execute_kg_sql" in names
    assert "method_disease_combo_gap" not in names
    assert not any(n.startswith("graph_") for n in names)


def test_moderator_bundle_feasibility_focused():
    tools, schemas = build_role_tool_bundle("moderator")
    names = [s["function"]["name"] for s in schemas]
    assert names == MODERATOR_TOOL_NAMES
    assert "literature_data_cross_matrix" in names
    assert "pathology_disease_catalog" in names
    assert "subtype_distribution" not in names
    assert "disease_cohort_stats" not in names


def test_build_role_tool_bundle_unknown_role():
    try:
        build_role_tool_bundle("narrator")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_optimist_prompt_uses_budget_not_forced_scan():
    assert "at least 5 tools" not in OPTIMIST_SYSTEM_PROMPT
    assert "graph_*" not in OPTIMIST_SYSTEM_PROMPT
    assert "≤6" in OPTIMIST_SYSTEM_PROMPT or "at most 6" in OPTIMIST_SYSTEM_PROMPT.lower()
    assert "emerging_gap_opportunities" in OPTIMIST_SYSTEM_PROMPT
    assert "improvement_suggestions_by_topic" in OPTIMIST_SYSTEM_PROMPT


def test_skeptic_prompt_limits_sql_and_scan():
    assert "execute_kg_sql" in SKEPTIC_SYSTEM_PROMPT
    assert "at most 2" in SKEPTIC_SYSTEM_PROMPT.lower() or "max 2" in SKEPTIC_SYSTEM_PROMPT.lower()
    assert "method_disease_combo_gap" not in SKEPTIC_SYSTEM_PROMPT


def test_moderator_prompt_prefers_feasibility_tools():
    assert "literature_data_cross_matrix" in MODERATOR_SYSTEM_PROMPT
    assert "pathology_disease_catalog" in MODERATOR_SYSTEM_PROMPT
    assert "at most 4" in MODERATOR_SYSTEM_PROMPT.lower() or "≤4" in MODERATOR_SYSTEM_PROMPT


def test_stream_gap_debate_agent_uses_matching_role_bundles(monkeypatch):
    bundle_calls = []
    agent_calls = []

    def fake_build_bundle(role):
        bundle_calls.append(role)
        return {f"{role}_raw": object()}, [
            {"type": "function", "function": {"name": f"{role}_schema"}}
        ]

    def fake_bind_tools(tools, focus):
        name = next(iter(tools))
        return {f"bound_{name}_{focus}": object()}

    def fake_run_tool_agent(*, messages, tools, tool_schemas, role, **_kwargs):
        agent_calls.append((role, list(tools), tool_schemas))
        if role == "skeptic":
            content = '{"overall_confidence": 5.0, "verified_gaps": [], "false_gaps": []}'
        elif role == "moderator":
            moderator_call_count = sum(call[0] == "moderator" for call in agent_calls)
            content = (
                "```json\n"
                '{"accept": false, "overall_confidence": 5.0, "revision_priority": "revise"}'
                "\n```"
                if moderator_call_count == 1
                else "# Final report"
            )
        else:
            content = "Optimist proposal"
        messages.append({"role": "assistant", "content": content})
        if False:
            yield {}

    monkeypatch.setattr(gap_agent, "build_role_tool_bundle", fake_build_bundle)
    monkeypatch.setattr(gap_agent, "bind_tools_with_focus", fake_bind_tools)
    monkeypatch.setattr(gap_agent, "run_tool_agent", fake_run_tool_agent)
    monkeypatch.setattr(gap_agent, "_corpus_context", lambda _focus: "corpus")
    monkeypatch.setattr(gap_agent, "resolve_ops_memory_block", lambda *_args: "")

    list(
        gap_agent.stream_gap_debate_agent(
            focus="test focus",
            max_debate_rounds=2,
            use_ops_memory=False,
        )
    )

    assert bundle_calls == ["optimist", "skeptic", "moderator"]
    expected_round_calls = [
        (
            "optimist",
            ["bound_optimist_raw_test focus"],
            [{"type": "function", "function": {"name": "optimist_schema"}}],
        ),
        (
            "skeptic",
            ["bound_skeptic_raw_test focus"],
            [{"type": "function", "function": {"name": "skeptic_schema"}}],
        ),
        (
            "moderator",
            ["bound_moderator_raw_test focus"],
            [{"type": "function", "function": {"name": "moderator_schema"}}],
        ),
    ]
    assert agent_calls == expected_round_calls * 2
