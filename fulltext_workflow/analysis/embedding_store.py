"""SQLite vector cache and embedding job persistence."""
from __future__ import annotations

import json
import math
import sys
import uuid
from array import array
from dataclasses import dataclass
from typing import Iterable, Sequence

from db.schema import get_conn


@dataclass(frozen=True)
class CachedVector:
    input_sha256: str
    values: tuple[float, ...]
    vector_norm: float
    prompt_tokens: int | None = None


@dataclass(frozen=True)
class CacheWrite:
    input_sha256: str
    values: Sequence[float]
    input_chars: int
    prompt_tokens: int | None = None


class CorruptEmbeddingCache(ValueError):
    pass


def vector_to_blob(values: Sequence[float]) -> tuple[bytes, float]:
    floats = tuple(float(value) for value in values)
    if not floats or not all(math.isfinite(value) for value in floats):
        raise ValueError("Embedding vector must contain finite values")
    norm = math.sqrt(sum(value * value for value in floats))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("Embedding vector norm must be positive and finite")
    packed = array("f", floats)
    if sys.byteorder != "little":
        packed.byteswap()
    return packed.tobytes(), norm


def blob_to_vector(blob: bytes, dimensions: int) -> tuple[float, ...]:
    if len(blob) != dimensions * 4:
        raise CorruptEmbeddingCache("Embedding cache BLOB length mismatch")
    unpacked = array("f")
    unpacked.frombytes(blob)
    if sys.byteorder != "little":
        unpacked.byteswap()
    values = tuple(float(value) for value in unpacked)
    if len(values) != dimensions or not all(math.isfinite(value) for value in values):
        raise CorruptEmbeddingCache("Embedding cache vector is invalid")
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0:
        raise CorruptEmbeddingCache("Embedding cache vector norm is invalid")
    return values


def _chunks(values: Sequence[str], size: int = 500) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def cached_hashes(
    input_hashes: Sequence[str],
    *,
    provider: str,
    model: str,
    dimensions: int,
) -> set[str]:
    unique = sorted(set(input_hashes))
    found: set[str] = set()
    if not unique:
        return found
    with get_conn() as conn:
        for chunk in _chunks(unique):
            marks = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""SELECT input_sha256 FROM embedding_cache
                    WHERE provider=? AND model=? AND dimensions=?
                      AND input_sha256 IN ({marks})
                      AND length(vector_blob)=dimensions*4
                      AND vector_norm > 0""",
                (provider, model, dimensions, *chunk),
            ).fetchall()
            found.update(str(row["input_sha256"]) for row in rows)
    return found


def get_cached_vectors(
    input_hashes: Sequence[str],
    *,
    provider: str,
    model: str,
    dimensions: int,
    touch: bool = True,
) -> dict[str, CachedVector]:
    unique = sorted(set(input_hashes))
    result: dict[str, CachedVector] = {}
    if not unique:
        return result
    with get_conn() as conn:
        for chunk in _chunks(unique):
            marks = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""SELECT input_sha256, vector_blob, vector_norm, prompt_tokens
                    FROM embedding_cache
                    WHERE provider=? AND model=? AND dimensions=?
                      AND input_sha256 IN ({marks})""",
                (provider, model, dimensions, *chunk),
            ).fetchall()
            valid_hashes: list[str] = []
            for row in rows:
                input_hash = str(row["input_sha256"])
                try:
                    values = blob_to_vector(bytes(row["vector_blob"]), dimensions)
                    stored_norm = float(row["vector_norm"])
                    if not math.isfinite(stored_norm) or stored_norm <= 0:
                        raise CorruptEmbeddingCache("Stored vector norm is invalid")
                except (TypeError, ValueError, CorruptEmbeddingCache):
                    continue
                result[input_hash] = CachedVector(
                    input_sha256=input_hash,
                    values=values,
                    vector_norm=stored_norm,
                    prompt_tokens=row["prompt_tokens"],
                )
                valid_hashes.append(input_hash)
            if touch and valid_hashes:
                touch_marks = ",".join("?" for _ in valid_hashes)
                conn.execute(
                    f"""UPDATE embedding_cache SET last_used_at=CURRENT_TIMESTAMP
                        WHERE provider=? AND model=? AND dimensions=?
                          AND input_sha256 IN ({touch_marks})""",
                    (provider, model, dimensions, *valid_hashes),
                )
    return result


