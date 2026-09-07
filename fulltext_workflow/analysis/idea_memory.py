"""Persistent checkpoints for Generator × Critic proposal sessions."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from db.schema import checkpoint_idea_session, init_db, insert_idea_session


@dataclass
class IdeaMemoryState:
    session_id: str
    debate_session_id: str | None
    gap_text: str
    max_rounds: int
    current_round: int = 0
    next_role: str = "generator"
    current_draft: str = ""
    last_feedback: dict[str, Any] = field(default_factory=dict)
    guard_snapshot: dict[str, Any] = field(default_factory=dict)
    validation_status: str = ""
    persisted: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, default=str)


def create_idea_memory(
    *,
    gap_text: str,
    max_rounds: int,
    debate_session_id: str | None = None,
) -> IdeaMemoryState:
    state = IdeaMemoryState(
        session_id=str(uuid.uuid4()),
        debate_session_id=debate_session_id,
        gap_text=gap_text,
        max_rounds=max_rounds,
        persisted=bool(debate_session_id),
    )
    if not state.persisted:
        return state
    init_db()
    insert_idea_session(
        session_id=state.session_id,
        debate_session_id=debate_session_id,
        gap_text=gap_text,
        max_rounds=max_rounds,
        state_json=state.to_json(),
    )
    return state


def checkpoint_idea_phase(
    state: IdeaMemoryState,
    *,
    round_no: int,
    role: str,
    next_role: str,
    output_text: str,
    current_draft: str,
    last_feedback: dict[str, Any],
    guard_snapshot: dict[str, Any],
    validation_status: str = "",
    status: str = "running",
) -> None:
    state.current_round = round_no
    state.next_role = next_role
    state.current_draft = current_draft
    state.last_feedback = last_feedback
    state.guard_snapshot = guard_snapshot
    if validation_status:
        state.validation_status = validation_status
    if not state.persisted:
        return
    checkpoint_idea_session(
        state.session_id,
        round_no=round_no,
        role=role,
        next_role=next_role,
        output_text=output_text,
        state_json=state.to_json(),
        status=status,
    )
