"""Shared agent utilities for tool-calling LLM loops."""
from __future__ import annotations

import inspect
import json
from typing import Any, Generator

from openai import APIError, OpenAI

import config
from llm_utils import llm_extra_body, truncate_for_llm

_client = OpenAI(
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_API_BASE,
)


def _parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _sanitize_tool_arguments(raw: str | None) -> str:
    """Ensure tool-call arguments replayed to the API are valid JSON objects."""
    return json.dumps(_parse_tool_arguments(raw), ensure_ascii=False)


def _sanitize_assistant_message(msg_dict: dict[str, Any]) -> dict[str, Any]:
    tool_calls = msg_dict.get("tool_calls")
    if not tool_calls:
        return msg_dict
    for tc in tool_calls:
        fn = tc.get("function")
        if isinstance(fn, dict):
            fn["arguments"] = _sanitize_tool_arguments(fn.get("arguments"))
    return msg_dict


def _safe_invoke_tool(fn: Any, fn_args: dict[str, Any]) -> dict[str, Any]:
    """Call a tool with only supported parameters; never raise to caller."""
    try:
        sig = inspect.signature(fn)
        filtered = {
            k: v for k, v in fn_args.items()
            if k in sig.parameters
        }
        return fn(**filtered)
    except TypeError as exc:
        return {"error": str(exc), "received_args": fn_args}
    except Exception as exc:
        return {"error": str(exc)}


def run_tool_agent(
    messages: list[dict],
    tools: dict[str, Any],
    tool_schemas: list[dict],
    role: str,
    max_iters: int = 15,
    temperature: float = 0.4,
    max_tokens: int | None = None,
) -> Generator[dict, None, None]:
    """
    Run one agent through its tool-calling loop.
    Yields typed events; final assistant message is appended to messages in-place.
    """
    if max_tokens is None:
        max_tokens = config.LLM_MAX_TOKENS

    for _ in range(max_iters):
        try:
            response = _client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=llm_extra_body(config.OPENAI_API_BASE),
            )
        except APIError as exc:
            yield {"type": "error", "role": role, "content": str(exc)}
            return
        except Exception as exc:
            yield {"type": "error", "role": role, "content": str(exc)}
            return

        msg = response.choices[0].message
        msg_dict = _sanitize_assistant_message(msg.model_dump(exclude_none=True))
        messages.append(msg_dict)

        if msg.content and msg.tool_calls:
            yield {"type": "thinking", "role": role, "content": msg.content}

        finish = response.choices[0].finish_reason
        if not msg.tool_calls or finish == "stop":
            return

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = _parse_tool_arguments(tc.function.arguments)

            yield {
                "type": "tool_call",
                "role": role,
                "name": fn_name,
                "args": fn_args,
                "call_id": tc.id,
            }

            if fn_name in tools:
                result = _safe_invoke_tool(tools[fn_name], fn_args)
                if "error" in result:
                    result_str = json.dumps(result, ensure_ascii=False, indent=2)
                    yield {
                        "type": "tool_error",
                        "role": role,
                        "name": fn_name,
                        "error": result["error"],
                        "call_id": tc.id,
                    }
                else:
                    result_str = json.dumps(result, ensure_ascii=False, indent=2)
                    if len(result_str) > config.LLM_MAX_TOOL_RESULT_CHARS:
                        result_str = (
                            result_str[: config.LLM_MAX_TOOL_RESULT_CHARS]
                            + "\n... [truncated]"
                        )
                    yield {
                        "type": "tool_result",
                        "role": role,
                        "name": fn_name,
                        "result": result,
                        "call_id": tc.id,
                    }
            else:
                result_str = json.dumps({"error": f"Unknown tool: {fn_name}"})
                yield {
                    "type": "tool_error",
                    "role": role,
                    "name": fn_name,
                    "error": f"Unknown tool: {fn_name}",
                    "call_id": tc.id,
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })


def last_assistant_content(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            return m["content"]
    return ""


def parse_json_block(text: str, fallback: dict | None = None) -> dict:
    import re

    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except Exception:
        return fallback or {}
