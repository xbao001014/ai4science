"""Validated OpenAI-compatible embedding client for Bailian Phase A."""
from __future__ import annotations

import math
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from openai import OpenAI

import config


@dataclass(frozen=True)
class EmbeddingItem:
    item_id: str
    input_sha256: str
    text: str


@dataclass(frozen=True)
class EmbeddingVector:
    item_id: str
    input_sha256: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: tuple[EmbeddingVector, ...]
    prompt_tokens: int | None = None


class EmbeddingClientError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_KEY_RE = re.compile(r"(?i)(?:bearer\s+)?sk-[a-z0-9_-]{8,}")
_AUTH_RE = re.compile(r"(?i)(authorization\s*[:=]\s*)[^,;\s]+")


def sanitize_embedding_error(
    value: BaseException | str,
    *,
    sensitive_texts: Sequence[str] = (),
    max_chars: int = 500,
) -> str:
    """Return a single-line error safe for logs and job rows."""
    text = str(value)
    for sensitive in sensitive_texts:
        if sensitive:
            text = text.replace(sensitive, "<redacted-input>")
    text = _KEY_RE.sub("<redacted-key>", text)
    text = _AUTH_RE.sub(r"\1<redacted-key>", text)
    text = " ".join(text.split())
    return text[:max_chars]


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _status_code(exc: BaseException) -> int | None:
    direct = getattr(exc, "status_code", None)
    if isinstance(direct, int):
        return direct
    response = getattr(exc, "response", None)
    nested = getattr(response, "status_code", None)
    return nested if isinstance(nested, int) else None


def _classify_error(exc: BaseException) -> tuple[str, bool]:
    status = _status_code(exc)
    if status in (401, 403):
        return "auth_error", False
    if status in (400, 404, 422):
        return "request_error", False
    if status in (408, 429) or (status is not None and 500 <= status <= 599):
        return "rate_limit" if status == 429 else "provider_error", True
    message = str(exc).lower()
    if "429" in message or "rate limit" in message or "too many" in message:
        return "rate_limit", True
    if any(word in message for word in ("timeout", "timed out", "connection")):
        return "transport_error", True
    if any(word in message for word in ("500", "502", "503", "504")):
        return "provider_error", True
    return "client_error", False


