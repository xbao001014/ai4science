"""Tests for the read-only fallback SQL tool."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.gap_tools import tool_execute_kg_sql  # noqa: E402
from db.schema import get_conn, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    init_db()


def test_execute_kg_sql_allows_simple_select():
    result = tool_execute_kg_sql("SELECT 1 AS value")
    assert result["data"] == [{"value": 1}]


def test_execute_kg_sql_rejects_write_statement():
    result = tool_execute_kg_sql("DROP TABLE papers")
    assert "Only SELECT/WITH/EXPLAIN allowed" in result["error"]


def test_execute_kg_sql_truncates_large_results():
    result = tool_execute_kg_sql(
        "WITH RECURSIVE nums(n) AS ("
        "SELECT 1 UNION ALL SELECT n + 1 FROM nums WHERE n < 120"
        ") SELECT n FROM nums"
    )
    assert result["row_count"] == 100
    assert result["truncated"] is True
    assert "Results capped" in result["hint"]


def test_execute_kg_sql_rejects_document_sections_without_limit():
    result = tool_execute_kg_sql("SELECT id, content FROM document_sections")
    assert "document_sections" in result["error"]
    assert "LIMIT" in result["error"]


def test_execute_kg_sql_allows_document_sections_with_limit():
    result = tool_execute_kg_sql(
        "SELECT id, content FROM document_sections LIMIT 5"
    )
    assert "error" not in result


def test_execute_kg_sql_rejects_document_sections_with_only_nested_limit():
    result = tool_execute_kg_sql(
        "SELECT id, content FROM document_sections "
        "WHERE paper_id IN (SELECT id FROM papers LIMIT 1)"
    )

    assert "document_sections" in result["error"]
    assert "LIMIT" in result["error"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM document_sections -- LIMIT 5",
        "SELECT 'LIMIT 5' AS note FROM document_sections",
    ],
)
def test_execute_kg_sql_rejects_document_sections_limit_in_comments_or_strings(sql):
    result = tool_execute_kg_sql(sql)

    assert "document_sections" in result["error"]
    assert "LIMIT" in result["error"]


def test_execute_kg_sql_rejects_document_sections_limit_as_quoted_identifier():
    result = tool_execute_kg_sql(
        'SELECT id AS "limit" FROM document_sections'
    )

    assert "document_sections" in result["error"]
    assert "LIMIT" in result["error"]


@pytest.mark.parametrize(
    "sql",
    [
        "WITH candidate AS (SELECT 1) DELETE FROM papers WHERE pmid = 'protected'",
        (
            "WITH removed AS ("
            "DELETE FROM papers WHERE pmid = 'protected' RETURNING id"
            ") SELECT * FROM removed"
        ),
    ],
)
def test_execute_kg_sql_rejects_write_like_ctes_without_changing_db(sql):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO papers (pmid, title) VALUES (?, ?)",
            ("protected", "Protected paper"),
        )

    result = tool_execute_kg_sql(sql)

    assert "read-only" in result["error"].lower()
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE pmid = ?", ("protected",)
        ).fetchone()[0]
    assert count == 1


def test_execute_kg_sql_schema_error_includes_column_hint():
    result = tool_execute_kg_sql(
        "SELECT p.paper_id FROM papers p LIMIT 1"
    )
    assert "no such column" in result["error"].lower()
    assert "hint" in result
    assert "papers(id, pmid" in result["hint"]
    assert "There is no papers.paper_id" in result["hint"]


def test_execute_kg_sql_focus_expansion_uses_disease_concept():
    result = tool_execute_kg_sql(
        "SELECT 1 AS value",
        focus="nasopharyngeal carcinoma",
    )
    exp = result["focus_expansion"]
    assert exp["matched_concept"] is True
    assert exp["mode"] == "disease_concept"
    assert exp["canonical"]
    assert any("nasopharyngeal" in p.lower() for p in exp["phrases"])
    assert "OR" in exp["suggested_sql_filter"]


def test_execute_kg_sql_focus_expansion_falls_back_to_token_synonyms():
    result = tool_execute_kg_sql(
        "SELECT 1 AS value",
        focus="hepatic tumor imaging",
    )
    exp = result["focus_expansion"]
    assert exp["matched_concept"] is False
    assert exp["mode"] == "token_synonyms"
    joined = " ".join(exp["phrases"]).lower()
    assert "liver" in joined or "hepatic" in joined
    assert "cancer" in joined or "tumor" in joined or "carcinoma" in joined


def test_execute_kg_sql_schema_error_keeps_focus_expansion():
    result = tool_execute_kg_sql(
        "SELECT p.paper_id FROM papers p LIMIT 1",
        focus="肠息肉",
    )
    assert "no such column" in result["error"].lower()
    assert result["focus_expansion"]["matched_concept"] is True
    assert any("polyp" in p.lower() for p in result["focus_expansion"]["phrases"])


def test_execute_kg_sql_warns_on_mixed_and_or_without_parentheses():
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO papers (pmid, title) VALUES (?, ?)",
            ("p1", "colorectal cancer study"),
        )
        conn.execute(
            "INSERT INTO entities (id, name, type) VALUES (1, 'LLM', 'Method')"
        )
        conn.execute(
            "INSERT INTO paper_entity_bindings "
            "(source_pmid, method_entity_id, disease_entity_id) VALUES (?, 1, NULL)",
            ("p1",),
        )

    buggy = (
        "SELECT p.pmid FROM papers p "
        "JOIN paper_entity_bindings peb ON p.pmid = peb.source_pmid "
        "JOIN entities e ON e.id = peb.method_entity_id "
        "WHERE LOWER(p.title) LIKE '%colorectal%' "
        "AND LOWER(e.name) LIKE '%llm%' "
        "OR LOWER(e.name) LIKE '%large language%' "
        "LIMIT 20"
    )
    result = tool_execute_kg_sql(buggy)
    assert "error" not in result
    hint = (result.get("hint") or "").lower()
    assert "parenthes" in hint
    assert "and" in hint and "or" in hint


def test_execute_kg_sql_no_and_or_warning_when_parentheses_present():
    result = tool_execute_kg_sql(
        "SELECT 1 AS value FROM papers "
        "WHERE (title LIKE '%a%' OR title LIKE '%b%') AND year > 0 LIMIT 1"
    )
    hint = (result.get("hint") or "").lower()
    assert "parenthes" not in hint
