"""What `list` and `status` report about a knowledge base, and how each field is derived.

**`list` is `status` projected down**, never a parallel answer, and that is the claim this module
exists to keep true: there is one gathering step and two views of its result, rather than two
queries that agree today.

Both calls also have to answer for a knowledge base they cannot read, and the two ways that happens
are different answers rather than one. An **absent** database is reported as an empty corpus needing
a build, though a build cannot supply one — its definition went with the file, so the way back is to
remove the name and add it again. A **present** database that will not open is an error, which a
build does not obviously repair either, and which an operator has to look at. So absence is checked
before opening rather than inferred from a failed open, and a corpus in either state reports the
fields it still has and `None` for the rest — never zeros no stored value backs.

Field names map to `meta` keys by dropping the `skipped_` prefix. That is stated as a rule so the
difference is deliberate rather than drift.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote

import aiosqlite

from zikaron.core import clock
from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.errors import ZikaronError
from zikaron.core.knowledge import counters, database, lock, meta, paths, pending, registry, state
from zikaron.core.knowledge.registry import KnowledgeBase


def _reported_skip_name(key: str) -> str:
    """The `status` field one skip-reason `meta` key is reported under."""
    return key.removeprefix(counters.SKIP_PREFIX)


@dataclass(frozen=True, slots=True)
class Summary:
    """The fields a caller needs in order to *choose* a corpus — what `list` returns.

    `files_remaining` is `None` both when no build is running and when one has started but has not
    yet worked out what changed. Those are deliberately one value rather than two: `0` would read
    as *nothing left to do* when the truth is *not yet counted*, and that is the reading that
    makes a caller stop waiting.
    """

    name: str
    description: str
    state: state.KnowledgeState
    files_indexed: int
    files_remaining: int | None


@dataclass(frozen=True, slots=True)
class LockReport:
    """Who holds this corpus's build lock, and what this machine can establish about them.

    Reported because `state` alone cannot explain either of the two cases where lock rows outlive
    the build that wrote them. A lock recorded on **another machine** is never reclaimed here — a
    local process probe says nothing about a foreign one — so it reports `indexing` and persists
    until somebody clears it by hand, and the holder is what tells them which machine to look at.
    A **local** holder whose process is gone does *not* keep the corpus reported as mid-scan, which
    leaves nothing at all to say a detached build died: its output went nowhere, and the counters it
    left behind are indistinguishable from a build still climbing. `live: false` is that signal.

    `live` is `None` wherever the question cannot be answered from here — a foreign host, or a pid
    that is not a number. `age_seconds` is `None` when the recorded instant cannot be read as one,
    which only a hand-edited row produces.
    """

    pid: int | None
    host: str
    started_at: str
    age_seconds: float | None
    live: bool | None


@dataclass(frozen=True, slots=True)
class Details:
    """The diagnostic half of `status`: why a corpus is the way it is.

    A separate type from `Summary` because it has a separate availability. Every field here rests
    on the knowledge base's own database, so a knowledge base that has no readable database has
    none of them — which `Status.details` says by being `None` rather than by reporting zeros that
    no stored value backs.

    `git_mode_effective` is `None` until a build has recorded one. It is read from what the last
    build actually used rather than recomputed now, because the value that explains an indexed
    corpus is the one that shaped it, not whatever the environment happens to say today.
    """

    root_path: str
    git_mode: meta.GitMode
    git_mode_effective: meta.GitMode | None
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    max_file_bytes: int
    chunks: int
    bytes_indexed: int
    files_seen: int
    files_skipped: int
    skipped: Mapping[str, int]
    searches: int
    searches_empty: int
    results_returned: int
    results_stale: int
    last_scan_started_at: str | None
    last_scan_completed_at: str | None
    lock: LockReport | None


@dataclass(frozen=True, slots=True)
class Status:
    """Everything `list` returns, plus the diagnostic half when there is one to report.

    Composition rather than one wide dataclass, so "`list` is `status` projected down" is a fact
    about the types rather than a convention two constructors have to keep.
    """

    summary: Summary
    details: Details | None


@dataclass(frozen=True, slots=True)
class Orphan:
    """A knowledge-base database with no registry row.

    The residue of an interrupted `remove`. Reported, never opened for search, and never deleted
    on its own — an unreferenced database may hold a corpus somebody wants back after a botched
    removal, and that is worth more than the disk it occupies.

    `breadcrumb_name` is read from the file's own non-authoritative name copy, which is what that
    copy exists for. It is `None` when the file cannot be read, which is exactly when a human
    needs to be told the file is there rather than what it was called.
    """

    path: Path
    breadcrumb_name: str | None
    size_bytes: int


@dataclass(frozen=True, slots=True)
class Observed:
    """One corpus's report, plus the fact its report deliberately hides.

    `state` answers *can I trust results from this corpus*, and under its precedence a knowledge
    base that is both unbuilt and being built reports `reindex_required` — correctly, because the
    corpus still cannot be trusted. That makes the reported state the wrong thing to ask *is a
    writer holding this database*, which is a different question with a different consequence, so
    the answer travels alongside rather than being read back out of the state.

    `blocker` is the recorded holder that cannot be shown to be gone, and `None` covers both *no
    lock* and *a lock whose process this host can see has died*. The second is why it is not a
    plain presence flag: a crashed indexer leaves its rows behind by design, and treating those as
    a live writer would make one dead process enough to make a knowledge base unremovable forever.

    `unreadable_because` is the exception a database that would not open raised, kept rather than
    discarded so that a caller which must *refuse* over it — rather than merely report it — can
    say what actually went wrong instead of inventing a message for it. It is `None` whenever the
    state is anything but `error`, and it is the one piece of this report that is not for a
    reader: `status` already says the corpus cannot be opened, in the vocabulary a reader uses.
    """

    status: Status
    blocker: lock.LockHolder | None
    unreadable_because: Exception | None = None

    def __post_init__(self) -> None:
        """Hold the two halves of *unreadable* together, so a reader may use either.

        `state is error` and `unreadable_because is not None` are one fact recorded twice, and a
        caller that needs the exception — one that must raise rather than report — would otherwise
        have to guard against a combination this module never produces, which is a branch nothing
        can reach and no test can exercise. Stated as a constructor check instead: it is reachable,
        it is testable, and it makes the guarantee the thing callers rely on rather than a habit.
        """
        errored = self.status.summary.state is state.KnowledgeState.ERROR
        if errored != (self.unreadable_because is not None):
            message = (
                f"state {self.status.summary.state.value!r} and "
                f"unreadable_because={self.unreadable_because!r} disagree about whether this "
                f"knowledge base could be read"
            )
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Listing:
    """Every corpus a call was asked about, plus every database no registry row points at."""

    knowledge_bases: tuple[Status, ...]
    orphans: tuple[Orphan, ...]


def _counter(raw: Mapping[str, str], key: str) -> int:
    """One counter's value, treating anything unreadable as zero.

    Counters are seeded at creation, so a missing or malformed one means a database somebody
    edited by hand — and a diagnostic report is the wrong place to refuse over it. The identity
    keys, which decide whether a corpus can be served at all, are validated strictly instead.
    """
    try:
        return int(raw[key])
    except (KeyError, ValueError):
        return 0


def _git_mode_or_none(value: str | None) -> meta.GitMode | None:
    if value is None:
        return None
    try:
        return meta.GitMode(value)
    except ValueError:
        return None


def _lock_report(raw: Mapping[str, str]) -> LockReport | None:
    """The recorded holder with this machine's reading of it, or `None` if no lock is recorded."""
    holder = lock.read(raw)
    if holder is None:
        return None
    return LockReport(
        pid=holder.pid,
        host=holder.host,
        started_at=holder.started_at,
        age_seconds=clock.seconds_since(holder.started_at),
        live=lock.probe(holder, host=lock.this_host()),
    )


