"""The dense index: `memory_chunk` rows, their `vec0` vectors, and the order they are written in.

Two constraints from `design/schema.md` shape everything here.

**Invariant 1 — `memory_vec.rowid == memory_chunk.chunk_id`.** That equality is the *only* link
between a vector and the memory it belongs to; `memory_vec` is a virtual table with no columns
beyond the embedding and no foreign key to anything. So a vector is inserted with an explicit
rowid taken from the chunk row that was just written, never with an autoassigned one.

**Deletion is vectors first, then chunks.** The reverse order fails unsafely: with no foreign key,
deleting chunks first and then being interrupted leaves vectors nothing identifies, and an
unidentified vector is a silent false positive in retrieval — it matches a query and resolves to
no memory, or to the wrong one. An orphaned *chunk* row, the failure the chosen order can leave,
is detectable by a join and repairable by re-chunking.
"""

import asyncio
import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass

import aiosqlite

from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.indexing.chunking import ChunkPlan
from zikaron.core.indexing.encoder import Encoder

#: `vec0`'s wire format for a `float[N]` column: N little-endian 32-bit floats, no header.
_FLOAT32 = "<{n}f"


@dataclass(frozen=True, slots=True)
class IndexIdentity:
    """What every chunk row records about the vector beside it: the model, and its width.

    The pair `schema.md` calls dual-homed and `meta` holds authoritatively — *what the existing
    index was actually built with*, as against what a config file currently asks for. They travel
    together because a width without the model that produced it says nothing: D20's whole finding is
    that a same-width model swap corrupts `vec0` silently, so the model name is the only thing that
    makes a stored vector's meaning checkable.
    """

    embed_model: str
    embed_dim: int


def _reject_embed() -> ZikaronError:
    return ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.EMBED)


def _normalize(vector: Sequence[float], *, embed_dim: int) -> tuple[float, ...]:
    """Scale one vector to unit length, refusing anything the metric cannot describe.

    `retrieval.md` states the corpus is L2-normalized at write time, and the cosine arithmetic every
    threshold in the corpus is expressed in — `cos = 1 - d^2/2` over `vec0`'s L2 distance — is true
    only of unit vectors. The deployed `bge-small` already returns unit vectors, so this is
    measurably a no-op today; it is done here anyway because D20 keeps the model a config key, and a
    model that returned unnormalized vectors would otherwise silently invalidate every cutoff rather
    than failing.

    A zero-norm or non-finite vector has no direction to preserve and cannot be compared to
    anything, so it is `index_failed` rather than a divide that produces `inf` and stores it.
    """
    if len(vector) != embed_dim:
        raise _reject_embed()
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if not math.isfinite(norm) or norm == 0.0:
        raise _reject_embed()
    return tuple(value / norm for value in vector)


def _serialize(vector: Sequence[float]) -> bytes:
    return struct.pack(_FLOAT32.format(n=len(vector)), *vector)


async def embed_chunks(
    plan: ChunkPlan, *, gist: str, encoder: Encoder, embed_dim: int
) -> tuple[bytes, ...]:
    """Embed every chunk's assembled sequence and return the vectors ready for `vec0`.

    Runs **outside** any transaction, deliberately: a cold model load costs hundreds of
    milliseconds and holding SQLite's single write lock across it would make every concurrent
    writer's `busy_timeout` a function of model-load time. Nothing is staged in the store at this
    point, so a failure here loses nothing.

    The embedder call goes through a worker thread because it is blocking and CPU-bound, and this
    is a coroutine: running it inline would hold the event loop for the whole inference, stalling
    every other request the service is serving for the duration.

    Raises:
        ZikaronError: `INDEX_FAILED` at stage `embed` if the embedder raises, returns a different
            number of vectors than there are chunks, or returns one of the wrong width — each of
            which would otherwise be written as a vector that does not describe its chunk.
    """
    texts = plan.embedded_texts(gist)
    try:
        vectors = await asyncio.to_thread(encoder.embed, texts)
    except ZikaronError:
        raise
    except Exception as error:
        raise _reject_embed() from error
    if len(vectors) != len(texts):
        raise _reject_embed()
    return tuple(_serialize(_normalize(vector, embed_dim=embed_dim)) for vector in vectors)


async def insert_chunks(
    db: aiosqlite.Connection,
    *,
    memory_uuid: str,
    plan: ChunkPlan,
    vectors: Sequence[bytes],
    identity: IndexIdentity,
) -> None:
    """Write every chunk row and its vector, pairing them by the chunk row's own `chunk_id`.

    `chunk_id` is assigned by SQLite on the chunk insert and read back from that same statement,
    then used as the explicit `memory_vec` rowid — invariant 1. Read back rather than predicted: a
    `MAX(chunk_id) + 1` guess would be wrong the moment a row is ever deleted, and wrong silently,
    pairing a new vector with a stale chunk id.

    Args:
        vectors: one serialized vector per chunk, in `part_index` order, as `embed_chunks` returns
            them.
        identity: the model and width this store's index was built with, recorded on every chunk.
    """
    if len(vectors) != plan.n_chunks:
        raise _reject_embed()
    for chunk, vector in zip(plan.chunks, vectors, strict=True):
        cursor = await db.execute(
            "INSERT INTO memory_chunk "
            "(memory_uuid, part_index, token_count, truncated, embed_model, embed_dim) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                memory_uuid,
                chunk.part_index,
                chunk.token_count,
                int(chunk.truncated),
                identity.embed_model,
                identity.embed_dim,
            ),
        )
        chunk_id = cursor.lastrowid
        if chunk_id is None:
            raise ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.INDEX_WRITE)
        await db.execute(
            "INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)", (chunk_id, vector)
        )


async def delete_chunks(db: aiosqlite.Connection, *, memory_uuid: str) -> None:
    """Delete one memory's vectors, then its chunk rows — in that order, for the reason above.

    A memory with no chunks yet is not an error: `remember` calls nothing here, and an amend of a
    row whose chunks were removed by an earlier repair has nothing to remove.
    """
    rows = await db.execute_fetchall(
        "SELECT chunk_id FROM memory_chunk WHERE memory_uuid = ? ORDER BY part_index",
        (memory_uuid,),
    )
    for (chunk_id,) in rows:
        await db.execute("DELETE FROM memory_vec WHERE rowid = ?", (chunk_id,))
    await db.execute("DELETE FROM memory_chunk WHERE memory_uuid = ?", (memory_uuid,))
