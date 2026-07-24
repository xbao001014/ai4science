from utils.proposal_difficulty_ui import (
    difficulty_display_target,
    support_pmids_from_evidence,
)


def test_difficulty_display_target_ignores_changed_selectbox_value():
    state = {
        "proposal_target_difficulty": "hard",
        "proposal_result_target_difficulty": "easy",
    }

    assert difficulty_display_target(state) == "easy"

    state["proposal_target_difficulty"] = "moderate"
    assert difficulty_display_target(state) == "easy"


def test_difficulty_display_target_falls_back_to_result_event():
    state = {
        "proposal_target_difficulty": "hard",
        "idea_events": [
            {"type": "start", "target_difficulty": "easy"},
            {"type": "difficulty_assessed", "target_difficulty": "moderate"},
        ],
    }

    assert difficulty_display_target(state) == "moderate"


def test_support_pmids_from_debate_evidence():
    evidence = [
        {"PMID": "92000001", "Title/Entity": "Paper A"},
        {"PMID": "92000002", "Title/Entity": "Paper B"},
        {"PMID": "92000001", "Title/Entity": "Duplicate"},
    ]

    assert support_pmids_from_evidence(evidence) == ["92000001", "92000002"]
