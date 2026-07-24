"""Pure session/evidence helpers for proposal difficulty UI state."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def difficulty_display_target(session_state: Mapping[str, Any]) -> str | None:
    """Return the target captured for the rendered proposal result."""
    stored = session_state.get("proposal_result_target_difficulty")
    if stored:
        return str(stored)

    events = session_state.get("idea_events")
    if isinstance(events, Sequence) and not isinstance(events, (str, bytes)):
        for event in reversed(events):
            if (
                isinstance(event, Mapping)
                and event.get("type") in {"difficulty_assessed", "final"}
                and event.get("target_difficulty")
            ):
                return str(event["target_difficulty"])
    return None


def support_pmids_from_evidence(evidence: list[dict]) -> list[str]:
    """Collect unique PMIDs from normalized Gap Debate evidence rows."""
    seen: set[str] = set()
    pmids: list[str] = []
    for row in evidence:
        pmid = str(row.get("PMID") or "").strip()
        if pmid and pmid not in seen:
            seen.add(pmid)
            pmids.append(pmid)
    return pmids
