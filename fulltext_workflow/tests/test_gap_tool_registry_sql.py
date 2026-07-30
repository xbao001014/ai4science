"""Regression coverage for the merged gap-tool registry."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.graph_tools import GAP_TOOL_SCHEMAS, init_gap_registry  # noqa: E402


def test_execute_kg_sql_present_in_merged_gap_tool_schemas():
    init_gap_registry()
    names = [tool["function"]["name"] for tool in GAP_TOOL_SCHEMAS]
    assert "execute_kg_sql" in names


def test_execute_kg_sql_schema_describes_fallback_usage():
    init_gap_registry()
    schema = next(
        tool["function"]
        for tool in GAP_TOOL_SCHEMAS
        if tool["function"]["name"] == "execute_kg_sql"
    )
    description = schema["description"]
    assert "Use when pre-built tools cannot answer" in description
    assert "custom joins, aggregations, year filters, or exact verification" in description
    assert "Returns up to 100 rows" in description
    assert "papers(id, pmid," in description
    assert "entities(id, name, type" in description
    assert "There is no papers.paper_id" in description


def test_study_type_relation_stats_present_in_merged_gap_tool_schemas():
    init_gap_registry()
    names = [tool["function"]["name"] for tool in GAP_TOOL_SCHEMAS]
    assert "study_type_relation_stats" in names


def test_study_type_relation_stats_in_sql_tools():
    from analysis.gap_tools import SQL_TOOLS

    assert "study_type_relation_stats" in SQL_TOOLS
