"""Cache-first orchestration for small synchronous embedding jobs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from analysis.embedding_client import (
    EmbeddingClient,
    EmbeddingClientError,
    EmbeddingItem,
    EmbeddingVector,
    sanitize_embedding_error,
)
from analysis.embedding_store import (
    CacheWrite,
    create_embedding_job,
    finalize_embedding_job,
    get_cached_vectors,
    put_cached_vectors,
    upsert_job_item,
)


@dataclass(frozen=True)
class EmbeddingJobResult:
    job_id: str
    vectors: tuple[EmbeddingVector, ...]
    cache_hits: int
    requested_items: int
    actual_tokens: int


def embed_with_cache(
    client: EmbeddingClient,
    items: Sequence[EmbeddingItem],
    *,
    provider: str,
    model: str,
    dimensions: int,
    job_type: str,
    item_type: str = "text",
    context_quality: str = "probe",
) -> EmbeddingJobResult:
    """Resolve cached values and request only misses, with resumable job records."""
    estimated_tokens = sum(max(1, (len(item.text.encode("utf-8")) + 2) // 3) for item in items)
    job_id = create_embedding_job(
        job_type=job_type,
        provider=provider,
        model=model,
        dimensions=dimensions,
        scope={"input_count": len(items)},
        planned_items=len(items),
        estimated_tokens=estimated_tokens,
    )
    cached = get_cached_vectors(
        [item.input_sha256 for item in items],
        provider=provider,
        model=model,
        dimensions=dimensions,
    )
    resolved: dict[str, EmbeddingVector] = {}
    missing: list[EmbeddingItem] = []
    for item in items:
        cached_item = cached.get(item.input_sha256)
        if cached_item is None:
            missing.append(item)
            status = "pending"
            cache_hit = False
        else:
            resolved[item.item_id] = EmbeddingVector(
                item_id=item.item_id,
                input_sha256=item.input_sha256,
                values=cached_item.values,
            )
            status = "succeeded"
            cache_hit = True
        upsert_job_item(
            job_id,
            item_type=item_type,
            item_id=item.item_id,
            input_sha256=item.input_sha256,
            context_quality=context_quality,
            input_chars=len(item.text),
            estimated_tokens=max(1, (len(item.text.encode("utf-8")) + 2) // 3),
            status=status,
            cache_hit=cache_hit,
        )

    requested = 0
    actual_tokens = 0
    failed = 0
    first_error: EmbeddingClientError | None = None
    for start in range(0, len(missing), client.batch_size):
        batch = missing[start : start + client.batch_size]
        requested += len(batch)
        try:
            response = client.embed(batch)
            actual_tokens += response.prompt_tokens or 0
            by_id = {vector.item_id: vector for vector in response.vectors}
            put_cached_vectors(
                [
                    CacheWrite(
                        input_sha256=vector.input_sha256,
                        values=vector.values,
                        input_chars=len(item.text),
                    )
                    for item in batch
                    for vector in [by_id[item.item_id]]
                ],
                provider=provider,
                model=model,
                dimensions=dimensions,
            )
            for item in batch:
                resolved[item.item_id] = by_id[item.item_id]
                upsert_job_item(
                    job_id,
                    item_type=item_type,
                    item_id=item.item_id,
                    input_sha256=item.input_sha256,
                    context_quality=context_quality,
                    input_chars=len(item.text),
                    estimated_tokens=max(1, (len(item.text.encode("utf-8")) + 2) // 3),
                    status="succeeded",
                    attempts=1,
                )
        except EmbeddingClientError as exc:
            first_error = first_error or exc
            failed += len(batch)
            safe_error = sanitize_embedding_error(
                exc, sensitive_texts=tuple(item.text for item in batch)
            )
            for item in batch:
                upsert_job_item(
                    job_id,
                    item_type=item_type,
                    item_id=item.item_id,
                    input_sha256=item.input_sha256,
                    context_quality=context_quality,
                    input_chars=len(item.text),
                    estimated_tokens=max(1, (len(item.text.encode("utf-8")) + 2) // 3),
                    status="failed",
                    attempts=1,
                    error_code=exc.code,
                    error_summary=safe_error,
                )

    succeeded = len(resolved)
    final_status = "completed" if failed == 0 else ("partial" if succeeded else "failed")
    finalize_embedding_job(
        job_id,
        status=final_status,
        cache_hits=len(items) - len(missing),
        requested_items=requested,
        succeeded_items=succeeded,
        failed_items=failed,
        actual_tokens=actual_tokens,
        error_summary=sanitize_embedding_error(first_error) if first_error else None,
    )
    if first_error is not None:
        raise EmbeddingClientError(first_error.code, sanitize_embedding_error(first_error))
    return EmbeddingJobResult(
        job_id=job_id,
        vectors=tuple(resolved[item.item_id] for item in items),
        cache_hits=len(items) - len(missing),
        requested_items=requested,
        actual_tokens=actual_tokens,
    )
