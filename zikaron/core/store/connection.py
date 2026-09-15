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

from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import quote

import aiosqlite
import sqlite_vec

#: How a caller names a failed connect. Takes the driver's error and returns the exception to
#: raise in its place, with the original kept as the cause.
type ConnectFailure = Callable[[aiosqlite.Error], Exception]


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
    try:
        if existing_only:
            uri = f"file:{quote(str(db_path))}?mode=rw"
            db = await aiosqlite.connect(uri, uri=True)
        else:
            db = await aiosqlite.connect(db_path)
    except aiosqlite.Error as error:
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
