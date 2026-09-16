"""`chunks_vec` maintenance and the batched embedding that fills it.

**A vector is addressed by `chunk_id`, and there is no `rowid` here to fall back on.** The table is
declared with an explicit `chunk_id INTEGER PRIMARY KEY`, and a `vec0` table declared that way
exposes no `rowid` column at all — measured: selecting one raises `no such column`. That is the
opposite of the memory store's vector table, which has no key column and is addressed by `rowid`, so
the resemblance between the two is a trap rather than a shortcut.

**Nothing cascades.** `vec0` takes no foreign key, so a vector outlives the chunk row it belongs to
unless something deletes it explicitly — and an unidentified vector is a silent false positive in
retrieval, matching a query and resolving to nothing. The per-file transaction in `writes.py` is the
only thing that keeps the two in step.
"""

import asyncio
from collections.abc import Sequence

import aiosqlite

from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.indexing.encoder import Encoder
from zikaron.core.indexing.vectors import normalize, serialize
from zikaron.core.knowledge.chunking import FileChunkPlan


def _reject_embed() -> ZikaronError:
    return ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.EMBED)


async def embed_chunks(
    plan: FileChunkPlan, *, encoder: Encoder, embed_dim: int, batch_size: int
) -> tuple[bytes, ...]:
    """Embed every chunk of one file and return the vectors ready for `chunks_vec`.

    Runs **outside** any transaction, deliberately: inference is the expensive step of a build by an
    order of magnitude, and holding SQLite's single write lock across it would make every concurrent
    reader's `busy_timeout` a function of model speed. Nothing is staged at this point, so a failure
    here loses nothing.

    **Batched, and the batch size may not change the answer.** Splitting the file's chunks into
    passes of `batch_size` is a throughput decision; a chunk's vector must be the same whether it
    was embedded alone or beside thirty-one others, which holds when pooling is mask-aware and
    fails silently when it is not — the failure being an embedding that depends on what else
    happened to be in the batch.

    Each pass goes through a worker thread because inference is blocking and CPU-bound, and this is
    a coroutine: running it inline would hold the event loop for the whole pass.

    Args:
        plan: the chunks to embed, in `part_index` order, carrying the prefix their sequences were
            budgeted against — which is why this takes no path of its own to prepend.
        encoder: the artifact, whose identity the caller has already checked against the corpus.
        embed_dim: the width this knowledge base's `chunks_vec` column was created at.
        batch_size: `knowledge_embed_batch`.

    Returns:
        One serialized unit-length vector per chunk, in `part_index` order.

    Raises:
        ZikaronError: `INDEX_FAILED` at stage `embed` if the embedder raises, returns a different
            number of vectors than it was given texts, or returns one of the wrong width — each of
            which would otherwise be stored as a vector that does not describe its chunk.
    """
    texts = plan.embedded_texts()
    produced: list[tuple[float, ...]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        produced.extend(await _embed_one_pass(batch, encoder=encoder))
    return tuple(serialize(normalize(vector, embed_dim=embed_dim)) for vector in produced)


async def _embed_one_pass(
    texts: Sequence[str], *, encoder: Encoder
) -> tuple[tuple[float, ...], ...]:
    """One forward pass, with the embedder's own failures named as this layer's."""
    try:
        produced = await asyncio.to_thread(encoder.embed, texts)
    except ZikaronError:
        raise
    except Exception as error:
        raise _reject_embed() from error
    if len(produced) != len(texts):
        raise _reject_embed()
    return produced


async def insert(db: aiosqlite.Connection, *, chunk_id: int, vector: bytes) -> None:
    """Store one chunk's vector under the chunk's own id."""
    await db.execute(
        "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)", (chunk_id, vector)
    )


async def delete(db: aiosqlite.Connection, *, chunk_ids: Sequence[int]) -> None:
    """Remove the vectors for `chunk_ids`, which may be empty.

    One statement per id rather than an `IN` list: `vec0` is a virtual table, and keeping its
    deletes to the primary-key form the extension documents is worth more than saving round trips on
    a set bounded by one file's chunk count.
    """
    for chunk_id in chunk_ids:
        await db.execute("DELETE FROM chunks_vec WHERE chunk_id = ?", (chunk_id,))
