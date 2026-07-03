"""Shared OpenAI-compatible LLM client with global rate limiting."""
from __future__ import annotations

import json
import random
import sys
import threading
import time
from pathlib import Path

from openai import (
    APIConnectionError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

import config

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))
from llm_utils import llm_extra_body, truncate_for_llm  # noqa: E402

_client = OpenAI(
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_API_BASE,
    timeout=config.LLM_REQUEST_TIMEOUT,
    max_retries=0,
)

_rate_lock = threading.Lock()
_last_request_at = 0.0
_concurrency = threading.Semaphore(max(1, config.LLM_MAX_CONCURRENT))


def parse_llm_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            ln for ln in lines if not ln.strip().startswith("```")
        ).strip()
    parsed = json.loads(content)
    if isinstance(parsed, list):
        return {"triples": parsed}
    return parsed


def _rate_limit_wait() -> None:
    global _last_request_at
    with _rate_lock:
        now = time.monotonic()
        wait = config.LLM_MIN_INTERVAL - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _is_retriable(exc: BaseException) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "429",
            "rate limit",
            "too many",
            "connection",
            "timeout",
            "timed out",
            "503",
            "502",
            "500",
            "throttl",
        )
    )


def _retry_wait(exc: BaseException, attempt: int) -> float:
    base = config.LLM_RETRY_DELAY * (2**attempt)
    if isinstance(exc, RateLimitError) or "429" in str(exc):
        base = max(base, config.LLM_RATE_LIMIT_COOLDOWN)
    return base + random.uniform(0, 1.5)


def llm_call_structured(system: str, user: str) -> dict:
    last_exc: BaseException | None = None
    for attempt in range(config.LLM_RETRY_ATTEMPTS):
        try:
            with _concurrency:
                _rate_limit_wait()
                response = _client.chat.completions.create(
                    model=config.LLM_MODEL_EXTRACT,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=config.LLM_MAX_TOKENS,
                    temperature=config.LLM_TEMPERATURE,
                    response_format={"type": "json_object"},
                    extra_body=llm_extra_body(config.OPENAI_API_BASE),
                )
            content = response.choices[0].message.content or "{}"
            return parse_llm_json(content)
        except Exception as e:
            last_exc = e
            if _is_retriable(e) and attempt < config.LLM_RETRY_ATTEMPTS - 1:
                wait = _retry_wait(e, attempt)
                print(
                    f"  [LLM] Attempt {attempt + 1} error: {e}. "
                    f"Retrying in {wait:.1f}s..."
                )
                time.sleep(wait)
            else:
                print(f"  [LLM] All retries failed: {e}")
                break
    return {}


def truncate_input(text: str) -> str:
    return truncate_for_llm(text, config.EXTRACT_MAX_SECTION_CHARS)