class EmbeddingClient:
    """Small synchronous client with strict response validation and retries."""

    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = config.EMBEDDING_API_BASE,
        model: str = config.EMBEDDING_MODEL,
        dimensions: int = config.EMBEDDING_DIMENSIONS,
        batch_size: int = config.EMBEDDING_BATCH_SIZE,
        max_concurrent: int = config.EMBEDDING_MAX_CONCURRENT,
        request_timeout: float = config.EMBEDDING_REQUEST_TIMEOUT,
        retry_attempts: int = config.EMBEDDING_RETRY_ATTEMPTS,
        retry_delay: float = config.EMBEDDING_RETRY_DELAY,
        min_interval: float = config.EMBEDDING_MIN_INTERVAL,
        rate_limit_cooldown: float = config.EMBEDDING_RATE_LIMIT_COOLDOWN,
        sdk_client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = lambda: random.uniform(0.0, 0.5),
    ) -> None:
        if not api_key:
            raise EmbeddingClientError("missing_key", "Embedding API key is not configured")
        if not 1 <= int(batch_size) <= 10:
            raise EmbeddingClientError(
                "invalid_config", "Embedding batch size must be between 1 and 10"
            )
        self.model = model
        self.dimensions = int(dimensions)
        self.batch_size = int(batch_size)
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_delay = max(0.0, float(retry_delay))
        self.min_interval = max(0.0, float(min_interval))
        self.rate_limit_cooldown = max(0.0, float(rate_limit_cooldown))
        self._sleep = sleep
        self._monotonic = monotonic
        self._jitter = jitter
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0
        self._concurrency = threading.Semaphore(max(1, int(max_concurrent)))
        self._client = sdk_client or OpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=request_timeout,
            max_retries=0,
        )

    def _wait_for_rate_limit(self) -> None:
        with self._rate_lock:
            now = self._monotonic()
            wait = self.min_interval - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
            self._last_request_at = self._monotonic()

    def _validate_response(
        self, response: Any, items: Sequence[EmbeddingItem]
    ) -> EmbeddingBatchResult:
        raw_data = _field(response, "data")
        if not isinstance(raw_data, (list, tuple)) or len(raw_data) != len(items):
            raise EmbeddingClientError(
                "invalid_response", "Embedding response item count mismatch"
            )

        by_index: dict[int, tuple[float, ...]] = {}
        for entry in raw_data:
            index = _field(entry, "index")
            raw_vector = _field(entry, "embedding")
            if not isinstance(index, int) or index < 0 or index >= len(items):
                raise EmbeddingClientError(
                    "invalid_response", "Embedding response contains invalid index"
                )
            if index in by_index:
                raise EmbeddingClientError(
                    "invalid_response", "Embedding response contains duplicate index"
                )
            if not isinstance(raw_vector, (list, tuple)):
                raise EmbeddingClientError(
                    "invalid_response", "Embedding response vector is missing"
                )
            try:
                values = tuple(float(value) for value in raw_vector)
            except (TypeError, ValueError) as exc:
                raise EmbeddingClientError(
                    "invalid_response", "Embedding response vector is not numeric"
                ) from exc
            if len(values) != self.dimensions:
                raise EmbeddingClientError(
                    "invalid_response", "Embedding response dimension mismatch"
                )
            if not all(math.isfinite(value) for value in values):
                raise EmbeddingClientError(
                    "invalid_response", "Embedding response contains non-finite values"
                )
            if not any(value != 0.0 for value in values):
                raise EmbeddingClientError(
                    "invalid_response", "Embedding response contains a zero vector"
                )
            by_index[index] = values

        if set(by_index) != set(range(len(items))):
            raise EmbeddingClientError(
                "invalid_response", "Embedding response indexes are incomplete"
            )

        usage = _field(response, "usage")
        prompt_tokens = _field(usage, "prompt_tokens") if usage is not None else None
        if not isinstance(prompt_tokens, int) or prompt_tokens < 0:
            prompt_tokens = None
        vectors = tuple(
            EmbeddingVector(
                item_id=item.item_id,
                input_sha256=item.input_sha256,
                values=by_index[index],
            )
            for index, item in enumerate(items)
        )
        return EmbeddingBatchResult(vectors=vectors, prompt_tokens=prompt_tokens)

    def embed(self, items: Sequence[EmbeddingItem]) -> EmbeddingBatchResult:
        if not items:
            return EmbeddingBatchResult(vectors=())
        if len(items) > self.batch_size or len(items) > 10:
            raise EmbeddingClientError(
                "batch_too_large",
                f"Embedding request has {len(items)} items; maximum is {min(self.batch_size, 10)}",
            )
        if any(not item.text.strip() for item in items):
            raise EmbeddingClientError("invalid_input", "Embedding input must not be empty")

        sensitive = tuple(item.text for item in items)
        last_error: BaseException | None = None
        for attempt in range(self.retry_attempts):
            try:
                with self._concurrency:
                    self._wait_for_rate_limit()
                    response = self._client.embeddings.create(
                        model=self.model,
                        input=[item.text for item in items],
                        dimensions=self.dimensions,
                        encoding_format="float",
                    )
                return self._validate_response(response, items)
            except EmbeddingClientError:
                raise
            except Exception as exc:  # provider SDK errors have multiple concrete types
                last_error = exc
                code, retriable = _classify_error(exc)
                if not retriable or attempt >= self.retry_attempts - 1:
                    raise EmbeddingClientError(
                        code,
                        sanitize_embedding_error(exc, sensitive_texts=sensitive),
                    ) from exc
                delay = self.retry_delay * (2**attempt)
                if code == "rate_limit":
                    delay = max(delay, self.rate_limit_cooldown)
                self._sleep(delay + self._jitter())
        raise EmbeddingClientError(
            "client_error", sanitize_embedding_error(last_error or "unknown embedding error")
        )
