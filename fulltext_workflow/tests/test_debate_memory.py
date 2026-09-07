"""Offline tests for persistent multi-role debate working memory."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

_TEST_DB = str(_ROOT / "data" / "test_debate_memory.db")
config.DB_PATH = _TEST_DB

from analysis.debate_memory import (  # noqa: E402
    build_role_handoff,
    checkpoint_phase,
    complete_debate_session,
    create_debate_session,
    load_debate_state,
    persist_tool_event,
    resume_cursor,
    resume_debate_session,
    stabilize_candidate_ids,
)
from analysis.idea_memory import (  # noqa: E402
    checkpoint_idea_phase,
    create_idea_memory,
)
from analysis.idea_session_guards import IdeaSessionGuards  # noqa: E402
from db.schema import (  # noqa: E402
    fetch_debate_session,
    fetch_debate_tool_events,
    fetch_debate_turns,
    fetch_idea_session,
    get_conn,
    init_db,
    list_debate_sessions,
)


def _reset_db() -> None:
    config.DB_PATH = _TEST_DB
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)
    init_db()


def _proposal(title: str, candidate_id: str = "G01") -> str:
    return (
        f"### Candidate gap 1: {title}\n"
        f"**Candidate ID**: {candidate_id}\n"
        "**Research question**: Test?\n"
    )


def test_schema_and_phase_checkpoint_round_trip():
    _reset_db()
    state = create_debate_session(focus="乳腺癌", max_rounds=2, top_n=3)
    checkpoint_phase(
        state,
        round_no=1,
        role="optimist",
        input_text="find gaps",
        output_text=_proposal("Breast cancer WSI survival modeling"),
        evidence={"corpus_focus_coverage": {"result": {"papers": 12}}},
        next_role="skeptic",
    )

    loaded = load_debate_state(state.session_id)
    assert loaded is not None
    assert loaded.focus_key == "breast carcinoma"
    assert loaded.next_role == "skeptic"
    assert loaded.candidates["G01"].title == "Breast cancer WSI survival modeling"
    assert "corpus_focus_coverage" in loaded.evidence_ledger["1"]["optimist"]

    turns = fetch_debate_turns(state.session_id)
    assert [(row["round_no"], row["role"]) for row in turns] == [(1, "optimist")]
    with get_conn() as conn:
        candidate = dict(
            conn.execute(
                "SELECT * FROM debate_candidates WHERE session_id=?",
                (state.session_id,),
            ).fetchone()
        )
    assert candidate["candidate_id"] == "G01"


def test_candidate_id_survives_title_revision_and_review():
    _reset_db()
    state = create_debate_session(focus="npc", max_rounds=2, top_n=3)
    checkpoint_phase(
        state,
        round_no=1,
        role="optimist",
        input_text="v1",
        output_text=_proposal("NPC WSI survival modeling"),
        evidence={},
        next_role="skeptic",
    )
    review = {
        "verified_gaps": [
            {"candidate_id": "G01", "title": "NPC WSI survival modeling"}
        ]
    }
    checkpoint_phase(
        state,
        round_no=1,
        role="skeptic",
        input_text="review",
        output_text="review json",
        evidence={"literature_evidence_search": {"result": {"hits": 2}}},
        next_role="moderator",
        review=review,
    )
    checkpoint_phase(
        state,
        round_no=2,
        role="optimist",
        input_text="revise",
        output_text=_proposal(
            "Multimodal NPC WSI survival modeling", candidate_id="G09"
        ),
        evidence={"author_stated_gaps": {"result": {"hits": 1}}},
        next_role="skeptic",
    )

    assert set(state.candidates) == {"G01"}
    assert state.candidates["G01"].last_round == 2
    assert set(state.evidence_ledger) == {"1", "2"}

    reconciled = stabilize_candidate_ids(
        state,
        _proposal("Multimodal NPC WSI survival modeling", candidate_id="G09"),
        round_no=2,
    )
    assert "**Candidate ID**: G01" in reconciled
    assert "G09" not in reconciled


def test_tool_events_and_completion_are_persisted():
    _reset_db()
    state = create_debate_session(focus=None, max_rounds=1, top_n=2)
    persist_tool_event(
        state,
        round_no=1,
        role="optimist",
        event={
            "type": "tool_call",
            "name": "corpus_focus_coverage",
            "call_id": "call-1",
            "args": {"focus": None},
        },
    )
    persist_tool_event(
        state,
        round_no=1,
        role="optimist",
        event={
            "type": "tool_result",
            "name": "corpus_focus_coverage",
            "call_id": "call-1",
            "result": {"papers": 10},
        },
    )
    complete_debate_session(
        state,
        final_report="# Final",
        validation_status="evidence_checked",
    )

    events = fetch_debate_tool_events(state.session_id)
    assert [row["event_type"] for row in events] == ["tool_call", "tool_result"]
    session = fetch_debate_session(state.session_id)
    assert session is not None
    assert session["status"] == "completed"
    assert session["validation_status"] == "evidence_checked"
    assert session["final_report"] == "# Final"


def test_structured_handoff_tracks_objections_and_unresolved_questions():
    _reset_db()
    state = create_debate_session(focus="npc", max_rounds=2, top_n=2)
    checkpoint_phase(
        state,
        round_no=1,
        role="optimist",
        input_text="draft",
        output_text=_proposal("NPC WSI survival modeling"),
        evidence={"coverage": {"result": {"papers": 10}}},
        next_role="skeptic",
    )
    review = {
        "weak_evidence_gaps": [
            {
                "candidate_id": "G01",
                "issue": "Only one supporting cohort",
                "suggestion": "Find an external validation cohort",
            }
        ],
        "data_concerns": ["Follow-up is incomplete"],
        "revision_priority": "Strengthen external validation",
    }
    handoff = build_role_handoff(
        state,
        from_role="skeptic",
        to_role="moderator",
        round_no=1,
        review=review,
    )
    assert handoff.objections[0]["candidate_id"] == "G01"
    assert "Find an external validation cohort" in handoff.unresolved_questions
    assert handoff.requested_actions == ["Strengthen external validation"]


def test_resume_cursor_continues_from_next_role():
    _reset_db()
    state = create_debate_session(focus="npc", max_rounds=2, top_n=2)
    checkpoint_phase(
        state,
        round_no=1,
        role="optimist",
        input_text="draft",
        output_text=_proposal("NPC WSI survival modeling"),
        evidence={},
        next_role="skeptic",
    )
    resumed = resume_debate_session(state.session_id)
    assert resume_cursor(resumed) == (1, "skeptic")
    assert resumed.rolling_summary
    rows = list_debate_sessions(focus_key=state.focus_key, resumable_only=True)
    assert [row["session_id"] for row in rows] == [state.session_id]


def test_gap_agent_resume_skips_completed_role(monkeypatch):
    import gap_agent

    _reset_db()
    state = create_debate_session(focus=None, max_rounds=1, top_n=1)
    checkpoint_phase(
        state,
        round_no=1,
        role="optimist",
        input_text="draft",
        output_text=_proposal("WSI survival modeling"),
        evidence={},
        next_role="skeptic",
    )

    def fake_agent(*, messages, role, **_kwargs):
        if role == "skeptic":
            content = """```json
{"overall_confidence": 5.0, "verified_gaps": [], "false_gaps": [],
 "weak_evidence_gaps": [{"candidate_id": "G01", "title": "WSI survival modeling",
 "issue": "missing evidence", "suggestion": "verify"}],
 "corpus_limitations": "test", "data_concerns": [], "revision_priority": "verify"}
```"""
        else:
            content = """## Research gap analysis
