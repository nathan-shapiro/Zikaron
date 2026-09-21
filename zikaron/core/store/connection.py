"""How Zikaron opens a SQLite database, for every database it owns.

Two live today — the memory store and one file per knowledge base — and they differ in their
schemas, not in how a connection is established: both need `sqlite-vec` loaded, both need their own
pragmas applied, and both need a failure between connecting and finishing that setup to close the
connection rather than abandon it. Keeping one implementation is what stops the second database
growing a subtly different opener; the alternative was already measured to be expensive in this
project, where an unclosed `aiosqlite` connection keeps its process alive with nothing printed.

**Two things vary between callers, and both are parameters rather than assumptions.**

- **How a failed *connect* is named** — the same split `transactions.FailureMap` makes, for the same
  reason. A memory store that will not open is a configuration error naming the store directory; a
  knowledge-base database that will not open is a reportable state of one corpus, and not an error
  at all when the file is simply absent.
- **Which pragmas to apply.** The two schemas do not want the same set, and the difference is
  load-bearing rather than cosmetic: the knowledge schema declares no foreign key anywhere, so
  `PRAGMA foreign_keys = ON` there would advertise a cascade that does not exist — which is the
  precise wrong mental model its design spends a paragraph refusing. The set is therefore supplied
  by whoever owns the schema, and there is deliberately **no default**: a caller that did not say
  would get whichever set this module happened to import, which is exactly how a connection came to
  carry a pragma its own design forbids.

Everything *after* the connect — the extension, the pragmas — raises the driver's own error for
every caller, because a database that opened and then refused a pragma is the same fault whoever
asked for it.
"""

import asyncio
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final
from urllib.parse import quote

import aiosqlite
import sqlite_vec

#: How a caller names a failed connect. Takes the driver's error and returns the exception to
#: raise in its place, with the original kept as the cause.
type ConnectFailure = Callable[[aiosqlite.Error], Exception]


#: How long to wait for the worker thread of a *failed* connect to finish. It is draining a single
#: queued sentinel, which takes microseconds; this bound exists so a wedged thread cannot hang a
#: caller rather than as a duration anything is expected to spend.
_ABANDONED_WORKER_JOIN_SECONDS: Final = 5.0


async def join_abandoned_worker(connector: aiosqlite.Connection) -> None:
    """Wait for the worker thread of a connect that failed, so it cannot outlive this event loop.

    **Why this is needed, reproduced before it was written.** `aiosqlite.connect()` starts a worker
    thread, and a failed connect leaves it mid-shutdown: the library's own failure path calls
    `stop()`, which *queues* a sentinel and returns without waiting. If the event loop closes before
    the thread drains that sentinel — which is exactly what happens when a caller catches the error
    and returns, the situation every caller of this function is in — the thread tries to deliver the
    sentinel's result through `call_soon_threadsafe` on a dead loop, raises `RuntimeError: Event
    loop is closed`, fails identically while trying to report that, and dies with the exception
    unhandled. A test run surfaces it as `PytestUnhandledThreadExceptionWarning`.

    **What that loses is the thread, and nothing else.** A connect that *failed* never produced a
    `sqlite3.Connection` for anybody to drop — the driver raised instead of returning one, and the
    stop the library queues behind it therefore finds no handle to close either. So this path
    cannot leave a database open, and an `unclosed database` warning seen near it has a different
    cause. *Superseded, in place: this docstring previously said the dropped connection "surfaces
    separately as `ResourceWarning: unclosed database`", and the surrounding record called it one
    bug with two symptoms. It is one symptom; the warnings counted alongside it came from raw
    `sqlite3` connections in test helpers and were fixed separately.*

    The number this is worth is in `test_store_connection.py`, which keeps the measurement as a
    test because nothing else in the gate can tell the two states apart: coverage sees both
    branches execute either way, and the matrix's warning filter errors only on deprecations.

    The join runs off the event loop, so a thread that never exits costs this bound rather than
    blocking the loop. `_thread` is private, and deliberately so — the library exposes no other way
    to wait for a worker it has already told to stop, and `stop()`'s own return value is a future on
    the loop that is about to close, which is the thing that cannot be relied on here.

    **Absence is tolerated for a substitute only, and the type is what draws that line.** A test
    that replaces `aiosqlite.connect` gets a plain coroutine with no worker behind it, and there is
    genuinely nothing to wait for; the first version of this assumed the attribute and broke such a
    test, which is how the tolerance was arrived at. A real `aiosqlite.Connection` that stopped
    keeping its thread here is the opposite case — the wait would quietly become a no-op and the
    defect would come back with nothing to announce it — so the check is on the type rather than on
    mere presence, and `test_store_connection.py` pins the attribute against the installed library
    so a version that moves it turns the matrix red instead of disabling this.
    """
    worker = getattr(connector, "_thread", None)
    if not isinstance(worker, threading.Thread):
        return
    await asyncio.to_thread(worker.join, _ABANDONED_WORKER_JOIN_SECONDS)


