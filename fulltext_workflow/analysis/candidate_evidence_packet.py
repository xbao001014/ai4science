"""Versioned handoff contract from gap debate to proposal generation."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from analysis.evidence_context import load_evidence_context
from analysis.research_quality import evidence_records
from pipeline_utils import parse_gap_sections


SCHEMA_VERSION = "candidate-evidence-packet/v1"
_CANDIDATE_ID_RE = re.compile(
    r"\*\*Candidate\s+ID\*\*\s*[：:]\s*(G\d{2,})\b", re.IGNORECASE
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique_text(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        item = _text(value)
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _empty_packet(gap_text: str = "") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate": {
            "candidate_id": None,
            "title": _text(gap_text),
            "section_md": _text(gap_text),
            "research_question": None,
            "classification": "manual",
            "review_confidence": None,
            "review_summary": "",
        },
        "scope": {
            "focus": None,
            "disease": None,
            "task": None,
            "method": None,
            "endpoint": None,
        },
        "debate": {
            "session_id": None,
            "validation_status": None,
        },
        "corpus": {
            "global_papers": None,
            "focus_papers": None,
            "focus_extracted": None,
            "warnings": [],
        },
        "evidence": {"supports": [], "refutes": [], "context": []},
        "feasibility": {"cross_matrix_rows": [], "catalog_records": []},
        "handoff": {
            "support_pmids": [],
            "linked_papers": [],
            "feasibility_assessment": {},
            "public_dataset_assessment": {},
            "disease_id": None,
            "hypothesis": {},
        },
        "warnings": [],
    }


def _deep_fill(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_fill(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def coerce_candidate_evidence_packet(
    gap_text: str,
    gap_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize v1 and legacy proposal inputs into exactly one stable shape."""
    packet = _empty_packet(gap_text)
    source = gap_data if isinstance(gap_data, dict) else {}
    if source.get("schema_version") == SCHEMA_VERSION:
        _deep_fill(packet, source)
    else:
        section_md = _text(source.get("section_md"))
        if section_md:
            packet["candidate"]["section_md"] = section_md
        candidate_id = source.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id.strip():
            packet["candidate"]["candidate_id"] = candidate_id.strip()
        for old_key, new_key in (
            ("support_pmids", "support_pmids"),
            ("papers", "linked_papers"),
            ("feasibility_assessment", "feasibility_assessment"),
            ("public_dataset_assessment", "public_dataset_assessment"),
            ("disease_id", "disease_id"),
            ("hypothesis", "hypothesis"),
        ):
            if old_key in source:
                packet["handoff"][new_key] = copy.deepcopy(source[old_key])
        if source:
            packet["warnings"].append("legacy_gap_data_adapted_to_v1")

    candidate = packet.get("candidate")
    if not isinstance(candidate, dict):
        packet["candidate"] = _empty_packet(gap_text)["candidate"]
    defaults = _empty_packet(gap_text)
    for key in ("scope", "debate", "corpus", "evidence", "feasibility"):
        if not isinstance(packet.get(key), dict):
            packet[key] = defaults[key]
    packet["candidate"]["title"] = _text(packet["candidate"].get("title")) or _text(gap_text)
    packet["candidate"]["section_md"] = (
        _text(packet["candidate"].get("section_md")) or packet["candidate"]["title"]
    )
    handoff = packet.get("handoff")
    if not isinstance(handoff, dict):
        packet["handoff"] = _empty_packet()["handoff"]
        handoff = packet["handoff"]
    handoff["support_pmids"] = _unique_text(handoff.get("support_pmids"))
    if not isinstance(handoff.get("linked_papers"), list):
        handoff["linked_papers"] = []
    for key in ("feasibility_assessment", "public_dataset_assessment", "hypothesis"):
        if not isinstance(handoff.get(key), dict):
            handoff[key] = {}
    for key in ("supports", "refutes", "context"):
        if not isinstance(packet["evidence"].get(key), list):
            packet["evidence"][key] = []
    if not isinstance(packet.get("warnings"), list):
        packet["warnings"] = []
    return packet


