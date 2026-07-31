"""Regression: focus-bound wrappers must not drop required tool args like sql."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.agent_utils import (  # noqa: E402
    _safe_invoke_tool,
    bind_tools_with_focus,
)
from analysis.gap_tools import tool_execute_kg_sql  # noqa: E402


def test_bound_execute_kg_sql_keeps_sql_argument():
    tools = bind_tools_with_focus(
        {"execute_kg_sql": tool_execute_kg_sql},
        focus="nasopharyngeal carcinoma",
    )

    result = _safe_invoke_tool(
        tools["execute_kg_sql"],
        {"sql": "SELECT 1 AS value"},
    )

    assert "error" not in result
    assert result["data"] == [{"value": 1}]
