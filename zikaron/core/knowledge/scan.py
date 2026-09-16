"""One build of one knowledge base's index, as two phases over one lock.

**The walk phase** establishes what the corpus *is*: it walks the root, asks git what changed,
reads and hashes the candidates git could not clear, deletes everything the walk no longer admits,
and then replaces the pending list wholesale with the paths still to be done. **The index phase**
then disposes of each of those paths, one transaction each, and lives in `disposal.py` — the pending
table is the whole of what passes between them, which is what makes them separable at all.

**Which phase performs a deletion follows from which phase discovered it.** The walk phase knows
the whole admitted set, so every indexed path it stops admitting — gone, over the cap, newly
excluded by a glob or an attribute, or failing the sniff on the walk's own hashing read — is
deleted there, and never enters the pending list, because there is nothing left for a later phase
to decide about it. The index phase's deletions are the ones only it can discover: a file its own
read refuses — no longer text, or past the size cap — and which was indexed before, either because
the walk's read of it failed or because the file changed again after that read.

That is what makes the pending list's three disposals exactly the three outcomes of reading one
pending file — it is indexable, it is not and was indexed before, it is not and never was — with
one **non**-disposal beside them: a file that could not be read keeps its row, so the staleness it
implies survives until a later walk replaces the list. **"Not indexable" is two refusals rather
than one**: the file is no longer text, or it has grown past the size cap since the walk measured
it. Both produce a recorded skip, and both delete the row where one exists.

**Indexing one file is chunking it, embedding those chunks, and writing all of it in one
transaction.** The first two are the expensive steps and both happen before the transaction opens,
so the write lock is never held across a model call.

**A chunking or embedding failure ends the build, rather than skipping that file**, and that is the
right shape for what can still raise there: the model is unavailable, or it answered with the wrong
number of vectors, or the packing violated its own budget. None of those is a fact about the file in
front of it, so continuing would mean the same failure on every file after it and a corpus reported
as built from whatever happened to precede the first one. Everything already committed stays
committed, the completion instant is not written, and the next build resumes from the `files` rows.
The one failure that *was* about a single file — a path too long to leave room for content — is
handled by the chunker rather than raised, precisely because it would otherwise trap a build on one
file forever.

**Nothing here is a checkpoint.** A build that dies leaves its committed files intact and its
pending rows naming what it never got to; the next build walks again, compares hashes, and does
whatever still does not match.

**Two things can make a build reindex a file the comparison would have cleared, and they are not
the same thing.** A caller may ask for change detection to be *bypassed*, which is the whole of
what a full build is — every other mechanic is unchanged, so the corpus is replaced a file at a
time rather than emptied first. And a build **rebuilds** a corpus whose stored vectors cannot be
what its own record says they are: `repair.py` drops the derived tables up front, because a new
vector width cannot be added to a table declared for the old one, which leaves every file changed
by definition without anybody declaring it so.

**What a rebuild answers to is `repair.rebuilt_identity`, asked on state read under this build's own
lock** — the encoder in hand against the recorded identity, and the table's declared width against
that same identity. Read before acquiring, the answer would be a snapshot a concurrent build could
have overtaken; `_begin` returns both so the decision and the work belong to one lock hold.

**Neither question reports an interrupted rebuild, and neither is meant to.** The drop records the
identity it is rebuilding to in the transaction that empties the tables, so a dead rebuild leaves
`meta` naming exactly what is stored and both comparisons quiet. What says a build is owed is the
completion instant the same transaction cleared. That separation is what lets the next scan be an
ordinary one **where the encoder in hand is still the one `meta` names**: the rows the dead run
committed came from that model, so clearing them as current is correct, and the remainder is indexed
with the same model — a resume, not a redo. A reverted configuration makes the recorded identity a
mismatch instead, and the first question fires, which redoes the corpus — correct for the same
reason, since those rows came from the model being abandoned.
"""

import asyncio
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import aiosqlite

from zikaron.core.clock import timestamp
from zikaron.core.knowledge import (
    candidates,
    changes,
    database,
    disposal,
    files,
    lock,
    meta,
    pending,
    repair,
    roots,
    walk,
    writes,
)
from zikaron.core.knowledge.counters import ScanCounters
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.disposal import BuildSettings, Disposals
from zikaron.core.knowledge.errors import CorpusRootMissingError
from zikaron.core.knowledge.meta import GitMode, KnowledgeMeta
from zikaron.core.store.transactions import in_one_transaction, propagate

