"""The `call` event: one row per dispatched RPC, written where the caller cannot be made to wait.

`schema.md` §"`call` is an access log" is normative. The semantic kinds answer *what happened to the
store*; this answers *what was asked of it*, including everything that was asked and refused, and
it is emitted at the dispatch seam so that a method added later is instrumented because it is in
the table rather than because somebody remembered.

**It is best-effort, and that is a mechanism rather than an intention.** Every connection the store
opens waits `ddl.BUSY_TIMEOUT_MS` for the write lock, and this row is attempted on the response path
of a caller with no stake in the lock it needs. So the writer owns a connection of its own, opened
with that timeout at zero, and drops the row rather than waiting: losing an audit row is a
measurement gap, and holding a response behind an unrelated lock is not. The access log therefore
undercounts under contention, by construction, and the semantic kinds remain the authority on what
happened to the store.

**Nothing this module does may reach a caller's answer.** The seam encodes its response line before
attempting the row, so the property holds by construction rather than by a guard here — which
matters because the row is written *after* the handler has committed: a failure propagating from
this point would answer `internal_error` for a `memory_remember` that is durably in the store, the
agent would retry, and the store would gain a duplicate.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

import aiosqlite

from zikaron.core.errors import ErrorCode
from zikaron.core.events import EVENT_SPECS, CallDetail, EventOrigin
from zikaron.core.records.memory import log_event
from zikaron.core.store import ddl
from zikaron.core.store.connection import open_connection
from zikaron.core.store.transactions import in_one_transaction, is_contention, propagate
from zikaron.service.rpc import ProtocolErrorCode

_LOGGER = logging.getLogger("zikaron.service")


@dataclass(slots=True)
class AccessLog:
    """A store's access log, on a private connection, or a stopped one that writes nothing.

    Two states, and `record` is safe in both: a stopped log is what `close` leaves behind and what a
    connection closed out from under this writer becomes, and a caller never has to ask which it
    holds.

    **The connection is private rather than the store's own**, because the pragmas that make this
    write cheap are per-connection and toggling them on a shared one would leave them applied to
    whatever other handler's statement ran in that window — turning an unrelated caller's write into
    a spurious `store_busy`. What is borrowed from `core/knowledge/counters.py` is its contention
    swallow, not its toggle, which is safe only because that caller owns its connection.
    """

    _connection: aiosqlite.Connection | None
    #: Serializes the three statements one row takes. See `record`.
    _writing: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: Whether the last *transient* failure has already been logged. A full disk fails every call,
    #: so a line per call floods the service log while one line ever hides the recovery: the latch
    #: clears on the next row that lands. The stop does not use it — it fires once by construction.
    _reported: bool = False

    @classmethod
    async def open(cls, db_path: Path) -> Self:
        """Open the private connection this writer owns.

        Opened in `ServiceContext` **after** the store, so it never meets a `CHECK` that would
        refuse its rows: the service is the one opener that migrates, and a connection opened ahead
        of that would be writing a kind the schema on disk does not yet admit.

        It loads `sqlite-vec` that it will never use, because `open_connection` does. One extension
        load per service start is not worth a second opener variant, and a bare-`sqlite3` path to
        avoid it is what that function exists to forbid: a handler calling `sqlite3` directly can
        hold the event loop for the whole of SQLite's retry.

        `existing_only`, so a `memory.db` that has gone missing between the store's open and this is
        a failure rather than a second, empty database file beside the real one.

        Raises:
            aiosqlite.Error: the connect, the extension load or a pragma failed. The service has no
                access log without this and startup is where a failure is cheap to report.
            OSError: `db_path` could not be `stat`ed once the connection was established.
        """
        connection, _inode = await open_connection(
            db_path, pragmas=ddl.ACCESS_LOG_PRAGMAS, existing_only=True
        )
        return cls(_connection=connection)

    async def record(
        self,
        *,
        origin: EventOrigin,
        method: str,
        refused: ErrorCode | ProtocolErrorCode | None,
        duration_ms: float,
    ) -> None:
        """Write one `call` row, or drop it. No failure of the write reaches the caller.

        `refused` is typed over both error enums rather than over the name it becomes, which is what
        makes `mypy --strict` refuse a bare string here: `CallDetail.error_code` is `str | None`,
        because `ErrorCode` is an `IntEnum` whose `str()` is its wire integer and a member stored
        there would be refused inside this very write and the row dropped — leaving an access log
        that holds no refusal at all. So the conversion happens once, here, off a parameter no
        string satisfies.

        Written as a fresh transaction on this writer's own connection, committed after the handler
        it describes: the seam sees a handler only once it has committed or rolled back, which is
        why `call` is exempt from invariant 10 and cannot be otherwise.
        """
        detail = CallDetail(
            method=method,
            ok=refused is None,
            error_code=None if refused is None else refused.wire_name,
            duration_ms=duration_ms,
        )

        async def _write(db: aiosqlite.Connection) -> None:
            await log_event(db, ctx=origin, detail=detail, memory_uuid=None)

        # One writer at a time on this connection. `record` is awaited from every client
        # connection's task, and its three statements interleave at their awaits — so two concurrent
        # calls would have the second's `BEGIN` fail *inside* the first's transaction, and the
        # second's rollback discard the first's row as well as its own. `busy_timeout` is zero here,
        # so a wait for this lock is bounded by one write rather than by SQLite's retry.
        #
        # The connection is read **under** that lock, which is the only read of it that can be
        # trusted: `close` clears the field while holding the same lock, so a call queued behind
        # another one during a shutdown finds the `None` rather than a handle that closed underneath
        # it and reports an orderly close as a failure.
        async with self._writing:
            connection = self._connection
            if connection is None:
                return
            # Validated **before** the transaction, which is what lets the two failure dispositions
            # below be told apart. `EventSpec.validate` raises `ValueError`, and so does a statement
            # on a connection `transactions.finalize` has closed — but a refused payload says
            # nothing about the next row, where a closed connection fails every one. Inside the
            # transaction the two would be one `except`, and a single bad payload would switch the
            # log off for the process. **After** the check above, so a stopped log validates nothing
            # and cannot report a payload from a writer the design says writes nothing.
            try:
                EVENT_SPECS[detail.kind].validate(detail.as_detail())
            except ValueError:
                self._report("refused a call event's own payload")
                return
            try:
                await in_one_transaction(connection, _write, failure=propagate)
            except aiosqlite.Error as error:
                if not is_contention(error):
                    self._report("could not write a call event")
            except Exception:
                # Two causes, one disposition. `finalize` closed this connection after a rollback it
                # could not complete, and the next statement on a closed one raises; or the failure
                # is one no layer below named. Reopening would retry against transaction state that
                # could not be repaired, so the log stops and a restart restores it.
                #
                # Closed before the field is cleared, because on the second cause the connection is
                # still open and `aiosqlite`'s worker thread is not a daemon — abandoning it keeps
                # the interpreter alive at exit. Suppressed, because a branch whose purpose is to
                # reach no caller may not raise on its way out; an already-closed connection's
                # `close` returns at once, so the first cause pays nothing for it.
                with contextlib.suppress(Exception):
                    await connection.close()
                self._connection = None
                # Not through `_report`: this branch can fire **at most once** — `_connection` is
                # `None` afterwards and every later call returns at the check above — so it
                # needs no latch, and going through the shared one would swallow it in the very
                # sequence that reaches here. A driver error on the row latches `_report` first;
                # `finalize`'s failed rollback closes the connection behind it; the stop arrives on
                # the *next* call and would find the latch already set.
                _LOGGER.exception("the access log has stopped; no further call events")
            else:
                self._reported = False

    def _report(self, message: str) -> None:
        """Log one transient failure with its traceback, and nothing more until a row lands.

        Called only from an `except` block, which is where the traceback comes from. Not used for
        the stop, which fires once by construction — see `record`.
        """
        if self._reported:
            return
        self._reported = True
        _LOGGER.exception(message)

    async def close(self) -> None:
        """Close the private connection and stop writing. Safe to call more than once.

        Holds `_writing`, so a `record` already inside it finishes first and one waiting behind it
        sees the cleared field instead of a handle this closed. The wait is bounded by one write,
        which is what `busy_timeout = 0` on this connection makes bounded.
        """
        async with self._writing:
            connection = self._connection
            self._connection = None
            if connection is not None:
                await connection.close()
