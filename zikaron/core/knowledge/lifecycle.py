"""The five knowledge-base verbs: add, list, remove, rename, status.

**The registry is always mutated first**, for both `add` and `remove` — the same ordering, not
mirrored ones. The rule is to leave the recoverable state where one exists and the lesser harm
where none does, and the two interruptions are not symmetric, so one ordering satisfies both:

- An interrupted `add` leaves a **row without a file**: a dangling name, reported as
  `reindex_required`, cleared by `remove` and re-created by `add`. Nothing is lost, because
  nothing was ever indexed under it. A build cannot repair it — everything defining a corpus but
  its name and description lives in the database that is missing — so a build refuses instead.
- An interrupted `remove` leaves a **file without a row**: an orphan, invisible to every query,
  never opened, reported by `status`. It leaks disk until someone clears it, which is the lesser
  harm.

The reverse ordering is worse in both directions. An `add` writing its row last would leave an
orphan on interruption, and because a retried `add` mints a fresh id that orphan is *permanent*,
where the dangling name it avoids costs one `remove`. A `remove` unlinking first would leave a
name for a corpus the caller had just asked to destroy, still answering as a knowledge base that
merely needs a build.

**Those two are the states this code produces, not the only two physically reachable, and the
difference is worth stating because an exhaustive-sounding list is how the third one gets
overlooked.** Creating a knowledge base's database is itself several steps — the file comes into
existence when it is connected to, before any table is in it — so a failure in between would leave
a registered name pointing at an empty database, which reads back as *this index cannot be opened*
rather than as one needing a build. Creation removes what it made on **every failure it can catch**,
from the connect onwards, which folds those into the first state above. What remains is a **hard
kill inside that window**, which no in-process handler can catch: it leaves a row and an empty file,
reported as an unreadable index. Rarer than the two above, repaired by deleting the file, and named
here rather than left for somebody to meet without warning.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import aiosqlite

from zikaron.core.clock import timestamp
from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.errors import ZikaronError
from zikaron.core.knowledge import (
    database,
    lock,
    meta,
    paths,
    registry,
    reporting,
    roots,
    scan,
    state,
)
from zikaron.core.knowledge.errors import DanglingKnowledgeBaseError, IndexerBusyError
from zikaron.core.knowledge.registry import KnowledgeBase
from zikaron.core.store import permissions
from zikaron.core.store.transactions import in_one_transaction, propagate


@dataclass(frozen=True, slots=True)
class Observed:
    """One corpus's report, plus the fact its report deliberately hides.

    `state` answers *can I trust results from this corpus*, and under its precedence a knowledge
    base that is both unbuilt and being built reports `reindex_required` — correctly, because the
    corpus still cannot be trusted. That makes the reported state the wrong thing to ask *is a
    writer holding this database*, which is a different question with a different consequence, so
    the answer travels alongside rather than being read back out of the state.
    """

    status: reporting.Status
    lock_held: bool


@dataclass(frozen=True, slots=True)
class AddRequest:
    """A request to create a corpus, exactly as its caller stated it.

    One type rather than a long parameter list, because two surfaces construct exactly this — a
    command's parsed arguments and a tool call's validated payload — and a parameter list would
    let the two drift into accepting different things. Nothing here is validated yet: `add` does
    that, so neither surface can skip a check by being written second.

    `home` is a parameter rather than a lookup so a test states the home directory it is checking
    instead of mutating the process's. `None` means this process's own.
    """

    name: str
    root: Path
    description: str
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    git_mode: meta.GitMode = meta.GitMode.TRACKED
    max_file_bytes: int | None = None
    home: Path | None = None


@dataclass(frozen=True, slots=True)
class Created:
    """What `add` did, and what the caller should expect next.

    `git_mode_effective` comes from `add`'s own probe rather than from any stored key: the stored
    one is written by a build, which has not run yet, and a caller learning at creation time that
    its `git_mode` will not take effect is the whole point of probing at all.
    """

    knowledge_base: KnowledgeBase
    database_path: Path
    git_mode: meta.GitMode
    git_mode_effective: meta.GitMode
    status: reporting.Status


@dataclass(frozen=True, slots=True)
class Refreshed:
    """What one build did, and where it left the corpus.

    Both halves, because they answer different questions: the result says what this build changed,
    and the status says whether the corpus can now be trusted — which a build can leave unchanged,
    for instance when the encoder it was configured with has moved on since the index was made.
    """

    knowledge_base: KnowledgeBase
    result: scan.ScanResult
    status: reporting.Status


@dataclass(frozen=True, slots=True)
class Removed:
    """What `remove` destroyed — a final snapshot, since its corpus no longer exists to poll."""

    knowledge_base: KnowledgeBase
    status: reporting.Status
    files_unlinked: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class Listing:
    """Every corpus a call was asked about, plus every database no registry row points at."""

    knowledge_bases: tuple[reporting.Status, ...]
    orphans: tuple[reporting.Orphan, ...]


async def ensure_registry(db: aiosqlite.Connection) -> None:
    """Make sure `memory.db` carries the registry table, creating it on first use.

    The only creation site, and idempotent, which is what lets a store predating the table open
    and answer normally with nothing about the memory path changed. Wrapped in an explicit
    transaction because a bare `CREATE` with none open runs in autocommit, which would leave the
    table behind after a later statement in the same logical operation failed and rolled back.
    """
    await in_one_transaction(db, registry.ensure_table, failure=propagate)


async def _observe(store_dir: Path, registered: KnowledgeBase, config: EffectiveConfig) -> Observed:
    """One corpus's whole report, including the case where there is no corpus to read.

    Absence is checked before opening rather than inferred from a failed open, because the two
    outcomes are genuinely different answers: an absent database reads as an empty knowledge base,
    and a present one that will not open is an `error` a build does not obviously repair.
    """
    db_path = paths.knowledge_db_path(store_dir, registered.id)
    if not db_path.is_file():
        absent = reporting.without_details(registered, state.KnowledgeState.REINDEX_REQUIRED)
        return Observed(status=absent, lock_held=False)
    try:
        opened = await database.KnowledgeDatabase.open(store_dir, registered.id)
    except (aiosqlite.Error, ZikaronError, OSError):
        broken = reporting.without_details(registered, state.KnowledgeState.ERROR)
        return Observed(status=broken, lock_held=False)
    async with opened:
        raw = await database.read_meta(opened.connection)
        lock_held = lock.is_held(raw)
        resolved = state.resolve(
            state.StateInputs(
                unreadable=False,
                database_absent=False,
                root_missing=not Path(opened.meta.root_path).is_dir(),
                encoder_mismatch=not database.encoder_matches_config(opened.meta, config),
                never_built=state.never_built(raw),
                indexing=lock_held,
            )
        )
        gathered = await reporting.gather(
            registered, opened.connection, opened.meta, raw, corpus_state=resolved
        )
    return Observed(status=gathered, lock_held=lock_held)


async def _breadcrumb(db_path: Path) -> str | None:
    """An orphan's own record of what it was called, or `None` if it will not give one up.

    This is the one place an unreferenced database is opened at all, and it is for a human's
    benefit rather than for a query's: the alternative is reporting a uuid and leaving somebody to
    open the file by hand to find out what they lost.

    **Deliberately not through the shared opener, because that opener's job is the opposite of what
    is wanted here.** It establishes a *working* connection to a database we own, which means
    applying `journal_mode = WAL` — a persistent header write. Measured: run against a database in
    the default rollback journal, it converts the file to WAL. Every orphan this project made is
    already in WAL so nothing would usually be observed, but the promise made about an orphan is
    that it is reported and otherwise left alone, and a file that is *not* ours is exactly the one
    that might not be in WAL.

    Two things keep that promise, and it is worth saying which does the work. **Applying no pragmas
    is what makes the read harmless today** — a plain connect writes nothing, whatever mode it asks
    for. **`mode=ro` is the tripwire for tomorrow**: measured, a `journal_mode = WAL` issued on a
    read-only connection raises `attempt to write a readonly database` and leaves the file alone,
    so an edit that later adds a pragma loop here fails loudly instead of quietly converting
    somebody else's database. Reading `meta` needs neither, since it is an ordinary table and the
    vector extension is not loaded.
    """
    uri = f"file:{quote(str(db_path))}?mode=ro"
    try:
        db = await aiosqlite.connect(uri, uri=True)
    except (aiosqlite.Error, OSError):
        return None
    try:
        raw = await database.read_meta(db)
    finally:
        await db.close()
    return raw.get(meta.NAME_BREADCRUMB_KEY)


async def _orphans(
    store_dir: Path, registered: Sequence[KnowledgeBase]
) -> tuple[reporting.Orphan, ...]:
    """Every database file in the knowledge directory that no registry row points at."""
    known = {paths.knowledge_db_path(store_dir, base.id) for base in registered}
    found: list[reporting.Orphan] = []
    for candidate in paths.orphan_candidates(store_dir):
        if candidate in known:
            continue
        size = candidate.stat().st_size if candidate.is_file() else 0
        found.append(
            reporting.Orphan(
                path=candidate, breadcrumb_name=await _breadcrumb(candidate), size_bytes=size
            )
        )
    return tuple(found)


async def add(
    store_dir: Path,
    db: aiosqlite.Connection,
    config: EffectiveConfig,
    request: AddRequest,
) -> Created:
    """Register a corpus and create its database, in that order.

    Every per-knowledge-base setting is persisted at creation, `max_file_bytes` included. A
    setting accepted and not persisted would be silently undone by the next build, which would
    re-walk under the global default and change the corpus the caller had just defined.

    A successful `add` reports `reindex_required`, and that is the truth rather than a wart: the
    database exists and its `meta` is sound, but no build has completed, so the honest answer to
    *can I trust results from this corpus* is not yet.

    Args:
        store_dir: the `.zikaron` directory this store lives in.
        db: an open connection to `memory.db`, which carries the registry.
        config: the effective configuration to seed this corpus's tuning keys from.
        request: what to create, as supplied. Validated here rather than by the caller, so the
            command and the tool surface cannot come to accept different things.

    Raises:
        InvalidNameError: the name is empty or blank.
        InvalidRootError: the root is absent, is not a directory, or is degenerate.
        DuplicateNameError: the name is taken. Never an upsert — silently reconfiguring a corpus
            underneath whoever created it is worse than a failed call.
        ZikaronError: `BAD_CONFIG` if `max_file_bytes` is out of range.
    """
    home = request.home if request.home is not None else Path.home()
    resolved_root = roots.validate_root(request.root, home=home)
    stored_name = registry.normalize_name(request.name)
    if request.max_file_bytes is not None:
        meta.check_bounded(meta.MAX_FILE_BYTES_KEY, request.max_file_bytes)
    effective = await roots.effective_git_mode(resolved_root, request.git_mode)

    async def _register(connection: aiosqlite.Connection) -> KnowledgeBase:
        await registry.ensure_table(connection)
        return await registry.insert(
            connection,
            name=stored_name,
            description=request.description,
            created_at=timestamp(),
        )

    registered = await in_one_transaction(db, _register, failure=propagate)

    spec = database.NewKnowledgeBase(
        name=registered.name,
        root=resolved_root,
        description=request.description,
        include_globs=request.include_globs,
        exclude_globs=request.exclude_globs,
        git_mode=request.git_mode,
        max_file_bytes=request.max_file_bytes,
    )
    async with await database.KnowledgeDatabase.create(
        store_dir, database.seed_identity(registered.id, spec, config)
    ):
        pass

    observed = await _observe(store_dir, registered, config)
    return Created(
        knowledge_base=registered,
        database_path=paths.knowledge_db_path(store_dir, registered.id),
        git_mode=request.git_mode,
        git_mode_effective=effective,
        status=observed.status,
    )


async def rename(
    store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig, *, name: str, new_name: str
) -> reporting.Status:
    """Change a corpus's name. A registry `UPDATE` that touches no file.

    Safe while a build is running, and deliberately does not check the lock: the name lives in the
    registry alone, so nothing about a rename can disturb a database being written.

    Raises:
        InvalidNameError: either name is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`.
        DuplicateNameError: `new_name` is taken.
    """

    async def _work(connection: aiosqlite.Connection) -> KnowledgeBase:
        await registry.ensure_table(connection)
        return await registry.rename(connection, name=name, new_name=new_name)

    renamed = await in_one_transaction(db, _work, failure=propagate)
    observed = await _observe(store_dir, renamed, config)
    return observed.status


async def refresh(
    store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig, *, name: str
) -> Refreshed:
    """Build one corpus's index, and report what the build did and where it left the corpus.

    Runs the build to completion before returning, and holds the corpus's own lock for the whole
    of it, so two of these against one knowledge base do not overlap whichever process they run
    in.

    Args:
        store_dir: the `.zikaron` directory this store lives in.
        db: an open connection to `memory.db`, which carries the registry.
        config: the effective configuration, used only to report whether the built corpus's
            encoder identity still agrees with it. The corpus itself is defined entirely by its
            own stored `meta`.
        name: which corpus to build.

    Raises:
        InvalidNameError: `name` is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`.
        DanglingKnowledgeBaseError: the corpus is registered but its database is gone, and with it
            everything that said what to index.
        CorpusRootMissingError: the indexed directory is gone. The index is left as it is.
        IndexerBusyError: another build holds this corpus's lock.
    """
    await ensure_registry(db)
    registered = await registry.require(db, name)
    db_path = paths.knowledge_db_path(store_dir, registered.id)
    if not db_path.is_file():
        raise DanglingKnowledgeBaseError(
            f"{registered.name!r} has no database, so nothing records what it indexes; "
            f"remove it and add it again"
        )
    async with await database.KnowledgeDatabase.open(store_dir, registered.id) as opened:
        result = await scan.run(opened)
    observed = await _observe(store_dir, registered, config)
    return Refreshed(knowledge_base=registered, result=result, status=observed.status)


async def remove(
    store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig, *, name: str
) -> Removed:
    """Destroy a corpus: delete its registry row, commit, then unlink its three files.

    Refuses while the knowledge base's lock keys are present. Whether a present lock is *live* is
    a question the lock's owner answers; refusing on presence is deliberately the conservative
    half, because refusing to unlink a database a writer may hold is recoverable and unlinking one
    it does hold is not.

    **That refusal is a check followed by an act, not one atomic step, and the window is accepted
    rather than overlooked.** The lock lives in the knowledge base's own database and the registry
    row lives in `memory.db`, so no single transaction spans them: a build that takes the lock
    after the check has its database unlinked underneath it. The harm is bounded — the racing
    build's writes land on an unlinked inode and evaporate, which is what destroying the corpus was
    asked for — and closing it properly would mean a lock somewhere both databases can see, which
    is a larger change than the outcome justifies.

    Unlinks all three of the `.db`, its `-wal` and its `-shm`, because in WAL mode a live database
    is three files and a journal left behind would be inherited by whatever is created at that path
    next. In practice it usually removes one: reading the corpus's state opens and closes it, and
    SQLite reclaims its own `-wal` and `-shm` on the last close, so the other two are typically
    already gone by the time this runs. `files_unlinked` reports what was actually there rather
    than what was attempted, which is why it is normally a single path.

    Raises:
        InvalidNameError: `name` is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`.
        IndexerBusyError: a build holds this knowledge base's lock.
    """
    await ensure_registry(db)
    registered = await registry.require(db, name)
    observed = await _observe(store_dir, registered, config)
    if observed.lock_held:
        raise IndexerBusyError(
            f"a build is running against {registered.name!r}; retry once it has finished"
        )

    async def _work(connection: aiosqlite.Connection) -> KnowledgeBase:
        return await registry.delete(connection, name=name)

    await in_one_transaction(db, _work, failure=propagate)

    db_path = paths.knowledge_db_path(store_dir, registered.id)
    unlinked = [
        path
        for path in permissions.database_files(db_path)
        if await asyncio.to_thread(_unlink_if_present, path)
    ]
    return Removed(
        knowledge_base=registered, status=observed.status, files_unlinked=tuple(unlinked)
    )


def _unlink_if_present(path: Path) -> bool:
    """Remove `path`, reporting whether it was there.

    Absence is an ordinary outcome rather than a fault: a knowledge base that was never built has
    no `-wal` or `-shm`, and one whose file was deleted by hand has none of the three.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


async def list_bases(store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig) -> Listing:
    """Every registered corpus with its state, plus every database no registry row points at."""
    await ensure_registry(db)
    registered = await registry.list_all(db)
    reports = [(await _observe(store_dir, base, config)).status for base in registered]
    return Listing(knowledge_bases=tuple(reports), orphans=await _orphans(store_dir, registered))


async def status(
    store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig, *, name: str | None = None
) -> Listing:
    """One corpus's full report, or every corpus's.

    The same gathering as `list_bases` — `list` is this projected down, never a second query — so
    naming one knowledge base narrows the result rather than changing what is read.

    Orphans are reported only when no name was given: an orphan belongs to no knowledge base, so
    attaching it to a report about one would be attaching it arbitrarily.

    Raises:
        InvalidNameError: `name` is empty or blank.
        UnknownKnowledgeBaseError: `name` names nothing.
    """
    if name is None:
        return await list_bases(store_dir, db, config)
    await ensure_registry(db)
    registered = await registry.require(db, name)
    observed = await _observe(store_dir, registered, config)
    return Listing(knowledge_bases=(observed.status,), orphans=())
