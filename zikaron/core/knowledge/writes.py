"""One file's place in the index, changed or removed in a single transaction.

**Atomicity is per file, not per corpus.** A build is thousands of independent transactions, which
buys two things at once: a search running alongside it sees whole files or no files, never a
half-indexed one; and progress is durable, so an interrupted build resumes rather than restarting.

**Three tables have to move together and none of them will do it on its own.** `chunks_fts` is
external-content, so it observes no delete on `chunks`; `chunks_vec` is a virtual table that takes
no foreign key. Nothing here is a cascade, and the word does not apply: every deletion is issued by
hand, in an order chosen so that the values the lexical arm needs are still readable when it needs
them.

The caller owns the transaction. These functions stage work and never commit, so a file's chunks,
its `files` row, and whatever else that caller is doing in the same breath — clearing its pending
row, advancing its counters — commit together or not at all.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import aiosqlite

from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.knowledge import files, lexical, vectors
from zikaron.core.knowledge.chunking import FileChunkPlan

_CHUNK_COLUMNS = "path, part_index, start_line, end_line, text"


@dataclass(frozen=True, slots=True)
class _StoredChunk:
    """One chunk as it stands in the index, with exactly what removing it requires: its id, and the
    two column values the lexical arm was given when it was indexed."""

    chunk_id: int
    document: lexical.Document


async def _stored_chunks(db: aiosqlite.Connection, path: str) -> tuple[_StoredChunk, ...]:
    """Every chunk currently indexed for `path`, read before anything is deleted.

    Read first because the lexical arm's delete needs the values it was given at index time, and
    they exist only in the rows about to be removed.
    """
    rows = await db.execute_fetchall(
        "SELECT id, text, path FROM chunks WHERE path = ? ORDER BY part_index", (path,)
    )
    return tuple(
        _StoredChunk(
            chunk_id=int(chunk_id),
            # Both values come out of the row rather than from this function's own argument, even
            # though the path is what was searched for: what the delete needs is what was *indexed*,
            # and reading it back is what makes that true by construction instead of by reasoning.
            document=lexical.Document(text=str(text), path=str(indexed_path)),
        )
        for chunk_id, text, indexed_path in rows
    )


async def _clear(db: aiosqlite.Connection, path: str) -> None:
    """Remove every trace of `path` from all three tables, in the one order that works.

    Postings first, while the rows that say what was indexed are still there — the lexical delete
    takes the values it was given at index time, and given anything else it removes nothing and says
    nothing. Then vectors, then the chunk rows: vectors before their rows is the memory store's
    order too, and for the same reason. A chunk row with no vector is detectable by a join and
    repairable by reindexing, where a vector with no chunk row matches a query and resolves to
    nothing.
    """
    stored = await _stored_chunks(db, path)
    for chunk in stored:
        await lexical.remove(db, chunk_id=chunk.chunk_id, document=chunk.document)
    await vectors.delete(db, chunk_ids=[chunk.chunk_id for chunk in stored])
    await db.execute("DELETE FROM chunks WHERE path = ?", (path,))


async def index_file(
    db: aiosqlite.Connection,
    *,
    indexed: files.IndexedFile,
    plan: FileChunkPlan,
    embeddings: Sequence[bytes],
) -> None:
    """Replace everything the index holds for one file with this plan and these vectors.

    Replace rather than update: change detection tells us the file's content moved, and there is no
    correspondence between its old chunks and its new ones to preserve. A file the corpus has never
    seen takes the same path, since clearing a path with nothing under it removes nothing.

    Args:
        indexed: the `files` row to write, whose `chunk_count` is this plan's chunk count — the two
            are compared here rather than trusted, since a row claiming a count the chunks do not
            match is the one inconsistency no later reader can detect.
        plan: the chunks to store, in `part_index` order.
        embeddings: one serialized vector per chunk, in the same order.

    Raises:
        ZikaronError: `INDEX_FAILED` at stage `index_write` if the vectors, the plan and the row's
            count do not describe the same set of chunks, or if a chunk insert reports no id to pair
            its vector with.
    """
    if len(embeddings) != plan.n_chunks or indexed.chunk_count != plan.n_chunks:
        raise ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.INDEX_WRITE)
    await _clear(db, indexed.path)
    for chunk, vector in zip(plan.chunks, embeddings, strict=True):
        cursor = await db.execute(
            f"INSERT INTO chunks ({_CHUNK_COLUMNS}) VALUES (?, ?, ?, ?, ?)",  # noqa: S608 — a source-level column list; every value is bound.
            (indexed.path, chunk.part_index, chunk.start_line, chunk.end_line, chunk.text),
        )
        chunk_id = cursor.lastrowid
        if chunk_id is None:  # pragma: no cover — SQLite reports an id for every successful insert.
            raise ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.INDEX_WRITE)
        document = lexical.Document(text=chunk.text, path=indexed.path)
        await lexical.insert(db, chunk_id=chunk_id, document=document)
        await vectors.insert(db, chunk_id=chunk_id, vector=vector)
    await files.record(db, indexed)


async def forget_file(db: aiosqlite.Connection, *, path: str) -> None:
    """Remove one file from the index entirely: its chunks, both arms, and its `files` row.

    One function rather than two calls at each site, because "a chunk's path always names a row in
    `files`" is maintained by nobody else: a caller that removed the row and left the chunks would
    leave fragments pointing at a file the index no longer claims to hold, and nothing would raise.
    """
    await _clear(db, path)
    await files.forget(db, path)
