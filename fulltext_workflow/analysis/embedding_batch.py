"""OpenAI-compatible Bailian Batch transport for Method embeddings."""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

from openai import OpenAI

import config
from analysis.embedding_client import sanitize_embedding_error
from analysis.embedding_inputs import MethodEmbeddingInput
from analysis.embedding_store import (
    CacheWrite,
    attach_remote_batch,
    create_embedding_job,
    finalize_embedding_job,
    get_embedding_job_items,
    get_remote_batch,
    put_cached_vectors,
    update_remote_batch,
    upsert_job_item,
)


TERMINAL_BATCH_STATES = {"completed", "failed", "expired", "cancelled"}


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _content_bytes(response: Any) -> bytes:
    content = _field(response, "content")
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    reader = getattr(response, "read", None)
    if callable(reader):
        value = reader()
        return value if isinstance(value, bytes) else str(value).encode("utf-8")
    raise ValueError("Batch output content is unavailable")


class BailianEmbeddingBatch:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = config.EMBEDDING_API_BASE,
        provider: str = config.EMBEDDING_PROVIDER,
        model: str = config.EMBEDDING_MODEL,
        dimensions: int = config.EMBEDDING_DIMENSIONS,
        sdk_client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Embedding API key is not configured")
        self.provider = provider
        self.model = model
        self.dimensions = dimensions
        self._client = sdk_client or OpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=config.EMBEDDING_REQUEST_TIMEOUT,
            max_retries=0,
        )

    def submit(self, inputs: Sequence[MethodEmbeddingInput]) -> dict[str, Any]:
        if not inputs:
            raise ValueError("No uncached Method inputs to submit")
        if len(inputs) > 50_000:
            raise ValueError("Bailian Batch supports at most 50,000 requests per file")
        estimated_tokens = sum(item.estimated_tokens for item in inputs)
        job_id = create_embedding_job(
            job_type="method_shadow_batch",
            provider=self.provider,
            model=self.model,
            dimensions=self.dimensions,
            scope={"only_active_applies_method": True, "taxonomy_version": config.METHOD_TAXONOMY_VERSION},
            planned_items=len(inputs),
            estimated_tokens=estimated_tokens,
            estimated_cost_cny=estimated_tokens / 1_000_000 * config.EMBEDDING_BATCH_CNY_PER_MTOK,
        )
        for item in inputs:
            upsert_job_item(
                job_id,
                item_type="method",
                item_id=str(item.method_entity_id),
                input_sha256=item.input_sha256,
                context_quality=item.context_quality,
                input_chars=item.input_chars,
                estimated_tokens=item.estimated_tokens,
                status="submitted",
            )

        temp_path: str | None = None
        input_file_id = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".jsonl", delete=False
            ) as handle:
                temp_path = handle.name
                for item in inputs:
                    row = {
                        "custom_id": f"method-{item.method_entity_id}",
                        "method": "POST",
                        "url": "/v1/embeddings",
                        "body": {
                            "model": self.model,
                            "input": item.text,
                            "dimensions": self.dimensions,
                            "encoding_format": "float",
                        },
                    }
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            with Path(temp_path).open("rb") as file_handle:
                uploaded = self._client.files.create(file=file_handle, purpose="batch")
            input_file_id = str(_field(uploaded, "id") or "")
            if not input_file_id:
                raise ValueError("Bailian did not return an input file id")
            batch = self._client.batches.create(
                input_file_id=input_file_id,
                endpoint="/v1/embeddings",
                completion_window="24h",
                metadata={
                    "ds_name": f"method-family-{job_id[:8]}",
                    "taxonomy_version": config.METHOD_TAXONOMY_VERSION,
                },
            )
            remote_id = str(_field(batch, "id") or "")
            status = str(_field(batch, "status") or "validating")
            if not remote_id:
                raise ValueError("Bailian did not return a batch id")
            attach_remote_batch(
                job_id,
                remote_batch_id=remote_id,
                input_file_id=input_file_id,
                remote_status=status,
            )
            return {
                "job_id": job_id,
                "remote_batch_id": remote_id,
                "status": status,
                "submitted_items": len(inputs),
                "estimated_tokens": estimated_tokens,
                "estimated_cost_cny": round(estimated_tokens / 1_000_000 * config.EMBEDDING_BATCH_CNY_PER_MTOK, 6),
            }
        except Exception as exc:
            finalize_embedding_job(
                job_id,
                status="failed",
                cache_hits=0,
                requested_items=0,
                succeeded_items=0,
                failed_items=len(inputs),
                error_summary=sanitize_embedding_error(exc, sensitive_texts=tuple(item.text for item in inputs)),
            )
            if input_file_id:
                try:
                    self._client.files.delete(input_file_id)
                except Exception:
                    pass
            raise
        finally:
            if temp_path and os.path.isfile(temp_path):
                os.remove(temp_path)

    def status(self, job_id: str) -> dict[str, Any]:
        local = get_remote_batch(job_id)
        if not local:
            raise ValueError(f"Unknown embedding batch job: {job_id}")
        batch = self._client.batches.retrieve(local["remote_batch_id"])
        status = str(_field(batch, "status") or "unknown")
        output_file_id = _field(batch, "output_file_id")
        error_file_id = _field(batch, "error_file_id")
        update_remote_batch(
            job_id,
            remote_status=status,
            output_file_id=str(output_file_id) if output_file_id else None,
            error_file_id=str(error_file_id) if error_file_id else None,
        )
        return {
            "job_id": job_id,
            "remote_batch_id": local["remote_batch_id"],
            "status": status,
            "output_ready": bool(output_file_id),
            "error_file": bool(error_file_id),
        }

    def ingest(self, job_id: str, *, cleanup_remote_files: bool = True) -> dict[str, Any]:
        remote = get_remote_batch(job_id)
        if not remote:
            raise ValueError(f"Unknown embedding batch job: {job_id}")
        status_info = self.status(job_id)
        if status_info["status"] != "completed":
            raise ValueError(f"Batch job is not completed: {status_info['status']}")
        remote = get_remote_batch(job_id) or remote
        output_file_id = remote.get("output_file_id")
        if not output_file_id:
            raise ValueError("Completed batch has no output file")

        items = {str(row["item_id"]): row for row in get_embedding_job_items(job_id)}
        raw = _content_bytes(self._client.files.content(output_file_id))
        successes: set[str] = set()
        actual_tokens = 0
        writes: list[CacheWrite] = []
        for line in raw.decode("utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            custom_id = str(row.get("custom_id") or "")
            item_id = custom_id.removeprefix("method-")
            item = items.get(item_id)
            response = row.get("response") or {}
            body = response.get("body") or {}
            data = body.get("data") or []
            if item is None or response.get("status_code") != 200 or len(data) != 1:
                continue
            vector = data[0].get("embedding")
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                continue
            values = tuple(float(value) for value in vector)
            if not all(math.isfinite(value) for value in values) or not any(values):
                continue
            usage = body.get("usage") or {}
            tokens = usage.get("prompt_tokens")
            actual_tokens += int(tokens) if isinstance(tokens, int) and tokens >= 0 else 0
            writes.append(
                CacheWrite(
                    input_sha256=str(item["input_sha256"]),
                    values=values,
                    input_chars=int(item["input_chars"]),
                    prompt_tokens=tokens if isinstance(tokens, int) else None,
                )
            )
            successes.add(item_id)

        put_cached_vectors(
            writes,
            provider=self.provider,
            model=self.model,
            dimensions=self.dimensions,
        )
        for item_id, item in items.items():
            succeeded = item_id in successes
            upsert_job_item(
                job_id,
                item_type="method",
                item_id=item_id,
                input_sha256=str(item["input_sha256"]),
                context_quality=str(item["context_quality"]),
                input_chars=int(item["input_chars"]),
                estimated_tokens=int(item["estimated_tokens"]),
                status="succeeded" if succeeded else "failed",
                attempts=1,
                error_code=None if succeeded else "missing_batch_result",
                error_summary=None if succeeded else "No valid vector was present in the batch output",
            )
        failed = len(items) - len(successes)
        finalize_embedding_job(
            job_id,
            status="completed" if failed == 0 else "partial",
            cache_hits=0,
            requested_items=len(items),
            succeeded_items=len(successes),
            failed_items=failed,
            actual_tokens=actual_tokens,
        )
        update_remote_batch(
            job_id,
            remote_status="completed",
            output_file_id=str(output_file_id),
            error_file_id=remote.get("error_file_id"),
            ingested=True,
        )
        deleted: list[str] = []
        if cleanup_remote_files:
            for file_id in (remote.get("input_file_id"), output_file_id, remote.get("error_file_id")):
                if file_id:
                    try:
                        self._client.files.delete(file_id)
                        deleted.append(str(file_id))
                    except Exception:
                        pass
        return {
            "job_id": job_id,
            "status": "completed" if failed == 0 else "partial",
            "succeeded_items": len(successes),
            "failed_items": failed,
            "actual_tokens": actual_tokens,
            "remote_files_deleted": len(deleted),
        }