#: How many walked entries are pulled per hop onto a worker thread. The walk is blocking work and
#: the event loop must not hold it, but a hop per entry would cost more in scheduling than the
#: entry costs to produce. It also sets how often the seen count reaches the database, which is
#: the only evidence a scan is progressing before it has worked out what changed.
_WALK_BATCH: Final = 500


@dataclass(frozen=True, slots=True)
class ScanResult:
    """What one build did, for whoever is waiting on it.

    `files_deleted` counts every path this build removed from the index, whichever phase decided
    it: one the walk stopped admitting, and one the index phase's own read refused.

    `files_remaining` is what the index phase could not dispose of — files it could not read — and
    is normally zero. Those rows are left deliberately: they are what keeps a search honest about
    results whose files this scan never confirmed.

    `rebuilt_identity` is the model and width this build wrote over the recorded ones, or `None`
    for the ordinary build that found them already agreeing. It is reported because a rebuild is
    otherwise invisible in the numbers: every file is reindexed and none is deleted, which is what
    an ordinary first build looks like too.
    """

    git_mode: GitMode
    git_mode_effective: GitMode
    attributes_available: bool
    files_deleted: int
    files_remaining: int
    counters: ScanCounters
    rebuilt_identity: KnowledgeMeta | None


def _take(walker: Iterator[walk.Candidate], count: int) -> list[walk.Candidate]:
    """Pull at most `count` entries from a walk in progress, on whichever thread calls this.

    Never called concurrently — each call is awaited before the next begins — so the walk advances
    on one thread at a time, even though not always the same one.
    """
    taken: list[walk.Candidate] = []
    for candidate in walker:
        taken.append(candidate)
        if len(taken) >= count:
            break
    return taken


async def _write_counters(
    db: aiosqlite.Connection, counters: ScanCounters, extra: Mapping[str, str] | None = None
) -> None:
    """Flush the counters, plus anything else this moment records, in one transaction."""

    async def _work(connection: aiosqlite.Connection) -> None:
        await database.write_meta(connection, {**counters.as_meta_rows(), **(extra or {})})

    await in_one_transaction(db, _work, failure=propagate)


async def _begin(
    db: aiosqlite.Connection, counters: ScanCounters, *, effective: GitMode
) -> tuple[KnowledgeMeta, int]:
    """Take the lock, open the scan, and read back the state the rebuild decision is taken on.

    The lock is read and written in one transaction, because in two of them both of two racing
    acquisitions could commit; one transaction lets at most one. The counters are zeroed here so
    that what a report shows always describes the scan in front of you rather than an accumulation.

    **The identity and the vector table's width are read here rather than at open, because the
    build that decides what to do with them must be the one holding the lock.** They are the only
    inputs a *concurrent* build can change — the root and the git mode are fixed at creation — and
    a build that read them before acquiring would be deciding on a snapshot another build could
    have overtaken: two spawns that overlap by the width of a directory check and a git subprocess
    are ordinary, and the loser would then index with its own encoder into a corpus the winner had
    just relabelled. Nothing would raise, because at equal widths every insert fits.

    **Two builds that begin at the very same moment can both read *no holder*, and only one of them
    commits** — which is the right outcome, reached the wrong way: the loser gets the driver's
    `database is locked` rather than the refusal this documents. It is reachable in ordinary use,
    since two spawns inside one model-load window both pass the check the command runs first.
    Closing it would mean a `BEGIN IMMEDIATE` variant of the shared transaction primitive, verified
    by a test that holds one acquisition's transaction open while the other attempts its own —
    bought for a better sentence in an outcome that is already correct, on a path whose output is
    discarded.

    Returns:
        The recorded identity and the width the vector table is declared at, both as of the moment
        the lock was taken.

    Raises:
        IndexerBusyError: another indexer holds the lock and cannot be shown to be dead. Nothing
            is written, and in particular the lock is untouched — which is why this runs outside
            whatever releases it.
    """
    started_at = timestamp()

    async def _work(connection: aiosqlite.Connection) -> tuple[KnowledgeMeta, int]:
        await lock.acquire(
            connection, pid=os.getpid(), host=lock.this_host(), started_at=started_at
        )
        await database.write_meta(
            connection,
            {
                meta.LAST_SCAN_STARTED_AT_KEY: started_at,
                meta.LAST_SCAN_GIT_MODE_EFFECTIVE_KEY: effective.value,
                **counters.as_meta_rows(),
            },
        )
        return meta.parse_and_validate(await database.read_meta(connection)), (
            await database.stored_vector_width(connection)
        )

    return await in_one_transaction(db, _work, failure=propagate)


