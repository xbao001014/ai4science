from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.embedding_batch import BailianEmbeddingBatch  # noqa: E402
from analysis.embedding_inputs import MethodEmbeddingInput  # noqa: E402
from analysis.embedding_store import get_cached_vectors  # noqa: E402


class FakeFiles:
    def __init__(self):
        self.input_lines = []
        self.deleted = []

    def create(self, *, file, purpose):
        assert purpose == "batch"
        self.input_lines = [json.loads(line) for line in file.read().decode("utf-8").splitlines()]
        return SimpleNamespace(id="file-input")

    def content(self, file_id):
        assert file_id == "file-output"
        lines = []
        for request in reversed(self.input_lines):
            lines.append(
                json.dumps(
                    {
                        "custom_id": request["custom_id"],
                        "response": {
                            "status_code": 200,
                            "body": {
                                "data": [{"index": 0, "embedding": [1.0, 2.0, 3.0]}],
                                "usage": {"prompt_tokens": 4},
                            },
                        },
                        "error": None,
                    }
                )
            )
        return SimpleNamespace(content=("\n".join(lines) + "\n").encode())

    def delete(self, file_id):
        self.deleted.append(file_id)
        return SimpleNamespace(id=file_id, deleted=True)


class FakeBatches:
    def __init__(self):
        self.created = None

    def create(self, **kwargs):
        self.created = kwargs
        return SimpleNamespace(id="batch-1", status="validating")

    def retrieve(self, batch_id):
        assert batch_id == "batch-1"
        return SimpleNamespace(
            id=batch_id,
            status="completed",
            output_file_id="file-output",
            error_file_id=None,
        )


def _input(method_id: int, hash_char: str) -> MethodEmbeddingInput:
    text = f"method: test {method_id}"
    return MethodEmbeddingInput(
        method_entity_id=method_id,
        text=text,
        input_sha256=hash_char * 64,
        context_quality="evidence",
        input_chars=len(text),
        input_bytes=len(text.encode()),
        estimated_tokens=6,
    )


def test_batch_submit_status_ingest_and_cleanup(tmp_path, monkeypatch):
    import config
    from db.schema import init_db

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "batch.sqlite"))
    init_db()
    files = FakeFiles()
    batches = FakeBatches()
    sdk = SimpleNamespace(files=files, batches=batches)
    client = BailianEmbeddingBatch(
        api_key="test-key",
        provider="bailian",
        model="test-model",
        dimensions=3,
        sdk_client=sdk,
    )
    submitted = client.submit([_input(1, "a"), _input(2, "b")])
    assert submitted["submitted_items"] == 2
    assert batches.created["endpoint"] == "/v1/embeddings"
    assert all(row["url"] == "/v1/embeddings" for row in files.input_lines)
    assert all(row["body"]["dimensions"] == 3 for row in files.input_lines)
    assert client.status(submitted["job_id"])["status"] == "completed"
    ingested = client.ingest(submitted["job_id"])
    assert ingested["succeeded_items"] == 2
    assert ingested["failed_items"] == 0
    cached = get_cached_vectors(
        ["a" * 64, "b" * 64],
        provider="bailian",
        model="test-model",
        dimensions=3,
    )
    assert set(cached) == {"a" * 64, "b" * 64}
    assert set(files.deleted) == {"file-input", "file-output"}