async def _load_sqlite_vec(db: aiosqlite.Connection) -> None:
    """Load the `sqlite-vec` extension on this connection, through `aiosqlite`'s own method.

    `aiosqlite.Connection.load_extension` is the sanctioned path: the wrapped `sqlite3`
    connection lives on `aiosqlite`'s own dedicated worker thread, so reaching into it directly
    to call `sqlite_vec.load()` raises from the caller's thread instead.
    """
    await db.enable_load_extension(True)
    try:
        await db.load_extension(sqlite_vec.loadable_path())
    finally:
        await db.enable_load_extension(False)


async def open_connection(
    db_path: Path,
    *,
    pragmas: Sequence[str],
    existing_only: bool = False,
    connect_failure: ConnectFailure | None = None,
) -> tuple[aiosqlite.Connection, int]:
    """Open `db_path` through `aiosqlite`, with the extension loaded and `pragmas` applied.

    Returns the connection **and** the inode `db_path` resolved to at the moment this call's own
    `aiosqlite.connect()` returned — needed so a caller can hand it onward to whatever later needs
    to detect this exact file being replaced out from under an already-open connection
    (`zikaron.service.lifecycle`'s inode-drift self-stop).

    Never bare `sqlite3`: a handler that called it directly could hold the single-threaded event
    loop for as long as SQLite's own `busy_timeout` retries, which is a genuine, previously
    reproduced self-inflicted deadlock rather than a style concern. `aiosqlite` closes that
    structurally by running the connection on its own thread.

    A failure loading the extension or applying a pragma closes the connection before
    propagating: `aiosqlite.connect` succeeding is not this function succeeding, and a caller
    that only wraps its *own* work in `try`/`except` would otherwise be handed nothing to close
    when the failure happened here instead.

    **A known, deliberately accepted gap, settled on human authority rather than closed by
    further engineering — read this before "improving" the capture below.** Several attempts
    were made to close a much narrower race than the one this baseline actually needs to defend
    against: a replacement landing in the specific, sub-millisecond window inside `aiosqlite`'s
    own cross-thread connect handoff, between SQLite binding to a file on its worker thread and
    this coroutine resuming to read the path. Pinning a file descriptor and connecting through
    its own `/proc/self/fd/<n>` path — reasoned to sidestep pathname resolution entirely — was
    measured, empirically, to *not* actually do so: `PRAGMA database_list` shows SQLite
    canonicalizes that magic-symlink path back to the ordinary pathname internally, and a file
    replaced at the path while an existing connection is live can make even an *already
    established* connection fail on its next statement — meaning the assumption the whole
    mechanism rested on was false, not merely incompletely implemented. Closing this properly
    would require controlling SQLite's own VFS-level file handle directly (a custom VFS or
    file-control integration), which is a materially larger undertaking than the value warrants
    for a race with this shape: it requires an adversarial replacement to land inside a
    sub-millisecond window at process startup, not the ordinary case this mechanism exists for
    (a store deleted and recreated while the service has been sitting open and idle, which the
    lifecycle poll closes completely). **The operator's own explicit direction is to accept this
    narrow gap rather than pursue that undertaking**, and to keep the capture simple: read
    `db_path.stat()` once, immediately after `await aiosqlite.connect()` returns, with no
    `await` between the connect and the read — not provably instantaneous with SQLite's own
    internal bind, but the tightest capture available without the VFS-level work this decision
    declines, and correct for every case except the one named above.

    Args:
        db_path: the database file to open.
        pragmas: the pragmas this database's own schema requires, applied in order. Required, not
            defaulted: the two schemas want different sets, and a default is how one of them comes
            to be opened under the other's.
        existing_only: refuse to create `db_path` if it is absent, by opening it through a
            `file:…?mode=rw` URI. The caller is left to say what absence means: for the memory
            store it is a store that was never created, and for a knowledge base it is an empty
            corpus, which is not an error at all.
        connect_failure: what to raise when the connect itself fails. Omitted, the driver's own
            error propagates. It is scoped to the connect deliberately — a caller naming a
            missing store cannot also name a failed pragma, which describes a different fault.

    Raises:
        Exception: whatever `connect_failure` returns, if the connect failed and one was given.
        aiosqlite.Error: the connect failed with no `connect_failure` given, or the extension
            load or a pragma failed.
        OSError: `db_path` could not be `stat`ed once the connection was established.
    """
    if existing_only:
        connector = aiosqlite.connect(f"file:{quote(str(db_path))}?mode=rw", uri=True)
    else:
        connector = aiosqlite.connect(db_path)
    try:
        db = await connector
    except aiosqlite.Error as error:
        await join_abandoned_worker(connector)
        if connect_failure is None:
            raise
        raise connect_failure(error) from error
    try:
        # The very first statement inside this `try`, with no `await` before it — a failure here
        # (a permission error, the path having become unstatable) must close the just-established
        # `db` exactly like a pragma failure a few lines below does; reading it *outside* this
        # block would abandon a real, worker-thread-backed connection with nothing left to close
        # it, which is a genuine resource leak this project's own history has already paid for
        # once: a suite whose tests all completed in 0.76 s then hung indefinitely with an empty
        # output pipe, because a non-daemon worker thread is joined before any `atexit` handler.
        opened_inode = db_path.stat().st_ino
        await _load_sqlite_vec(db)
        for pragma in pragmas:
            await db.execute(pragma)
    except BaseException:
        await db.close()
        raise
    return db, opened_inode