def put_cached_vectors(
    writes: Sequence[CacheWrite],
    *,
    provider: str,
    model: str,
    dimensions: int,
) -> int:
    prepared: list[tuple] = []
    for write in writes:
        if len(write.values) != dimensions:
            raise ValueError("Embedding vector dimension mismatch")
        blob, norm = vector_to_blob(write.values)
        prepared.append(
            (
                write.input_sha256,
                provider,
                model,
                dimensions,
                blob,
                norm,
                int(write.input_chars),
                write.prompt_tokens,
            )
        )
    if not prepared:
        return 0
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany(
            """INSERT INTO embedding_cache
               (input_sha256, provider, model, dimensions, vector_blob,
                vector_norm, input_chars, prompt_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(input_sha256, provider, model, dimensions) DO NOTHING""",
            prepared,
        )
        return conn.total_changes - before


def create_embedding_job(
    *,
    job_type: str,
    provider: str,
    model: str,
    dimensions: int,
    scope: dict | None = None,
    planned_items: int = 0,
    estimated_tokens: int = 0,
    estimated_cost_cny: float = 0.0,
) -> str:
    job_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO embedding_jobs
               (job_id, job_type, status, provider, model, dimensions,
                scope_json, planned_items, estimated_tokens, estimated_cost_cny)
               VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                job_type,
                provider,
                model,
                dimensions,
                json.dumps(scope or {}, ensure_ascii=False, sort_keys=True),
                planned_items,
                estimated_tokens,
                estimated_cost_cny,
            ),
        )
    return job_id


def upsert_job_item(
    job_id: str,
    *,
    item_type: str,
    item_id: str,
    input_sha256: str,
    context_quality: str,
    input_chars: int,
    estimated_tokens: int,
    status: str,
    cache_hit: bool = False,
    attempts: int = 0,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO embedding_job_items
               (job_id, item_type, item_id, input_sha256, context_quality,
                input_chars, estimated_tokens, status, cache_hit, attempts,
                error_code, error_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_id, item_type, item_id) DO UPDATE SET
                 input_sha256=excluded.input_sha256,
                 context_quality=excluded.context_quality,
                 input_chars=excluded.input_chars,
                 estimated_tokens=excluded.estimated_tokens,
                 status=excluded.status,
                 cache_hit=excluded.cache_hit,
                 attempts=excluded.attempts,
                 error_code=excluded.error_code,
                 error_summary=excluded.error_summary,
                 updated_at=CURRENT_TIMESTAMP""",
            (
                job_id,
                item_type,
                item_id,
                input_sha256,
                context_quality,
                input_chars,
                estimated_tokens,
                status,
                1 if cache_hit else 0,
                attempts,
                error_code,
                error_summary,
            ),
        )


def finalize_embedding_job(
    job_id: str,
    *,
    status: str,
    cache_hits: int,
    requested_items: int,
    succeeded_items: int,
    failed_items: int,
    actual_tokens: int = 0,
    error_summary: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE embedding_jobs SET
                 status=?, cache_hits=?, requested_items=?, succeeded_items=?,
                 failed_items=?, actual_tokens=?, error_summary=?,
                 updated_at=CURRENT_TIMESTAMP, completed_at=CURRENT_TIMESTAMP
               WHERE job_id=?""",
            (
                status,
                cache_hits,
                requested_items,
                succeeded_items,
                failed_items,
                actual_tokens,
                error_summary,
                job_id,
            ),
        )


def attach_remote_batch(
    job_id: str,
    *,
    remote_batch_id: str,
    input_file_id: str,
    remote_status: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO embedding_batch_jobs
               (job_id, remote_batch_id, input_file_id, remote_status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(job_id) DO UPDATE SET
                 remote_batch_id=excluded.remote_batch_id,
                 input_file_id=excluded.input_file_id,
                 remote_status=excluded.remote_status,
                 last_polled_at=CURRENT_TIMESTAMP""",
            (job_id, remote_batch_id, input_file_id, remote_status),
        )


def update_remote_batch(
    job_id: str,
    *,
    remote_status: str,
    output_file_id: str | None = None,
    error_file_id: str | None = None,
    ingested: bool = False,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE embedding_batch_jobs SET
                 remote_status=?,
                 output_file_id=COALESCE(?, output_file_id),
                 error_file_id=COALESCE(?, error_file_id),
                 last_polled_at=CURRENT_TIMESTAMP,
                 ingested_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE ingested_at END
               WHERE job_id=?""",
            (remote_status, output_file_id, error_file_id, 1 if ingested else 0, job_id),
        )


def get_remote_batch(job_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT b.*, j.provider, j.model, j.dimensions, j.status AS job_status,
                      j.planned_items, j.estimated_tokens, j.estimated_cost_cny
               FROM embedding_batch_jobs b
               JOIN embedding_jobs j ON j.job_id=b.job_id
               WHERE b.job_id=?""",
            (job_id,),
        ).fetchone()
    return dict(row) if row else None


def get_embedding_job_items(job_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM embedding_job_items
               WHERE job_id=? ORDER BY item_type, item_id""",
            (job_id,),
        ).fetchall()
    return [dict(row) for row in rows]
