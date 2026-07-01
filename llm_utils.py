"""Shared helpers for OpenAI-compatible LLM providers (DeepSeek, DashScope, etc.)."""
from __future__ import annotations


def llm_extra_body(base_url: str) -> dict:
    """Provider-specific kwargs passed via OpenAI SDK extra_body."""
    url = (base_url or "").lower()
    if "deepseek.com" in url:
        return {"thinking": {"type": "disabled"}}
    if "dashscope" in url:
        return {"enable_thinking": False}
    return {}


def truncate_for_llm(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"