def validate_candidate_evidence_packet(packet: dict[str, Any]) -> list[str]:
    """Return contract errors without throwing at the UI/agent boundary."""
    issues: list[str] = []
    if not isinstance(packet, dict) or packet.get("schema_version") != SCHEMA_VERSION:
        return ["unsupported_schema_version"]
    for key in ("candidate", "scope", "debate", "corpus", "evidence", "feasibility", "handoff"):
        if not isinstance(packet.get(key), dict):
            issues.append(f"invalid_{key}")
    evidence = packet.get("evidence") or {}
    for key in ("supports", "refutes", "context"):
        if not isinstance(evidence.get(key), list):
            issues.append(f"invalid_evidence_{key}")
    return issues


def packet_support_pmids(packet: dict[str, Any]) -> list[str]:
    handoff = packet.get("handoff") if isinstance(packet, dict) else {}
    explicit = _unique_text((handoff or {}).get("support_pmids"))
    if explicit:
        return explicit
    values: list[str] = []
    rows = (packet.get("evidence") or {}).get("supports") or []
    if isinstance(rows, list):
        values.extend(_text(row.get("source_pmid")) for row in rows if isinstance(row, dict))
    return _unique_text(values)


def _review_index(review: dict[str, Any]) -> tuple[dict[str, tuple[str, dict]], dict[str, tuple[str, dict]]]:
    by_id: dict[str, tuple[str, dict]] = {}
    by_title: dict[str, tuple[str, dict]] = {}
    classes = {
        "verified_gaps": "verified",
        "false_gaps": "rejected",
        "weak_evidence_gaps": "needs_evidence",
    }
    for bucket, classification in classes.items():
        rows = review.get(bucket) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            cid = _text(row.get("candidate_id"))
            title = _text(row.get("title")).casefold()
            if cid:
                by_id[cid] = (classification, row)
            if title:
                by_title[title] = (classification, row)
    return by_id, by_title


def _latest_tool_result(evidence_source: Any, tool_name: str) -> dict[str, Any]:
    found: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).split("#", 1)[0] == tool_name and isinstance(item, dict):
                    result = item.get("result", item)
                    if isinstance(result, dict):
                        found.append(result)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(evidence_source)
    return found[-1] if found else {}


def _corpus_summary(evidence_source: Any) -> dict[str, Any]:
    result = _latest_tool_result(evidence_source, "corpus_focus_coverage")
    global_row = result.get("global") or {}
    focus_row = result.get("focus_subset") or {}
    return {
        "global_papers": global_row.get("papers") if isinstance(global_row, dict) else None,
        "focus_papers": focus_row.get("papers") if isinstance(focus_row, dict) else None,
        "focus_extracted": focus_row.get("extracted") if isinstance(focus_row, dict) else None,
        "warnings": _unique_text(result.get("warnings")),
    }


def _candidate_feasibility_rows(evidence_source: Any, section_md: str) -> tuple[list[dict], list[dict]]:
    stopwords = {
        "research", "gap", "candidate", "evidence", "method", "methods",
        "study", "studies", "proposal", "question", "clinical", "analysis",
    }
    words = {
        word.casefold()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", section_md)
        if word.casefold() not in stopwords
    }

    def scoped(tool_name: str) -> list[dict]:
        result = _latest_tool_result(evidence_source, tool_name)
        rows = result.get("data") or result.get("rows") or result.get("records") or []
        if not isinstance(rows, list):
            return []
        typed = [row for row in rows if isinstance(row, dict)]
        if not words:
            return []
        return [
            copy.deepcopy(row)
            for row in typed
            if any(word in json.dumps(row, ensure_ascii=False).casefold() for word in words)
        ]

    return scoped("literature_data_cross_matrix"), scoped("pathology_disease_catalog")


