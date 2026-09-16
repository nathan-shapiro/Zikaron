"""The index phase: what becomes of each path the walk phase left pending, one transaction each.

A scan is two phases. The walk phase decides what the corpus *is* and writes the list of paths still
to be done; this is what works through that list. They are separate modules because they are
separate jobs with separate failure stories — one walks a filesystem and compares hashes, the other
reads, chunks, embeds and writes — and the pending table is the whole of what passes between them.

**Every pending path has exactly three disposals, and that is what makes the list emptiable**: the
file is indexable and is reindexed; it is not indexable and was indexed before, so it is deleted; or
it is not indexable and never was, so the skip is recorded and nothing else happens. One
**non**-disposal sits beside them: a file that could not be read keeps its row, because the work it
names has not been done and a search should go on saying so until a later walk decides otherwise.

**"Not indexable" is two refusals rather than one** — the file is no longer text, or it has grown
past the size cap since the walk measured it — and both are discovered by this phase's own bounded
read rather than by the walk. That is why they are disposed of here at all: a path the walk stops
admitting never reaches the pending list.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from zikaron.core.clock import timestamp
from zikaron.core.indexing.encoder import Encoder
from zikaron.core.knowledge import (
    candidates,
    changes,
    chunking,
    database,
    files,
    pending,
    text,
    vectors,
    writes,
)
from zikaron.core.knowledge.counters import ScanCounters, SkipReason
from zikaron.core.knowledge.meta import KnowledgeMeta
from zikaron.core.store.transactions import in_one_transaction, propagate


@dataclass(frozen=True, slots=True)
class BuildSettings:
    """What a build needs that the corpus's own `meta` does not record.

    The corpus defines itself — its root, globs, size cap, chunk budget and encoder identity all
    come from its stored `meta`, so that changing a global default cannot silently re-shape an index
    that is already built. These three are the exceptions, and they are exceptions for one reason:
    none of them describes the index that results. `encoder` is the artifact this process happened
    to load; `embed_batch` is how many chunks go into one forward pass, which a correct
    implementation's vectors do not depend on at all; and `full` decides which files are rewritten
    rather than what any of them becomes, so a full build and an incremental one leave the same
    rows behind.
    """

    encoder: Encoder
    embed_batch: int
    full: bool = False


@dataclass(frozen=True, slots=True)
class Disposals:
    """What every disposal needs and none of them varies.

    One value rather than five parameters threaded through each call: they are established once by
    the walk phase and read by every disposal, and passing them separately would let one call site
    supply a different size cap from the one the walk admitted files under.
    """

    root: Path
    answers: candidates.GitAnswers
    counters: ScanCounters
    corpus: KnowledgeMeta
    build: BuildSettings


async def write_counters(db: aiosqlite.Connection, counters: ScanCounters) -> None:
    """Flush the counters in a transaction of their own.

    For the one outcome that changes a count and nothing else: a file that could not be read. Every
    other disposal writes its counters inside the transaction that disposes of it, which is what
    keeps a reported count from describing work that was rolled back.
    """

    async def _work(connection: aiosqlite.Connection) -> None:
        await database.write_meta(connection, counters.as_meta_rows())

    await in_one_transaction(db, _work, failure=propagate)


async def _record_skip(
    db: aiosqlite.Connection, path: str, was_indexed: bool, counters: ScanCounters
) -> bool:
    """Dispose of a path this scan will not index: a deletion if it was indexed, else nothing.

    A path with no row serves nothing, so recording the skip and clearing the pending row is the
    whole of it. A path that *was* indexed has text in the index that no longer corresponds to
    anything indexable, and serving that forever behind a stale flag is worse than removing it.

    **The second case is narrow, and saying which ways it is reachable is worth more than the
    branch.** A previously indexed file is normally read during the walk, which is where it
    ceasing to be indexable is noticed and where it is deleted. It reaches here only when the walk
    could not settle it: its read **failed** there, or the file was indexable when the walk read it
    and had changed by the time this read ran — into something not text, or past the size cap. All
    are races against an edit, all are rare, and the alternative to handling them is an index entry
    for content that is no longer there.

    Returns whether a file was removed from the index.
    """

    async def _work(connection: aiosqlite.Connection) -> None:
        if was_indexed:
            await writes.forget_file(connection, path=path)
        await pending.dispose(connection, path)
        await database.write_meta(connection, counters.as_meta_rows())

    await in_one_transaction(db, _work, failure=propagate)
    return was_indexed


async def _record_indexed(
    db: aiosqlite.Connection, path: str, raw: bytes, decoded: str, context: Disposals
) -> None:
    """Chunk this file, embed its chunks, and write all of it in one transaction.

    The two expensive steps happen first and outside the transaction: chunking tokenizes the whole
    file, and embedding runs the model over every chunk. Holding the write lock across either would
    make a concurrent reader's wait a function of model speed, and nothing is staged until both have
    succeeded.

    **A failure in either propagates and ends the whole build**, leaving this file's index entry as
    it was and its pending row still naming it. That is deliberate rather than incidental: what can
    raise here is systemic — an unavailable model, a wrong number of vectors, a packing that broke
    its own budget — so the next file would fail the same way, and a build that swallowed it would
    write a completion instant over a corpus it had stopped indexing.

    The stored content hash is this read's rather than the walk phase's: it is the read whose bytes
    were indexed, so a file that changed between the two phases records what was indexed rather than
    what was noticed.
    """
    corpus = context.corpus
    plan = await asyncio.to_thread(
        chunking.plan_file_chunks,
        path=path,
        text=decoded,
        encoder=context.build.encoder,
        chunk_max_tokens=corpus.chunk_max_tokens,
    )
    embeddings = await vectors.embed_chunks(
        plan,
        encoder=context.build.encoder,
        embed_dim=corpus.embed_dim,
        batch_size=context.build.embed_batch,
    )
    indexed = files.IndexedFile(
        path=path,
        size=len(raw),
        content_hash=files.content_hash(raw),
        git_blob_hash=context.answers.listed.get(path),
        chunk_count=plan.n_chunks,
        indexed_at=timestamp(),
    )

    async def _work(connection: aiosqlite.Connection) -> None:
        await writes.index_file(connection, indexed=indexed, plan=plan, embeddings=embeddings)
        await pending.dispose(connection, path)
        await database.write_meta(connection, context.counters.as_meta_rows())

    await in_one_transaction(db, _work, failure=propagate)


async def dispose(
    db: aiosqlite.Connection, path: str, context: Disposals, *, was_indexed: bool
) -> bool:
    """Do whatever this pending path needs, in one transaction, and remove its row.

    The exception is a file that cannot be read: its row stays, because the work it names has not
    been done and a search should keep saying so until a later walk decides otherwise.

    Returns whether this path was removed from the index.
    """
    counters = context.counters
    raw = await asyncio.to_thread(
        files.read_bounded, context.root / path, context.corpus.max_file_bytes
    )
    if raw is SkipReason.UNREADABLE:
        counters.skip(SkipReason.UNREADABLE)
        await write_counters(db, counters)
        return False
    if isinstance(raw, SkipReason):
        counters.skip(raw)
        return await _record_skip(db, path, was_indexed, counters)
    detection = text.sniff(raw)
    if isinstance(detection, text.NotText):
        counters.skip(detection.reason)
        return await _record_skip(db, path, was_indexed, counters)
    counters.index(len(raw))
    await _record_indexed(db, path, raw, detection.text, context)
    return False


async def run(db: aiosqlite.Connection, comparison: changes.Comparison, context: Disposals) -> int:
    """Dispose of every pending path, reading the list from the table the walk phase wrote.

    Returns how many of them were removed from the index rather than written to it.
    """
    deleted = 0
    for path in await pending.paths(db):
        if await dispose(db, path, context, was_indexed=path in comparison.previously_indexed):
            deleted += 1
    return deleted
