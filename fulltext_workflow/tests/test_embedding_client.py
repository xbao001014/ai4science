from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.embedding_client import (  # noqa: E402
    EmbeddingClient,
    EmbeddingClientError,
    EmbeddingItem,
    sanitize_embedding_error,
)


def _items(count: int) -> list[EmbeddingItem]:
    return [
        EmbeddingItem(
            item_id=str(index),
            input_sha256=hashlib.sha256(str(index).encode()).hexdigest(),
            text=f"method {index}",
        )
        for index in range(count)
    ]


class FakeEmbeddings:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDK:
    def __init__(self, outcomes):
        self.embeddings = FakeEmbeddings(outcomes)


class StatusError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _response(indexes=(0, 1), *, dimensions=3):
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=index, embedding=[float(index + 1)] * dimensions)
            for index in indexes
        ],
        usage=SimpleNamespace(prompt_tokens=12),
    )


def test_response_is_reordered_by_index():
    sdk = FakeSDK([_response((1, 0))])
    client = EmbeddingClient(
        api_key="test-key",
        dimensions=3,
        sdk_client=sdk,
        min_interval=0,
    )
    result = client.embed(_items(2))
    assert result.prompt_tokens == 12
    assert result.vectors[0].values == (1.0, 1.0, 1.0)
    assert result.vectors[1].values == (2.0, 2.0, 2.0)


@pytest.mark.parametrize("indexes", [(0,), (0, 0), (0, 2)])
def test_missing_duplicate_or_invalid_index_fails(indexes):
    sdk = FakeSDK([_response(indexes)])
    client = EmbeddingClient(
        api_key="test-key", dimensions=3, sdk_client=sdk, min_interval=0
    )
    with pytest.raises(EmbeddingClientError, match="response") as exc:
        client.embed(_items(2))
    assert exc.value.code == "invalid_response"


@pytest.mark.parametrize(
    "vector",
    ([1.0, 2.0], [1.0, 2.0, float("nan")], [0.0, 0.0, 0.0]),
)
def test_bad_dimension_nonfinite_and_zero_vectors_fail(vector):
    response = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=vector)])
    client = EmbeddingClient(
        api_key="test-key",
        dimensions=3,
        sdk_client=FakeSDK([response]),
        min_interval=0,
    )
    with pytest.raises(EmbeddingClientError) as exc:
        client.embed(_items(1))
    assert exc.value.code == "invalid_response"


def test_429_retries_but_401_does_not():
    sleeps: list[float] = []
    sdk = FakeSDK([StatusError(429, "limited"), _response((0,))])
    client = EmbeddingClient(
        api_key="test-key",
        dimensions=3,
        sdk_client=sdk,
        min_interval=0,
        retry_attempts=2,
        retry_delay=0,
        rate_limit_cooldown=3,
        sleep=sleeps.append,
        jitter=lambda: 0,
    )
    assert len(client.embed(_items(1)).vectors) == 1
    assert len(sdk.embeddings.calls) == 2
    assert sleeps == [3]

    auth_sdk = FakeSDK([StatusError(401, "denied")])
    auth_client = EmbeddingClient(
        api_key="test-key",
        dimensions=3,
        sdk_client=auth_sdk,
        min_interval=0,
        retry_attempts=3,
    )
    with pytest.raises(EmbeddingClientError) as exc:
        auth_client.embed(_items(1))
    assert exc.value.code == "auth_error"
    assert len(auth_sdk.embeddings.calls) == 1


def test_batch_limit_is_checked_before_request():
    sdk = FakeSDK([])
    client = EmbeddingClient(
        api_key="test-key", dimensions=3, sdk_client=sdk, min_interval=0
    )
    with pytest.raises(EmbeddingClientError) as exc:
        client.embed(_items(11))
    assert exc.value.code == "batch_too_large"
    assert sdk.embeddings.calls == []


def test_error_redaction_removes_key_and_input():
    secret = "sk-1234567890abcdef"
    input_text = "private input body"
    safe = sanitize_embedding_error(
        f"Authorization: Bearer {secret}; body={input_text}",
        sensitive_texts=(input_text,),
    )
    assert secret not in safe
    assert input_text not in safe
    assert "redacted" in safe