def build_candidate_evidence_packets(
    *,
    report_text: str,
    reviewer: dict[str, Any],
    evidence_source: Any,
    focus: str | None,
    debate_session_id: str | None,
    validation_status: str | None,
) -> dict[str, dict[str, Any]]:
    """Build candidate-scoped packets; never fall back to all debate evidence."""
    registry = {
        _text(row.get("evidence_id")): row
        for row in evidence_records(evidence_source)
        if _text(row.get("evidence_id"))
    }
    by_id, by_title = _review_index(reviewer if isinstance(reviewer, dict) else {})
    corpus = _corpus_summary(evidence_source)
    confidence = reviewer.get("overall_confidence") if isinstance(reviewer, dict) else None
    packets: dict[str, dict[str, Any]] = {}
    for title, section_md in parse_gap_sections(report_text):
        match = _CANDIDATE_ID_RE.search(section_md)
        candidate_id = match.group(1) if match else None
        review_match = by_id.get(candidate_id or "") or by_title.get(title.casefold())
        classification, review_row = review_match or ("unknown", {})
        packet = _empty_packet(title)
        packet["candidate"].update(
            {
                "candidate_id": candidate_id,
                "title": title,
                "section_md": section_md,
                "research_question": review_row.get("research_question"),
                "classification": classification,
                "review_confidence": confidence if isinstance(confidence, (int, float)) else None,
                "review_summary": _text(
                    review_row.get("rationale")
                    or review_row.get("issue")
                    or review_row.get("suggestion")
                ),
            }
        )
        packet["scope"]["focus"] = _text(focus) or None
        packet["debate"].update(
            {"session_id": debate_session_id, "validation_status": validation_status}
        )
        packet["corpus"] = copy.deepcopy(corpus)

        refs = review_row.get("evidence_refs") or []
        if not isinstance(refs, list):
            refs = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            evidence_id = _text(ref.get("evidence_id"))
            source = registry.get(evidence_id)
            if not source:
                packet["warnings"].append(f"unknown_evidence_id:{evidence_id or 'missing'}")
                continue
            cited_source = {**source, "text": _text(ref.get("quote")) or source.get("text")}
            context = load_evidence_context(cited_source)
            stance = _text(ref.get("stance")) or "context"
            row = {
                "evidence_id": evidence_id,
                "source_pmid": context["source_pmid"],
                "title": context["title"],
                "year": context["year"],
                "relation": _text(source.get("relation")),
                "entity_name": _text(source.get("entity_name") or source.get("object")),
                "evidence_section": context["evidence_section"],
                "quote": context["quote"],
                "context_before": context["context_before"],
                "context_after": context["context_after"],
                "context_located": context["context_located"],
                "section_title": context["section_title"],
                "support_status": context["support_status"],
                "stance": stance,
                "kind": _text(source.get("kind")) or "context",
            }
            bucket = {
                "supports_gap": "supports",
                "refutes_gap": "refutes",
            }.get(stance, "context")
            packet["evidence"][bucket].append(row)
            if not context["context_located"]:
                packet["warnings"].append(f"source_context_not_located:{evidence_id}")

        cross_rows, catalog_rows = _candidate_feasibility_rows(evidence_source, section_md)
        packet["feasibility"]["cross_matrix_rows"] = cross_rows
        packet["feasibility"]["catalog_records"] = catalog_rows
        packet["handoff"]["support_pmids"] = packet_support_pmids(packet)
        if not refs:
            packet["warnings"].append("candidate_has_no_reviewer_evidence_refs")
        key = candidate_id or title
        packets[key] = packet
    return packets


def find_candidate_evidence_packet(
    packets: dict[str, dict[str, Any]] | None,
    *,
    title: str,
    section_md: str = "",
) -> dict[str, Any]:
    """Resolve a UI selection by candidate ID first, then exact title."""
    values = packets if isinstance(packets, dict) else {}
    match = _CANDIDATE_ID_RE.search(section_md or "")
    if match and isinstance(values.get(match.group(1)), dict):
        return coerce_candidate_evidence_packet(title, values[match.group(1)])
    for packet in values.values():
        if not isinstance(packet, dict):
            continue
        candidate = packet.get("candidate") or {}
        if _text(candidate.get("title")).casefold() == _text(title).casefold():
            return coerce_candidate_evidence_packet(title, packet)
    return coerce_candidate_evidence_packet(title, {"section_md": section_md or title})