async def _walk_tree(
    db: aiosqlite.Connection, root: Path, counters: ScanCounters
) -> list[walk.Candidate]:
    """Every file the directory-level rules admit, with the seen count kept current as it goes."""
    walker = walk.entries(root, counters)
    found: list[walk.Candidate] = []
    while batch := await asyncio.to_thread(_take, walker, _WALK_BATCH):
        found.extend(batch)
        await _write_counters(db, counters)
    return found


async def _delete(db: aiosqlite.Connection, path: str, counters: ScanCounters) -> None:
    """Remove one path from the index, together with any pending row naming it."""

    async def _work(connection: aiosqlite.Connection) -> None:
        await writes.forget_file(connection, path=path)
        await pending.dispose(connection, path)
        await database.write_meta(connection, counters.as_meta_rows())

    await in_one_transaction(db, _work, failure=propagate)


async def _close_walk_phase(
    db: aiosqlite.Connection,
    comparison: changes.Comparison,
    counters: ScanCounters,
    effective: GitMode,
) -> None:
    """Replace the pending list wholesale and record that the walk phase finished.

    Replaced rather than appended to, so a file edited and then reverted between two scans loses
    its row instead of being flagged stale forever. The completion instant is written in the same
    transaction because it is what tells a reader in another process that an empty pending list
    means *nothing left to do* rather than *not yet counted* — two states that are otherwise
    byte-identical.

    Every file this scan cleared as unchanged is counted as indexed here, which is what makes the
    indexed count the size of the corpus rather than the size of this scan's workload: a rescan
    that finds nothing changed must not report an empty corpus.
    """
    completed_at = timestamp()
    for row in comparison.unchanged:
        counters.index(row.size)

    async def _work(connection: aiosqlite.Connection) -> None:
        await pending.replace_all(connection, comparison.changed, noticed_at=completed_at)
        for path, blob_hash in comparison.blob_hash_refreshes.items():
            await files.record_git_blob_hash(connection, path, blob_hash)
        await database.write_meta(
            connection,
            {
                meta.LAST_WALK_COMPLETED_AT_KEY: completed_at,
                meta.LAST_SCAN_GIT_MODE_EFFECTIVE_KEY: effective.value,
                **counters.as_meta_rows(),
            },
        )

    await in_one_transaction(db, _work, failure=propagate)


@dataclass(frozen=True, slots=True)
class _WalkInputs:
    """What the walk phase works from and none of its steps varies.

    One value rather than five parameters threaded through the phase, for the reason the index
    phase's equivalent gives: they are settled once by `run` and read by every step, and passing
    them separately would let one step judge candidates by a different corpus from the next.

    `corpus` is the identity this build is working **to**, which for a rebuild is the new encoder's
    rather than the one still recorded in `meta`.
    """

    root: Path
    corpus: KnowledgeMeta
    counters: ScanCounters
    probed: GitMode
    bypass: bool


async def _walk_phase(
    db: aiosqlite.Connection, inputs: _WalkInputs
) -> tuple[candidates.GitAnswers, changes.Comparison, int]:
    """Decide what the corpus contains, delete what it no longer does, and list what is left to do.

    Returns git's answers, the comparison the index phase works from, and how many files were
    deleted.
    """
    root, corpus, counters = inputs.root, inputs.corpus, inputs.counters
    found = await _walk_tree(db, root, counters)
    answers = await candidates.gather(root, inputs.probed, found)
    rules = walk.WalkRules(
        include_globs=corpus.include_globs,
        exclude_globs=corpus.exclude_globs,
        max_file_bytes=corpus.max_file_bytes,
    )
    admitted = walk.admitted(found, ignored=answers.ignored, rules=rules, counters=counters)
    admitted = await candidates.narrow(root, admitted, answers, counters)
    indexed = await files.load_all(db)
    comparison = await asyncio.to_thread(
        changes.compare,
        admitted,
        indexed,
        changes.Criteria(
            answers=answers,
            counters=counters,
            max_file_bytes=corpus.max_file_bytes,
            bypass=inputs.bypass,
        ),
    )
    still_admitted = {candidate.path for candidate in admitted} - comparison.no_longer_admitted
    deletions = sorted(set(indexed) - still_admitted)
    for path in deletions:
        await _delete(db, path, counters)
    await _close_walk_phase(db, comparison, counters, answers.effective)
    return answers, comparison, len(deletions)


