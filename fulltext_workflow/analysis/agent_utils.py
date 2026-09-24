"""Shared agent utilities for tool-calling LLM loops."""
from __future__ import annotations

import inspect
import json
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Generator

from openai import OpenAI

import config
from llm_utils import llm_extra_body, truncate_for_llm
from analysis.evidence_contract import compact_json

_client = OpenAI(
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_API_BASE,
    timeout=config.LLM_REQUEST_TIMEOUT,
    max_retries=0,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _field(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _token_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _retry_reason(exc: Exception) -> str | None:
    code = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    if code == 429:
        return "rate_limit"
    if isinstance(code, int) and code >= 500:
        return "server_error"
    if "timeout" in name:
        return "timeout"
    if "connection" in name:
        return "connection"
    return None


def _chat_with_metrics(
    *, role: str, iteration: int, messages: list[dict], request_kwargs: dict[str, Any]
) -> Generator[dict, None, tuple[Any | None, str | None]]:
    """One logical request with observable, bounded application retries."""
    request_id = str(uuid.uuid4())
    attempts = min(3, max(1, int(config.LLM_RETRY_ATTEMPTS)))
    for attempt_no in range(1, attempts + 1):
        operation_id = str(uuid.uuid4())
        yield {
            "type": "cost_start", "event_kind": "llm", "operation_id": operation_id,
            "request_id": request_id, "attempt_no": attempt_no, "role": role,
            "iteration": iteration, "model": config.LLM_MODEL_AGENT,
            "started_at_utc": _utc_now(),
        }
        started = time.perf_counter()
        try:
            response = _client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            reason = _retry_reason(exc)
            will_retry = reason is not None and attempt_no < attempts
            delay_ms = max(0, min(10000, int(config.LLM_RETRY_DELAY * 1000 * (2 ** (attempt_no - 1))))) if will_retry else 0
            yield {
                "type": "cost_finish", "event_kind": "llm", "operation_id": operation_id,
                "role": role, "status": "failed",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_code": type(exc).__name__, "retry_reason_code": reason,
                "retry_source": "agent" if will_retry else None,
                "retry_after_ms": delay_ms or None,
            }
            if not will_retry:
                return None, str(exc)
            yield {"type": "llm_retry", "role": role, "iteration": iteration,
                   "attempt_no": attempt_no + 1, "reason": reason}
            if delay_ms:
                time.sleep(delay_ms / 1000)
            continue
        usage = _field(response, "usage")
        prompt = _token_count(_field(usage, "prompt_tokens"))
        completion = _token_count(_field(usage, "completion_tokens"))
        total = _token_count(_field(usage, "total_tokens"))
        choices = _field(response, "choices") or []
        yield {
            "type": "cost_finish", "event_kind": "llm", "operation_id": operation_id,
            "role": role, "status": "success",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "provider_request_id": _field(response, "id"),
            "prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": total,
            "usage_source": "provider" if usage is not None else None,
            "finish_reason": _field(choices[0], "finish_reason") if choices else None,
        }
        return response, None
    return None, "LLM retry attempts exhausted"


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


def select_tool_bundle(
    names: list[str],
    tools: dict[str, Any],
    schemas: list[dict],
) -> tuple[dict[str, Any], list[dict]]:
    schema_by_name = {
        schema["function"]["name"]: schema
        for schema in schemas
        if isinstance(schema, dict) and "function" in schema
    }
    missing = [name for name in names if name not in tools or name not in schema_by_name]
    if missing:
        raise KeyError(f"Unknown tool(s) for bundle: {missing}")
    selected_tools = {name: tools[name] for name in names}
    selected_schemas = [schema_by_name[name] for name in names]
    return selected_tools, selected_schemas


def bind_tools_with_focus(
    tools: dict[str, Any],
    focus: str | None,
) -> dict[str, Any]:
    """Inject default focus into tool calls when the model omits it."""
    if not focus or not str(focus).strip():
        return tools

    default_focus = str(focus).strip()
    bound: dict[str, Any] = {}

    for name, fn in tools.items():
        try:
            has_focus = "focus" in inspect.signature(fn).parameters
        except (TypeError, ValueError):
            has_focus = False
        if not has_focus:
            bound[name] = fn
            continue

        def _make_wrapper(f: Any, foc: str):
            def _wrapped(**kwargs: Any) -> Any:
                if not kwargs.get("focus"):
                    kwargs["focus"] = foc
                return f(**kwargs)

            # Preserve the original signature so _safe_invoke_tool does not
            # drop required kwargs (e.g. execute_kg_sql's sql) when filtering.
            try:
                _wrapped.__signature__ = inspect.signature(f)
            except (TypeError, ValueError):
                pass
            return _wrapped

        bound[name] = _make_wrapper(fn, default_focus)

    return bound


def memoize_readonly_tools(
    tools: dict[str, Any], cache: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Reuse identical successful read-only tool results within one debate run."""
    wrapped: dict[str, Any] = {}
    for name, fn in tools.items():
        if name == "execute_kg_sql":
            wrapped[name] = fn
            continue

        def _make_wrapper(tool_name: str, function: Any):
            @wraps(function)
            def _cached(**kwargs: Any) -> Any:
                key = (tool_name, json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str))
                if key in cache:
                    hit = deepcopy(cache[key])
                    hit["_telemetry"] = {"cache_hit": True, "cache_source": "debate_session"}
                    return hit
                result = function(**kwargs)
                if isinstance(result, dict) and "error" not in result:
                    cache[key] = deepcopy(result)
                    result = deepcopy(result)
                    metadata = result.get("_telemetry")
                    if not isinstance(metadata, dict):
                        result["_telemetry"] = {
                            "cache_hit": False, "cache_source": "debate_session",
                        }
                return result
            return _cached

        wrapped[name] = _make_wrapper(name, fn)
    return wrapped


def _safe_invoke_tool(fn: Any, fn_args: dict[str, Any]) -> dict[str, Any]:
    """Call a tool with only supported parameters; never raise to caller."""
    try:
        sig = inspect.signature(fn)
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        filtered = fn_args if accepts_kwargs else {
            k: v for k, v in fn_args.items()
            if k in sig.parameters
        }
        result = fn(**filtered)
        return result if isinstance(result, dict) else {"data": result}
    except TypeError as exc:
        return {"error": str(exc), "received_args": fn_args}
    except Exception as exc:
        return {"error": str(exc)}


# Models sometimes emit a fake tool named after the desired output format
# (e.g. "json") instead of writing that format in the assistant message.
_PHANTOM_FORMAT_TOOLS = frozenset(
    {
        "json",
        "markdown",
        "md",
        "text",
        "output",
        "response",
        "final_answer",
        "answer",
        "report",
    }
)

_PHANTOM_TOOL_HINT = (
    "There is no tool named '{name}'. JSON/Markdown/report outputs belong in the "
    "assistant message content (optionally inside a fenced code block), not as a "
    "tool call. Do not invent tools. Call only tools from the provided tool list, "
    "or finish with a normal message and no tool_calls. "
    "Next turn has tools disabled — write your review/report now as message content."
)

_PHANTOM_FINISH_HINT = (
    "Tools are disabled. Do not call any tool (especially not json/markdown/text). "
    "Write your required output now as assistant message content only. "
    "For JSON, use a fenced ```json block. For a Markdown report/proposal, write raw "
    "Markdown starting with # or ## — do not wrap the entire document in a ```markdown fence."
)


def _phantom_payload_as_content(fn_name: str, fn_args: dict[str, Any]) -> str | None:
    """If a phantom tool call carries the intended payload, turn it into message text."""
    if not fn_args:
        return None
    if fn_name in {"markdown", "md", "text", "report", "final_answer", "answer", "output", "response"}:
        for key in ("content", "text", "markdown", "report", "answer", "output"):
            val = fn_args.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        # Single string-like dump
        if len(fn_args) == 1:
            only = next(iter(fn_args.values()))
            if isinstance(only, str) and only.strip():
                return only.strip()
        return None
    # json / generic structured payload
    if "content" in fn_args and isinstance(fn_args["content"], str) and fn_args["content"].strip():
        return fn_args["content"].strip()
    body = json.dumps(fn_args, ensure_ascii=False, indent=2)
    return f"```json\n{body}\n```"


_SQL_BUDGET_BLOCKED = (
    "SQL call budget exhausted ({used}/{max_calls} successful calls). Do not call "
    "execute_kg_sql again. Stop title/keyword scanning; use curated tools already "
    "returned, or finish with your review/report in the assistant message (no tool_calls)."
)

_SQL_EMPTY_HINT = (
    "Empty SQL result. Do not keep scanning with new title keywords or loose OR clauses; "
    "if the prior query mixed AND/OR, fix parentheses first "
    "((disease…) AND (method…)), then prefer curated tools "
    "(coverage / limitation_temporal_profile / author_stated_gaps / "
    "improvement_suggestions_by_topic) or write your verification now."
)

_SQL_FAILED_NO_BUDGET_HINT = (
    "SQL failed (schema/runtime). This failed call did NOT consume the successful-SQL "
    "budget. Qualify ambiguous columns (e.g. pis.confidence) and retry once, or use a "
    "curated tool instead."
)

_SQL_FINISH_NOW_HINT = (
    "SQL budget already exhausted. Do not call execute_kg_sql again. "
    "Next turn has tools disabled — output your final review/report now."
)

_DUPLICATE_TOOL_HINT = (
    "Tool '{name}' was already called with the same arguments in this phase. "
    "Use a different, specific query only if it checks a distinct claim; "
    "otherwise use the prior result or finish your review."
)


def _schemas_without_sql(schemas: list[dict]) -> list[dict]:
    out = []
    for schema in schemas:
        name = (schema.get("function") or {}).get("name")
        if name == "execute_kg_sql":
            continue
        out.append(schema)
    return out


def _wrap_execute_kg_sql_budget(
    fn: Any,
    max_sql_calls: int,
    counter: dict[str, int],
) -> Any:
    """Hard-cap successful execute_kg_sql calls; schema failures do not consume budget."""

    # Allow a few failed attempts so one bad column name does not burn the quota,
    # but still bound infinite fail/retry loops.
    max_attempts = max(max_sql_calls + 2, max_sql_calls * 2)

    def _capped(**kwargs: Any) -> Any:
        if counter["n"] >= max_sql_calls:
            return {
                "error": _SQL_BUDGET_BLOCKED.format(
                    used=counter["n"], max_calls=max_sql_calls
                ),
                "sql_budget_exhausted": True,
            }
        if counter.get("attempts", 0) >= max_attempts:
            return {
                "error": _SQL_BUDGET_BLOCKED.format(
                    used=counter["n"], max_calls=max_sql_calls
                )
                + f" Also hit max SQL attempts ({max_attempts}).",
                "sql_budget_exhausted": True,
            }
        counter["attempts"] = int(counter.get("attempts", 0)) + 1
        result = fn(**kwargs)
        if isinstance(result, dict) and result.get("error"):
            # Failed query: do not increment successful budget.
            if not result.get("hint"):
                result = {**result, "hint": _SQL_FAILED_NO_BUDGET_HINT}
            return result
        counter["n"] += 1
        return result

    try:
        _capped.__signature__ = inspect.signature(fn)
    except (TypeError, ValueError):
        pass
    return _capped


def run_tool_agent(
    messages: list[dict],
    tools: dict[str, Any],
    tool_schemas: list[dict],
    role: str,
    max_iters: int = 15,
    temperature: float = 0.4,
    max_tokens: int | None = None,
    max_sql_calls: int | None = None,
    disallow_duplicate_tools: bool = False,
    max_tool_calls: int | None = None,
    first_tool: str | None = None,
    required_tools: tuple[str, ...] = (),
) -> Generator[dict, None, None]:
    """
    Run one agent through its tool-calling loop.
    Yields typed events; final assistant message is appended to messages in-place.

    max_sql_calls: hard cap on *successful* execute_kg_sql invocations this phase
    (None = unlimited). Schema/runtime SQL errors do not consume the cap.
    After the budget is reached, execute_kg_sql is removed from subsequent tool schemas;
    a pure post-budget SQL-only turn disables tools on the next iteration to force text.

    disallow_duplicate_tools: when True, repeated calls with the same tool name and
    arguments in this phase are blocked; distinct scoped queries remain available.
    """
    if max_tokens is None:
        max_tokens = config.LLM_MAX_TOKENS

    tools = dict(tools)
    sql_counter = {"n": 0, "attempts": 0}
    active_schemas = list(tool_schemas)
    force_text_next = False
    called_tool_keys: set[tuple[str, str]] = set()
    successful_tools: set[str] = set()
    attempted_calls = 0
    def phase_status():
        missing = sorted(set(required_tools) - successful_tools)
        return {"type":"phase_status", "role":role, "successful_tools":sorted(successful_tools),
                "missing_required_tools":missing, "tool_attempts":attempted_calls,
                "validation_status":"needs_verification" if missing else "complete"}
    if max_sql_calls is not None:
        print(
            f"[tool-agent] role={role} max_sql_calls={max_sql_calls}",
            flush=True,
        )
        if max_sql_calls <= 0:
            active_schemas = _schemas_without_sql(active_schemas)
            tools.pop("execute_kg_sql", None)
        elif "execute_kg_sql" in tools:
            tools["execute_kg_sql"] = _wrap_execute_kg_sql_budget(
                tools["execute_kg_sql"], max_sql_calls, sql_counter
            )

    for iteration in range(max_iters):
        if force_text_next:
            active_schemas = []
            force_text_next = False

        yield {
            "type": "llm_request_start",
            "role": role,
            "iteration": iteration + 1,
            "max_iters": max_iters,
        }
        response, request_error = yield from _chat_with_metrics(
            role=role, iteration=iteration + 1, messages=messages,
            request_kwargs={
                "model": config.LLM_MODEL_AGENT,
                "messages": messages,
                "tools": active_schemas if active_schemas else None,
                "tool_choice": ({"type": "function", "function": {"name": first_tool}}
                                if first_tool and first_tool not in successful_tools
                                and any(s["function"]["name"] == first_tool for s in active_schemas)
                                else ("auto" if active_schemas else "none")),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "extra_body": llm_extra_body(config.OPENAI_API_BASE),
            },
        )
        if response is None:
            yield {"type": "error", "role": role, "content": request_error or "LLM request failed"}
            return

        msg = response.choices[0].message
        msg_dict = _sanitize_assistant_message(msg.model_dump(exclude_none=True))
        messages.append(msg_dict)

        if msg.content and msg.tool_calls:
            yield {"type": "thinking", "role": role, "content": msg.content}

        finish = response.choices[0].finish_reason
        if not msg.tool_calls:
            yield phase_status()
            return

        stop_after_tools = False
        turn_tool_names: list[str] = []
        turn_budget_blocks = 0
        turn_unrecovered_phantom = False
        text_only_this_turn = not active_schemas
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = _parse_tool_arguments(tc.function.arguments)
            tool_key = (fn_name, json.dumps(fn_args, sort_keys=True, ensure_ascii=False, default=str))
            try:
                parsed_args = json.loads(tc.function.arguments or "{}")
                argument_error = not isinstance(parsed_args, dict)
            except (json.JSONDecodeError, TypeError):
                argument_error = True
            turn_tool_names.append(fn_name)

            yield {
                "type": "tool_call",
                "role": role,
                "name": fn_name,
                "args": fn_args,
                "call_id": tc.id,
            }

            yield {
                "type": "tool_running",
                "role": role,
                "name": fn_name,
                "call_id": tc.id,
            }

            recovered_content: str | None = None
            budget_blocked = False
            contract_error = None
            if argument_error:
                contract_error = "invalid_tool_arguments: expected a valid JSON object; no tool executed"
            elif (
                text_only_this_turn and fn_name in tools
                and not (fn_name == "execute_kg_sql" and max_sql_calls is not None
                         and sql_counter["n"] >= max_sql_calls)
            ):
                contract_error = "tools_disabled: finish with message content; no tool executed"
            elif first_tool and first_tool not in successful_tools and fn_name != first_tool:
                contract_error = f"prerequisite_missing: successfully call {first_tool} before other tools"
            elif max_tool_calls is not None and attempted_calls >= max_tool_calls:
                contract_error = "tool_budget_exhausted: finish with available evidence"
            if contract_error:
                result = {"error":contract_error}
                result_str = json.dumps(result)
                yield {"type":"tool_error", "role":role, "name":fn_name, "error":contract_error, "call_id":tc.id}
            elif (
                fn_name == "execute_kg_sql"
                and max_sql_calls is not None
                and (
                    sql_counter["n"] >= max_sql_calls
                    or "execute_kg_sql" not in tools
                )
            ):
                err = _SQL_BUDGET_BLOCKED.format(
                    used=sql_counter["n"], max_calls=max_sql_calls
                )
                result = {
                    "error": err,
                    "sql_budget_exhausted": True,
                    "hint": _SQL_FINISH_NOW_HINT,
                }
                result_str = json.dumps(result, ensure_ascii=False)
                budget_blocked = True
                turn_budget_blocks += 1
                yield {
                    "type": "tool_error",
                    "role": role,
                    "name": fn_name,
                    "error": err,
                    "call_id": tc.id,
                }
            elif (
                disallow_duplicate_tools
                and tool_key in called_tool_keys
                and fn_name in tools
            ):
                err = _DUPLICATE_TOOL_HINT.format(name=fn_name)
                result = {
                    "error": err,
                    "duplicate_tool_blocked": True,
                    "hint": err,
                }
                result_str = json.dumps(result, ensure_ascii=False)
                yield {
                    "type": "tool_error",
                    "role": role,
                    "name": fn_name,
                    "error": err,
                    "call_id": tc.id,
                }
            elif fn_name in tools:
                attempted_calls += 1
                yield {"type":"tool_execution", "role":role, "name":fn_name, "args":fn_args, "call_id":tc.id}
                operation_id = str(uuid.uuid4())
                yield {
                    "type": "cost_start", "event_kind": "tool", "operation_id": operation_id,
                    "role": role, "tool_name": fn_name, "call_id": tc.id,
                    "started_at_utc": _utc_now(),
                }
                tool_started = time.perf_counter()
                result = _safe_invoke_tool(tools[fn_name], fn_args)
                tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 2)
                cache_info = result.pop("_telemetry", {}) if isinstance(result.get("_telemetry"), dict) else {}
                called_tool_keys.add(tool_key)
                if (
                    fn_name == "execute_kg_sql"
                    and isinstance(result, dict)
                    and result.get("sql_budget_exhausted")
                ):
                    active_schemas = _schemas_without_sql(active_schemas)
                    budget_blocked = True
                    turn_budget_blocks += 1
                    if not result.get("hint"):
                        result = {**result, "hint": _SQL_FINISH_NOW_HINT}
                elif (
                    fn_name == "execute_kg_sql"
                    and isinstance(result, dict)
                    and "error" not in result
                    and int(result.get("row_count") or 0) == 0
                ):
                    existing = (result.get("hint") or "").strip()
                    if "Empty SQL result" not in existing:
                        result = {
                            **result,
                            "hint": f"{existing} {_SQL_EMPTY_HINT}".strip(),
                        }
                if (
                    max_sql_calls is not None
                    and max_sql_calls > 0
                    and sql_counter["n"] >= max_sql_calls
                ):
                    active_schemas = _schemas_without_sql(active_schemas)
                if "error" in result:
                    result_str = json.dumps(result, ensure_ascii=False, indent=2)
                    output_event = {
                        "type": "tool_error",
                        "role": role,
                        "name": fn_name,
                        "error": result["error"],
                        "call_id": tc.id,
                    }
                else:
                    successful_tools.add(fn_name)
                    result_str = compact_json(result, config.LLM_MAX_TOOL_RESULT_CHARS)
                    output_event = {
                        "type": "tool_result",
                        "role": role,
                        "name": fn_name,
                        "result": result,
                        "call_id": tc.id,
                    }
                sent_payload = json.loads(result_str)
                cache_hit = cache_info.get("cache_hit")
                yield {
                    "type": "cost_finish", "event_kind": "tool", "operation_id": operation_id,
                    "role": role, "status": "failed" if "error" in result else "success",
                    "duration_ms": tool_duration_ms,
                    "raw_result_chars": len(json.dumps(result, ensure_ascii=False, default=str)),
                    "sent_result_chars": len(result_str),
                    "result_truncated": int(bool(sent_payload.get("evidence_truncated")))
                    if isinstance(sent_payload, dict) else 0,
                    "cache_hit": int(cache_hit) if isinstance(cache_hit, bool) else None,
                    "cache_source": cache_info.get("cache_source"),
                    "error_code": "tool_error" if "error" in result else None,
                }
                yield output_event
            else:
                phantom = fn_name.strip().lower() in _PHANTOM_FORMAT_TOOLS
                if phantom:
                    recovered_content = _phantom_payload_as_content(
                        fn_name.strip().lower(), fn_args
                    )
                    err = _PHANTOM_TOOL_HINT.format(name=fn_name)
                    if recovered_content:
                        err += " Recovered your tool arguments as message content."
                    else:
                        turn_unrecovered_phantom = True
                    result = {
                        "error": err,
                        "recovered": bool(recovered_content),
                        "hint": _PHANTOM_FINISH_HINT,
                    }
                else:
                    err = f"Unknown tool: {fn_name}"
                    result = {"error": err}
                result_str = json.dumps(result, ensure_ascii=False)
                yield {
                    "type": "tool_error",
                    "role": role,
                    "name": fn_name,
                    "error": err,
                    "call_id": tc.id,
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

            if recovered_content:
                messages.append({"role": "assistant", "content": recovered_content})
                stop_after_tools = True

        # Pure post-budget SQL thrash → disable tools next turn to force text output.
        if (
            max_sql_calls is not None
            and sql_counter["n"] >= max_sql_calls
            and turn_tool_names
            and all(name == "execute_kg_sql" for name in turn_tool_names)
            and turn_budget_blocks == len(turn_tool_names)
        ):
            force_text_next = True
            active_schemas = _schemas_without_sql(active_schemas)

        # Empty phantom format tools (e.g. json:{}) → disable tools and nudge finish.
        if turn_unrecovered_phantom and not stop_after_tools:
            force_text_next = True
            active_schemas = []
            messages.append({"role": "user", "content": _PHANTOM_FINISH_HINT})
            # Already in text-only mode and still invented a format tool → stop looping.
            if text_only_this_turn:
                return

        if stop_after_tools:
            yield phase_status()
            return

        if max_tool_calls is not None and attempted_calls >= max_tool_calls:
            active_schemas = []
            messages.append({"role":"user", "content":"Tool budget exhausted. Produce the required final output now; explicitly disclose missing verification."})

    # Exhaustion is not success. Reserve a single tool-free completion for usable output.
    messages.append({"role":"user", "content":"Iteration limit reached. No more tools. Produce the required final JSON review or full Markdown report now using available evidence. Missing verification is not acceptance."})
    yield {"type":"llm_request_start", "role":role, "iteration":max_iters+1, "max_iters":max_iters+1, "finalization":True}
    response, request_error = yield from _chat_with_metrics(
        role=role, iteration=max_iters + 1, messages=messages,
        request_kwargs={"model": config.LLM_MODEL_AGENT, "messages": messages,
                        "tool_choice": "none", "temperature": temperature,
                        "max_tokens": max_tokens,
                        "extra_body": llm_extra_body(config.OPENAI_API_BASE)},
    )
    if response is not None:
        final = response.choices[0].message
        if final.content and not final.tool_calls:
            messages.append({"role":"assistant", "content":final.content})
        else:
            yield {"type":"error", "role":role, "content":"Finalization returned no tool-free output"}
    else:
        yield {"type":"error", "role":role, "content":request_error or "LLM request failed"}
    yield phase_status()


def best_assistant_content(
    messages: list[dict],
    *,
    min_chars: int = 300,
) -> str:
    """Prefer the last tool-free assistant reply; avoid pre-tool thinking snippets."""
    tool_free: list[str] = []
    any_content: list[str] = []
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        any_content.append(content)
        if not m.get("tool_calls"):
            tool_free.append(content)

    if tool_free:
        return tool_free[0]
    if any_content:
        best = max(any_content, key=len)
        if len(best) >= min_chars:
            return best
        return best
    return ""


def looks_like_proposal(text: str) -> bool:
    if len(text.strip()) < 400:
        return False
    markers = (
        "## 1.",
        "## 1 ",
        "## Background",
        "## Research",
        "REVISION_NOTE",
        "Fangxin Data Integration",
        "## 一",
        "## 二",
        "研究背景",
        "# 研究",
    )
    return any(m in text for m in markers)


def finalize_assistant_content(
    messages: list[dict],
    *,
    instruction: str,
    temperature: float = 0.35,
    max_tokens: int | None = None,
) -> str:
    """One-shot completion without tools after a tool loop ends early."""
    if max_tokens is None:
        max_tokens = max(config.LLM_MAX_TOKENS, 8192)
    messages.append({"role": "user", "content": instruction})
    response = _client.chat.completions.create(
        model=config.LLM_MODEL_AGENT,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=llm_extra_body(config.OPENAI_API_BASE),
    )
    content = (response.choices[0].message.content or "").strip()
    if content:
        messages.append({"role": "assistant", "content": content})
    return content


def last_assistant_content(messages: list[dict]) -> str:
    return best_assistant_content(messages)


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
