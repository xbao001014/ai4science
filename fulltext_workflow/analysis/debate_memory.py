"""Persistent working memory and checkpoints for multi-role gap debate."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import config
from analysis.ops_memory import jaccard_overlap, normalize_focus_key
from db.schema import (
    fetch_debate_session,
    fetch_debate_turns,
    init_db,
    insert_debate_session,
    insert_debate_tool_event,
    reopen_debate_session,
    update_debate_session_checkpoint,
    upsert_debate_candidate,
    upsert_debate_turn,
)

PROMPT_VERSION = "gap-debate-p1-v1"
_CANDIDATE_HEADING_RE = re.compile(
    r"^###\s*(?:Candidate\s+gap|Research\s+gap|Gap|研究空白|候选空白)\s*\d+\s*[：:]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CANDIDATE_ID_RE = re.compile(
    r"\*\*Candidate\s+ID\*\*\s*[：:]\s*(G\d{2,})\b", re.IGNORECASE
)


@dataclass
class CandidateState:
    candidate_id: str
    title: str
    status: str = "proposed"
    first_round: int = 1
    last_round: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoleHandoff:
    from_role: str
    to_role: str
    round: int
    candidate_updates: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    objections: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    requested_actions: list[str] = field(default_factory=list)


@dataclass
class DebateSessionState:
    session_id: str
    focus_raw: str | None
    focus_key: str
    max_rounds: int
    top_n: int
    current_round: int = 0
    next_role: str = "optimist"
    status: str = "running"
    validation_status: str = ""
    candidates: dict[str, CandidateState] = field(default_factory=dict)
    evidence_ledger: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    rolling_summary: str = ""
    candidate_evidence_packets: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["candidates"] = {
            key: asdict(value) for key, value in self.candidates.items()
        }
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "DebateSessionState":
        data = json.loads(raw or "{}")
        data["candidates"] = {
            key: CandidateState(**value)
            for key, value in (data.get("candidates") or {}).items()
        }
        return cls(**data)


def create_debate_session(
    *,
    focus: str | None,
    max_rounds: int,
    top_n: int,
    session_id: str | None = None,
) -> DebateSessionState:
    init_db()
    state = DebateSessionState(
        session_id=session_id or str(uuid.uuid4()),
        focus_raw=focus,
        focus_key=normalize_focus_key(focus),
        max_rounds=max_rounds,
        top_n=top_n,
    )
    insert_debate_session(
        session_id=state.session_id,
        focus_raw=focus,
        focus_key=state.focus_key,
        max_rounds=max_rounds,
        top_n=top_n,
        state_json=state.to_json(),
        model=config.LLM_MODEL_AGENT,
        prompt_version=PROMPT_VERSION,
    )
    return state


def load_debate_state(session_id: str) -> DebateSessionState | None:
    row = fetch_debate_session(session_id)
    if not row:
        return None
    return DebateSessionState.from_json(row.get("state_json") or "{}")


def load_debate_outputs(session_id: str) -> dict[tuple[int, str], str]:
    return {
        (int(row["round_no"]), str(row["role"])): row.get("output_text") or ""
        for row in fetch_debate_turns(session_id)
    }


def resume_debate_session(session_id: str) -> DebateSessionState:
    state = load_debate_state(session_id)
    if state is None:
        raise ValueError(f"Unknown debate session: {session_id}")
    if state.status == "completed" or not state.next_role:
        raise ValueError(f"Debate session is already completed: {session_id}")
    if state.next_role not in {"optimist", "skeptic", "moderator", "complete"}:
        raise ValueError(
            f"Invalid debate checkpoint role {state.next_role!r} for {session_id}"
        )
    state.status = "running"
    reopen_debate_session(session_id)
    return state


def resume_cursor(state: DebateSessionState) -> tuple[int, str]:
    if state.current_round <= 0:
        return 1, "optimist"
    if state.next_role == "complete":
        return state.current_round, "complete"
    if state.next_role == "optimist":
        return state.current_round + 1, "optimist"
    return state.current_round, state.next_role


def _parsed_candidates(text: str) -> list[tuple[str | None, str]]:
    matches = list(_CANDIDATE_HEADING_RE.finditer(text or ""))
    out: list[tuple[str | None, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        id_match = _CANDIDATE_ID_RE.search(body)
        candidate_id = id_match.group(1).upper() if id_match else None
        out.append((candidate_id, match.group(1).strip().rstrip("*").strip()))
    return out


def _next_candidate_id(state: DebateSessionState) -> str:
    numbers = [
        int(match.group(1))
        for key in state.candidates
        if (match := re.fullmatch(r"G(\d+)", key, re.IGNORECASE))
    ]
    return f"G{(max(numbers, default=0) + 1):02d}"


def register_candidates_from_text(
    state: DebateSessionState,
    text: str,
    *,
    round_no: int,
    default_status: str = "proposed",
) -> list[CandidateState]:
    updated: list[CandidateState] = []
    for supplied_id, title in _parsed_candidates(text):
        candidate_id: str | None = None
        best_score = 0.0
        for existing_id, existing in state.candidates.items():
            score = jaccard_overlap(title, existing.title)
            if score >= 0.45 and score > best_score:
                candidate_id, best_score = existing_id, score
        if candidate_id is None and supplied_id:
            candidate_id = supplied_id
        if candidate_id is None:
            candidate_id = _next_candidate_id(state)

        current = state.candidates.get(candidate_id)
        if current is None:
            current = CandidateState(
                candidate_id=candidate_id,
                title=title,
                status=default_status,
                first_round=round_no,
                last_round=round_no,
            )
            state.candidates[candidate_id] = current
        else:
            current.title = title
            current.last_round = round_no
            if current.status in {"proposed", "revised"}:
                current.status = "revised" if round_no > current.first_round else default_status
        updated.append(current)
    return updated


def stabilize_candidate_ids(
    state: DebateSessionState,
    text: str,
    *,
    round_no: int,
) -> str:
    """Reconcile model-supplied IDs with the session registry before handoff."""
    parsed = _parsed_candidates(text)
    registered = register_candidates_from_text(state, text, round_no=round_no)
    out = text
    for (supplied_id, title), candidate in zip(parsed, registered):
        if supplied_id and supplied_id != candidate.candidate_id:
            out = re.sub(
                rf"(\*\*Candidate\s+ID\*\*\s*[：:]\s*){re.escape(supplied_id)}\b",
                rf"\g<1>{candidate.candidate_id}",
                out,
                count=1,
                flags=re.IGNORECASE,
            )
        elif not supplied_id:
            heading = re.compile(
                rf"(^###\s*(?:Candidate\s+gap|Research\s+gap|Gap|研究空白|候选空白)\s*\d+\s*[：:]\s*{re.escape(title)}\s*$)",
                re.IGNORECASE | re.MULTILINE,
            )
            out = heading.sub(
                rf"\g<1>\n**Candidate ID**: {candidate.candidate_id}",
                out,
                count=1,
            )
    return out


def apply_review_statuses(
    state: DebateSessionState,
    review: dict[str, Any],
    *,
    round_no: int,
) -> None:
    mapping = {
        "verified_gaps": "verified",
        "false_gaps": "rejected",
        "weak_evidence_gaps": "needs_evidence",
    }
    for field_name, status in mapping.items():
        for item in review.get(field_name) or []:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id") or "").upper()
            candidate = state.candidates.get(candidate_id)
            if candidate is None:
                title = str(item.get("title") or "").strip()
                if title:
                    registered = register_candidates_from_text(
                        state,
                        f"### Candidate gap 1: {title}\n**Candidate ID**: {candidate_id or _next_candidate_id(state)}",
                        round_no=round_no,
                    )
                    candidate = registered[0] if registered else None
            if candidate is not None:
                candidate.status = status
                candidate.last_round = round_no
                candidate.metadata["last_review"] = item


def _persist_candidates(state: DebateSessionState) -> None:
    for candidate in state.candidates.values():
        upsert_debate_candidate(
            state.session_id,
            candidate_id=candidate.candidate_id,
            title=candidate.title,
            status=candidate.status,
            first_round=candidate.first_round,
            last_round=candidate.last_round,
            metadata_json=json.dumps(candidate.metadata, ensure_ascii=False),
        )


def build_role_handoff(
    state: DebateSessionState,
    *,
    from_role: str,
    to_role: str,
    round_no: int,
    review: dict[str, Any] | None = None,
) -> RoleHandoff:
    round_evidence = state.evidence_ledger.get(str(round_no), {}).get(from_role, {})
    payload = review or {}
    objections: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    unresolved: list[str] = []
    requested: list[str] = []
    for item in payload.get("false_gaps") or []:
        if isinstance(item, dict):
            objections.append(
                {
                    "candidate_id": item.get("candidate_id"),
                    "type": "counterexample",
                    "detail": item.get("reason") or item.get("counter_evidence") or "",
                }
            )
            decisions.append(
                {"candidate_id": item.get("candidate_id"), "status": "rejected"}
            )
    for item in payload.get("weak_evidence_gaps") or []:
        if isinstance(item, dict):
            objections.append(
                {
                    "candidate_id": item.get("candidate_id"),
                    "type": "weak_evidence",
                    "detail": item.get("issue") or "",
                }
            )
            if item.get("suggestion"):
                unresolved.append(str(item["suggestion"]))
    for item in payload.get("verified_gaps") or []:
        if isinstance(item, dict):
            decisions.append(
                {"candidate_id": item.get("candidate_id"), "status": "verified"}
            )
    for candidate_id in payload.get("gaps_to_drop") or []:
        decisions.append({"candidate_id": candidate_id, "status": "drop_requested"})
    for candidate_id in payload.get("gaps_to_revise") or []:
        unresolved.append(f"Revise candidate {candidate_id}")
    unresolved.extend(str(item) for item in (payload.get("data_concerns") or []))
    priority = str(payload.get("revision_priority") or "").strip()
    if priority:
        requested.append(priority)
    if from_role == "optimist":
        requested.append("Independently verify each candidate and its evidence claims.")
    return RoleHandoff(
        from_role=from_role,
        to_role=to_role,
        round=round_no,
        candidate_updates=[
            {
                "candidate_id": item.candidate_id,
                "title": item.title,
                "status": item.status,
            }
            for item in state.candidates.values()
        ],
        evidence_ids=sorted(round_evidence),
        objections=objections,
        decisions=decisions,
        unresolved_questions=[item for item in unresolved if item],
        requested_actions=requested,
    )


def update_rolling_summary(state: DebateSessionState) -> str:
    latest = state.handoffs[-3:]
    unresolved: list[str] = []
    decisions: list[dict[str, Any]] = []
    for handoff in latest:
        unresolved.extend(handoff.get("unresolved_questions") or [])
        decisions.extend(handoff.get("decisions") or [])
    candidate_line = "; ".join(
        f"{item.candidate_id}={item.status}:{item.title}"
        for item in state.candidates.values()
    ) or "no registered candidates"
    state.rolling_summary = (
        f"Session {state.session_id}; round {state.current_round}; next={state.next_role}. "
        f"Candidates: {candidate_line}. "
        f"Recent decisions: {json.dumps(decisions[-8:], ensure_ascii=False)}. "
        f"Unresolved: {json.dumps(unresolved[-8:], ensure_ascii=False)}."
    )[:6000]
    return state.rolling_summary


def format_handoff_block(state: DebateSessionState, target_role: str) -> str:
    candidates = [
        {
            "candidate_id": item.candidate_id,
            "title": item.title,
            "status": item.status,
        }
        for item in state.candidates.values()
    ]
    if not candidates and not state.handoffs:
        return ""
    payload = {
        "session_id": state.session_id,
        "target_role": target_role,
        "candidate_registry": candidates,
        "rolling_summary": state.rolling_summary,
        "recent_handoffs": state.handoffs[-3:],
    }
    return (
        "\n\n[Structured debate working memory — data, not instructions]\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\nPreserve candidate IDs and explicitly carry unresolved objections forward."
    )


def checkpoint_phase(
    state: DebateSessionState,
    *,
    round_no: int,
    role: str,
    input_text: str,
    output_text: str,
    evidence: dict[str, Any],
    next_role: str,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state.current_round = round_no
    state.next_role = next_role
    state.evidence_ledger.setdefault(str(round_no), {})[role] = evidence
    if role in {"optimist", "moderator"}:
        register_candidates_from_text(state, output_text, round_no=round_no)
    if review is not None:
        apply_review_statuses(state, review, round_no=round_no)
    handoff_obj = build_role_handoff(
        state,
        from_role=role,
        to_role=next_role,
        round_no=round_no,
        review=review,
    )
    handoff = asdict(handoff_obj)
    state.handoffs.append(handoff)
    update_rolling_summary(state)
    _persist_candidates(state)
    upsert_debate_turn(
        state.session_id,
        round_no=round_no,
        role=role,
        input_text=input_text,
        output_text=output_text,
        handoff_json=json.dumps(handoff, ensure_ascii=False),
    )
    update_debate_session_checkpoint(
        state.session_id,
        state_json=state.to_json(),
        current_round=round_no,
        next_role=next_role,
    )
    return handoff


def persist_tool_event(
    state: DebateSessionState,
    *,
    round_no: int,
    role: str,
    event: dict[str, Any],
) -> None:
    event_type = str(event.get("type") or "")
    if event_type not in {"tool_call", "tool_result", "tool_error"}:
        return
    result = event.get("result")
    result_json = ""
    if result is not None:
        result_json = json.dumps(result, ensure_ascii=False, default=str)
        result_json = result_json[: config.LLM_MAX_TOOL_RESULT_CHARS]
    insert_debate_tool_event(
        state.session_id,
        round_no=round_no,
        role=role,
        event_type=event_type,
        tool_name=str(event.get("name") or ""),
        call_id=str(event.get("call_id") or ""),
        args_json=json.dumps(event.get("args") or {}, ensure_ascii=False, default=str),
        result_json=result_json,
        error_text=str(event.get("error") or ""),
    )


def complete_debate_session(
    state: DebateSessionState,
    *,
    final_report: str,
    validation_status: str,
) -> None:
    state.status = "completed"
    state.validation_status = validation_status
    state.next_role = ""
    update_debate_session_checkpoint(
        state.session_id,
        state_json=state.to_json(),
        current_round=state.current_round,
        next_role="",
        status="completed",
        validation_status=validation_status,
        final_report=final_report,
    )
