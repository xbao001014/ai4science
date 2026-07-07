"""Human-readable summaries for tool results shown in the Streamlit status log."""

from __future__ import annotations


def record_count(result: dict) -> int:
    return len(result.get("data", result.get("gaps", result.get("results_backed", []))))


def is_summary_result(tool_name: str, result: dict) -> bool:
    if tool_name == "corpus_focus_coverage":
        return "focus_subset" in result or "global" in result
    return record_count(result) == 0 and bool(result)


def extract_corpus_focus_metrics(result: dict) -> dict | None:
    focus_subset = result.get("focus_subset") or {}
    global_stats = result.get("global") or {}
    if not focus_subset and not global_stats:
        return None
    return {
        "focus": result.get("focus"),
        "focus_papers": focus_subset.get("papers", 0),
        "focus_extracted": focus_subset.get("extracted", 0),
        "limitation_relations": focus_subset.get("limitation_relations", 0),
        "method_entities": focus_subset.get("method_entities", 0),
        "disease_entities": focus_subset.get("disease_entities", 0),
        "global_papers": global_stats.get("papers", 0),
        "global_extracted": global_stats.get("extracted", 0),
        "global_fulltext": global_stats.get("fulltext_available", 0),
        "coverage_ratio": result.get("coverage_ratio"),
        "analysis_ready": result.get("analysis_ready"),
        "warnings": result.get("warnings") or [],
        "top_diseases": focus_subset.get("top_diseases") or [],
    }


def format_tool_result_summary(tool_name: str, result: dict) -> str:
    """Return a short status line for a tool result."""
    if tool_name == "corpus_focus_coverage":
        metrics = extract_corpus_focus_metrics(result)
        if metrics is not None:
            return (
                f"focus subset: {metrics['focus_papers']} papers / "
                f"global: {metrics['global_papers']}"
            )

    return f"{record_count(result)} records"