### Research gap 1: WSI survival modeling
**Candidate ID**: G01
**Research question**: Test?
"""
        messages.append({"role": "assistant", "content": content})
        if False:
            yield {}

    monkeypatch.setattr(gap_agent, "run_tool_agent", fake_agent)
    events = list(
        gap_agent.stream_gap_debate_agent(
            resume_session_id=state.session_id,
            use_ops_memory=False,
        )
    )
    roles = [event["role"] for event in events if event.get("type") == "phase_start"]
    assert roles == ["skeptic", "moderator"]
    assert events[-1]["type"] == "final"
    assert events[-1]["session_id"] == state.session_id
    completed = fetch_debate_session(state.session_id)
    assert completed is not None and completed["status"] == "completed"


def test_idea_checkpoint_persists_guard_and_cache_snapshot():
    _reset_db()
    debate = create_debate_session(focus="npc", max_rounds=2, top_n=2)
    idea = create_idea_memory(
        gap_text="NPC WSI survival modeling",
        max_rounds=2,
        debate_session_id=debate.session_id,
    )
    guards = IdeaSessionGuards()
    guards.baseline = {"disease_id": "by_bnai", "task_type": "survival_prediction"}
    guards.cache.put("public_dataset_assess", {"keyword": "npc"}, {"count": 2})
    checkpoint_idea_phase(
        idea,
        round_no=1,
        role="critic",
        next_role="generator",
        output_text="review",
        current_draft="draft",
        last_feedback={"overall_score": 6.0},
        guard_snapshot=guards.snapshot(),
        validation_status="needs_verification",
    )
    stored = fetch_idea_session(idea.session_id)
    assert stored is not None
    payload = json.loads(stored["state_json"])
    assert payload["guard_snapshot"]["baseline"]["disease_id"] == "by_bnai"
    assert payload["guard_snapshot"]["cache"]["entries"]
    assert stored["next_role"] == "generator"