async def _chunk_count(db: aiosqlite.Connection) -> int:
    rows = await db.execute_fetchall("SELECT count(*) FROM chunks")
    ((found,),) = list(rows)
    return int(found)


async def files_remaining(db: aiosqlite.Connection, raw: Mapping[str, str]) -> int | None:
    """How many files a running build has left to dispose of, or `None` when that is not a number.

    The rule needs a persisted discriminator because the process answering this may not be the one
    building, and "walk finished, nothing changed" and "walk still running" are otherwise
    byte-identical states: an empty `pending` table either way, with nothing left in it to carry a
    timestamp. So the count is a number only when a build is running **and** the walk phase's own
    completion instant is at least as recent as that build's start.

    *Running* is the same test `state` uses, and it has to be: `None` is what tells a caller no
    build is in flight, so a count beside a state that says the same thing would be two answers to
    one question. A killed build's lock rows are therefore not a running build, and the number they
    would otherwise report — whatever the dead scan had left — would never move again.
    """
    if lock.running_holder(raw, host=lock.this_host()) is None:
        return None
    started = raw.get(meta.LAST_SCAN_STARTED_AT_KEY)
    walked = raw.get(meta.LAST_WALK_COMPLETED_AT_KEY)
    if started is None or walked is None or walked < started:
        return None
    return await pending.count(db)


