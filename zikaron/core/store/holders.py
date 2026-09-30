"""Who holds a connection: its transaction lock, the task inside it, and whether it is closed.

`architecture.md` §"The service's connections" is normative. One SQLite connection has one
transaction state, so two tasks' transactions on one handle cannot overlap: the second `BEGIN`
fails as a nested one, or a statement issued outside a transaction runs inside another task's and
reads its uncommitted rows. The transaction primitive therefore serializes every transaction on a
handle behind that handle's lock, and this module is where the lock lives.

**A holder is found by the connection, not passed beside it**, so no signature that takes a bare
`aiosqlite.Connection` has to change. A handle nobody registered gets a default holder on first use:
deferred, and left to SQLite's own `busy_timeout`. The two kinds of handle that differ register
themselves — a `Store`'s writer, which opens every transaction `IMMEDIATE`, and a read-pool
connection, whose one `IMMEDIATE` transaction is a read's retry. Both run at `busy_timeout = 0`, and
the primitive polls for the write lock on them itself, until the request's deadline.

**Every refusal the primitive makes before a statement runs shares `TransactionRefused`**, and none
is an `aiosqlite.Error`: nothing reached SQLite, so no failure map may read one as the driver's.
"""

import asyncio
import weakref
from dataclasses import dataclass, field
from typing import Final

import aiosqlite

from zikaron.core.store.deadline import Deadline


class TransactionRefused(Exception):  # noqa: N818 — a refusal, not an error in the caller's code.
    """The primitive declined to start a transaction, and nothing ran."""


class WriterClosedError(TransactionRefused):
    """The handle was closed after a rollback that failed, before this transaction's first
    statement.

    Named for its commonest case, a request queued on the writer when it closed; it is raised for
    any closed handle. Nothing ran, so the honest answer is the retryable one.
    """


class LockWaitExpired(TransactionRefused):
    """A wait for a connection — its lock, or a pool lease — reached its deadline.

    `set_by_caller` is which bound cut the wait: the caller's own deadline, which is lateness, or
    the service's budget, which is contention.
    """

    def __init__(self, *, set_by_caller: bool) -> None:
        super().__init__("the wait for a connection reached its deadline")
        self.set_by_caller: Final = set_by_caller


class NestedTransactionError(RuntimeError):
    """A task asked for a transaction on a handle whose lock it already holds.

    A programming error, raised at once: waiting would wait on itself for the whole budget and then
    answer a retryable refusal for something no retry fixes.
    """


@dataclass(eq=False, slots=True)
class ConnectionHolder:
    """One handle's transaction lock, the task holding it, and the handle's closed mark."""

    #: Whether a transaction on this handle opens `IMMEDIATE` unless told otherwise.
    immediate: bool = False
    #: Whether the primitive polls for the write lock at an `IMMEDIATE` transaction's `BEGIN`, on a
    #: handle whose own `busy_timeout` is zero.
    polls_for_lock: bool = False
    closed: bool = False
    #: The deadline a read-pool lease was taken under, while it is held.
    lease_deadline: Deadline | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _owner: "asyncio.Task[object] | None" = None

    async def acquire(self, deadline: Deadline) -> None:
        """Take this handle's lock, waiting no later than `deadline`.

        Raises:
            NestedTransactionError: the calling task already holds it.
            LockWaitExpired: the lock was still held, or queued for, at `deadline`.
            WriterClosedError: the handle is closed. Checked after the lock is taken, so a request
                queued behind the transaction that closed it is refused rather than run.
        """
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            raise NestedTransactionError("a transaction is already open on this connection")
        # Timed whatever `locked()` says: it answers `False` between a release and its woken waiter
        # running, and an acquisition arriving then queues behind that waiter. A free lock is taken
        # without yielding, so the timeout never fires on it.
        try:
            async with asyncio.timeout(deadline.remaining()):
                await self._lock.acquire()
        except TimeoutError:
            raise LockWaitExpired(set_by_caller=deadline.set_by_caller) from None
        self._owner = task
        if self.closed:
            self.release()
            raise WriterClosedError("the connection was closed by a failed rollback")

    def release(self) -> None:
        """Let the next transaction on this handle start."""
        self._owner = None
        self._lock.release()


_HOLDERS: Final[weakref.WeakKeyDictionary[aiosqlite.Connection, ConnectionHolder]] = (
    weakref.WeakKeyDictionary()
)


def hold(db: aiosqlite.Connection, *, immediate: bool) -> ConnectionHolder:
    """Register one of a store's serving connections, with the transaction mode its owner requires.

    Called once, by whoever opened the handle, before any transaction runs on it. The handle must
    already run at `busy_timeout = 0` (`ddl.SERVING_PRAGMA`), since the primitive polls for its
    write lock.
    """
    holder = ConnectionHolder(immediate=immediate, polls_for_lock=True)
    _HOLDERS[db] = holder
    return holder


def holder_of(db: aiosqlite.Connection) -> ConnectionHolder:
    """`db`'s holder, created deferred and left to SQLite's own wait if nobody registered it."""
    holder = _HOLDERS.get(db)
    if holder is None:
        holder = ConnectionHolder()
        _HOLDERS[db] = holder
    return holder
