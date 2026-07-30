import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.agent_utils import select_tool_bundle  # noqa: E402


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


def test_select_tool_bundle_keeps_order_and_filters():
    tools = {"a": lambda: 1, "b": lambda: 2, "c": lambda: 3}
    schemas = [_schema("a"), _schema("b"), _schema("c")]

    selected_tools, selected_schemas = select_tool_bundle(["c", "a"], tools, schemas)

    assert list(selected_tools) == ["c", "a"]
    assert [schema["function"]["name"] for schema in selected_schemas] == ["c", "a"]


def test_select_tool_bundle_raises_on_unknown_name():
    tools = {"a": lambda: 1}
    schemas = [_schema("a")]

    try:
        select_tool_bundle(["missing"], tools, schemas)
        assert False, "expected KeyError"
    except KeyError as exc:
        assert "missing" in str(exc)