async def _complete(db: aiosqlite.Connection) -> None:
    """Record that this scan finished.

    Written only on success, because its absence — or an instant older than the scan's start — is
    how a crashed build is told from a completed one, and a build that claimed a completion it did
    not reach would report a corpus as trustworthy on the strength of a partial index.

    **This is the only key a rebuild leaves for the end**, and it is the one that has to be: the
    encoder identity is recorded by the drop, in the transaction that empties the tables, so `meta`
    describes what is stored throughout. This key describes something else — whether a *completed*
    build's corpus is what is stored — and only a scan that reached here can say yes. Between the
    two, an interrupted rebuild leaves a knowledge base that refuses to serve while naming, exactly,
    the model whose vectors are in it.

    Args:
        db: the knowledge base's own connection, outside a transaction.
    """

    async def _work(connection: aiosqlite.Connection) -> None:
        await database.write_meta(connection, {meta.LAST_SCAN_COMPLETED_AT_KEY: timestamp()})

    await in_one_transaction(db, _work, failure=propagate)


async def _release(db: aiosqlite.Connection) -> None:
    async def _work(connection: aiosqlite.Connection) -> None:
        await lock.release(connection)

    await in_one_transaction(db, _work, failure=propagate)


async def run(opened: KnowledgeDatabase, build: BuildSettings) -> ScanResult:
    """Build this knowledge base's index, holding its lock for as long as it takes.

    Args:
        opened: the knowledge base to build, already open. Its `meta` is what defines the corpus —
            the root, the globs, the size cap, the chunk budget, the encoder identity and the git
            mode all come from there rather than from configuration, so that changing a global
            default cannot silently re-shape an index that is already built.
        build: the artifact this process loaded, how many chunks to embed per pass, and whether
            every admitted file is to be reindexed rather than only what changed. A rebuild forced
            by a changed encoder asks for none of that — dropping the derived tables leaves every
            file changed on its own terms — so the two compose without either knowing about the
            other.

    Raises:
        CorpusRootMissingError: the indexed directory is gone. The index is left exactly as it is;
            an empty walk would read as *every file was deleted*.
        IndexerBusyError: another indexer holds this knowledge base's lock and cannot be shown to
            be dead. Nothing is written, and the lock is not released on the way out — it belongs
            to whoever holds it.
    """
    db = opened.connection
    # The root and the git mode are settled when a knowledge base is created and nothing rewrites
    # them, so the two checks that need a subprocess or a filesystem call are made here, before the
    # lock, where a refusal costs nobody the lock.
    root = Path(opened.meta.root_path)
    if not root.is_dir():
        raise CorpusRootMissingError(roots.missing_root_message(root))
    counters = ScanCounters()
    probed = await roots.effective_git_mode(root, opened.meta.git_mode)
    # Outside the block below, and it must be: a refused acquisition means somebody else holds the
    # lock, and releasing on the way out would take it away from them.
    recorded, stored_width = await _begin(db, counters, effective=probed)
    try:
        # The identity `meta` records, and the one this build rebuilds it to. They differ only when
        # the encoder in hand is not the one the stored vectors were made with, and everything
        # downstream — the width a vector is checked against, the width the table is declared at —
        # has to be the second, since that is what will be in the table.
        rebuilt = repair.rebuilt_identity(recorded, build.encoder, stored_width=stored_width)
        corpus = rebuilt if rebuilt is not None else recorded
        if rebuilt is not None:
            await repair.drop_derived(db, identity=rebuilt)
        answers, comparison, deleted = await _walk_phase(
            db,
            _WalkInputs(
                root=root,
                corpus=corpus,
                counters=counters,
                probed=probed,
                bypass=build.full,
            ),
        )
        deleted += await disposal.run(
            db,
            comparison,
            Disposals(root=root, answers=answers, counters=counters, corpus=corpus, build=build),
        )
        remaining = await pending.count(db)
        await _complete(db)
    finally:
        await _release(db)
    return ScanResult(
        git_mode=corpus.git_mode,
        git_mode_effective=answers.effective,
        attributes_available=answers.attributes_available,
        files_deleted=deleted,
        files_remaining=remaining,
        counters=counters,
        rebuilt_identity=rebuilt,
    )