async def gather(
    registered: KnowledgeBase,
    db: aiosqlite.Connection,
    current_meta: meta.KnowledgeMeta,
    raw: Mapping[str, str],
    *,
    corpus_state: state.KnowledgeState,
) -> Status:
    """Everything reportable about one open knowledge base.

    `name` and `description` come from the **registry**, never from the database's breadcrumb: the
    registry owns them, and a report preferring the copy would be authoritative about the wrong
    one of two values that are allowed to disagree.
    """
    return Status(
        summary=Summary(
            name=registered.name,
            description=registered.description,
            state=corpus_state,
            files_indexed=_counter(raw, "files_indexed"),
            files_remaining=await files_remaining(db, raw),
        ),
        details=Details(
            root_path=current_meta.root_path,
            git_mode=current_meta.git_mode,
            git_mode_effective=_git_mode_or_none(raw.get(meta.LAST_SCAN_GIT_MODE_EFFECTIVE_KEY)),
            include_globs=current_meta.include_globs,
            exclude_globs=current_meta.exclude_globs,
            max_file_bytes=current_meta.max_file_bytes,
            chunks=await _chunk_count(db),
            bytes_indexed=_counter(raw, "bytes_indexed"),
            files_seen=_counter(raw, "files_seen"),
            files_skipped=_counter(raw, "files_skipped"),
            skipped=MappingProxyType(
                {_reported_skip_name(key): _counter(raw, key) for key in meta.SKIP_REASON_KEYS}
            ),
            searches=_counter(raw, "searches"),
            searches_empty=_counter(raw, "searches_empty"),
            results_returned=_counter(raw, "results_returned"),
            results_stale=_counter(raw, "results_stale"),
            last_scan_started_at=raw.get(meta.LAST_SCAN_STARTED_AT_KEY),
            last_scan_completed_at=raw.get(meta.LAST_SCAN_COMPLETED_AT_KEY),
            lock=_lock_report(raw),
        ),
    )


def without_details(registered: KnowledgeBase, corpus_state: state.KnowledgeState) -> Status:
    """What to report for a knowledge base whose database is absent or could not be read.

    `files_indexed` is `0` because a corpus with no readable database has indexed nothing that can
    be served, which is a claim about availability rather than a guess at a stored number.
    Everything else the database would have supplied is absent rather than zeroed, so a caller is
    never handed a confident value that no stored one backs.
    """
    return Status(
        summary=Summary(
            name=registered.name,
            description=registered.description,
            state=corpus_state,
            files_indexed=0,
            files_remaining=None,
        ),
        details=None,
    )


async def observe(store_dir: Path, registered: KnowledgeBase, config: EffectiveConfig) -> Observed:
    """One corpus's whole report, including the case where there is no corpus to read."""
    db_path = paths.knowledge_db_path(store_dir, registered.id)
    if not db_path.is_file():
        absent = without_details(registered, state.KnowledgeState.REINDEX_REQUIRED)
        return Observed(status=absent, blocker=None)
    try:
        opened = await database.KnowledgeDatabase.open(store_dir, registered.id)
    except (aiosqlite.Error, ZikaronError, OSError) as error:
        broken = without_details(registered, state.KnowledgeState.ERROR)
        # No lock can be read out of a database that will not open, and reporting one anyway would
        # be a guess in the direction that stops a caller repairing it.
        return Observed(status=broken, blocker=None, unreadable_because=error)
    async with opened:
        raw = await database.read_meta(opened.connection)
        blocker = lock.running_holder(raw, host=lock.this_host())
        resolved = state.resolve(state.inputs_for_open(opened, raw, config))
        gathered = await gather(
            registered, opened.connection, opened.meta, raw, corpus_state=resolved
        )
    return Observed(status=gathered, blocker=blocker)


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


async def _orphans(store_dir: Path, registered: Sequence[KnowledgeBase]) -> tuple[Orphan, ...]:
    """Every database file in the knowledge directory that no registry row points at."""
    known = {paths.knowledge_db_path(store_dir, base.id) for base in registered}
    found: list[Orphan] = []
    for candidate in paths.orphan_candidates(store_dir):
        if candidate in known:
            continue
        size = candidate.stat().st_size if candidate.is_file() else 0
        found.append(
            Orphan(path=candidate, breadcrumb_name=await _breadcrumb(candidate), size_bytes=size)
        )
    return tuple(found)


async def list_bases(store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig) -> Listing:
    """Every registered corpus with its state, plus every database no registry row points at."""
    await registry.ensure(db)
    registered = await registry.list_all(db)
    reports = [(await observe(store_dir, base, config)).status for base in registered]
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
    await registry.ensure(db)
    registered = await registry.require(db, name)
    observed = await observe(store_dir, registered, config)
    return Listing(knowledge_bases=(observed.status,), orphans=())
