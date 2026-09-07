from __future__ import annotations

import hashlib
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.embedding_client import EmbeddingClient, EmbeddingItem  # noqa: E402
from analysis.embedding_service import embed_with_cache  # noqa: E402
from analysis.embedding_store import (  # noqa: E402
    CacheWrite,
    get_cached_vectors,
    put_cached_vectors,
)


class FakeEmbeddings:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[1.0, 2.0, 3.0])
                for index, _ in enumerate(kwargs["input"])
            ],
            usage=SimpleNamespace(prompt_tokens=5),
        )


def test_cache_round_trip_and_duplicate_insert(tmp_path, monkeypatch):
    import config
    from db.schema import init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "embedding.sqlite"))
    init_db()
    write = CacheWrite("a" * 64, (1.25, -2.5, 3.75), 12)
    assert put_cached_vectors(
        [write], provider="bailian", model="test", dimensions=3
    ) == 1
    assert put_cached_vectors(
        [write], provider="bailian", model="test", dimensions=3
    ) == 0
    cached = get_cached_vectors(
        [write.input_sha256], provider="bailian", model="test", dimensions=3
    )
    assert cached[write.input_sha256].values == (1.25, -2.5, 3.75)


def test_corrupt_nonfinite_cache_is_not_returned(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "corrupt.sqlite"))
    init_db()
    values = array("f", [1.0, float("nan"), 2.0]).tobytes()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO embedding_cache
               (input_sha256, provider, model, dimensions, vector_blob,
                vector_norm, input_chars)
               VALUES (?, 'bailian', 'test', 3, ?, 1.0, 10)""",
            ("b" * 64, values),
        )
    assert get_cached_vectors(
        ["b" * 64], provider="bailian", model="test", dimensions=3
    ) == {}


def test_cache_first_service_skips_second_api_call(tmp_path, monkeypatch):
    import config
    from db.schema import get_conn, init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "service.sqlite"))
    init_db()
    sdk = SimpleNamespace(embeddings=FakeEmbeddings())
    client = EmbeddingClient(
        api_key="test-key",
        model="test",
        dimensions=3,
        sdk_client=sdk,
        min_interval=0,
    )
    text = "method: test"
    item = EmbeddingItem("1", hashlib.sha256(text.encode()).hexdigest(), text)
    first = embed_with_cache(
        client,
        [item],
        provider="bailian",
        model="test",
        dimensions=3,
        job_type="mock",
    )
    second = embed_with_cache(
        client,
        [item],
        provider="bailian",
        model="test",
        dimensions=3,
        job_type="mock",
    )
    assert sdk.embeddings.calls == 1
    assert first.requested_items == 1
    assert second.requested_items == 0
    assert second.cache_hits == 1
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM embedding_jobs").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0] == 1
