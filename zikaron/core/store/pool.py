"""A small pool of read connections, leased one request at a time.

`architecture.md` §"The service's connections" and `retrieval.md` §"One read is one transaction" are
normative. A read runs on a connection of its own so that it never queues behind the writer's lock:
WAL gives it a snapshot while a write is open. The lease covers a request's whole handler, not one
transaction, because the knowledge reads run several transactions with corpus opens between them.

**The wait for a lease shares the request's one budget.** `lease` waits no later than the request's
deadline, and the deadline travels with the leased handle (`lease_deadline`), so a read's retry
polls for the write lock only for what the lease wait left.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Final

import aiosqlite

from zikaron.core.store.deadline import Deadline
from zikaron.core.store.holders import LockWaitExpired, hold, holder_of

#: How many read connections one store's service opens at most. The case it covers is a cold model
#: load, when every read that arrives embeds its query while holding its lease and waits on the one
#: load: one request in flight from each concurrent client of a store — the push hook, the primary
#: MCP server, a consolidator, and a typed command. A second session's reads during the same load
#: wait for a lease within their budget.
POOL_SIZE: Final = 4

#: Opens one read connection onto the store — its pragmas applied, `sqlite-vec` loaded, and the
#: file checked to be the one the service opened.
type Opener = Callable[[], Awaitable[aiosqlite.Connection]]


class ReadPool:
    """Read connections, opened on first demand up to `POOL_SIZE`, and closed with the store."""

    def __init__(self, opener: Opener) -> None:
        self._opener: Final = opener
        self._idle: list[aiosqlite.Connection] = []
        #: Connections whose return a cancellation cut short: neither idle nor closed, and each
        #: holds a non-daemon worker thread that would keep the process alive after it stopped.
        self._abandoned: list[aiosqlite.Connection] = []
        self._opened = 0
        self._closed = False
        self._changed = asyncio.Condition()

    @contextlib.asynccontextmanager
    async def lease(self, deadline: Deadline) -> AsyncIterator[aiosqlite.Connection]:
        """One read connection for the span of the block, waited for no later than `deadline`.

        Raises:
            LockWaitExpired: every connection was leased and none returned by `deadline`.
            StoreReplacedError: a connection opened for this lease found the store's file replaced
                or gone.
        """
        db = await self._take(deadline)
        holder_of(db).lease_deadline = deadline
        try:
            yield db
        finally:
            await self._give_back(db)

    async def _take(self, deadline: Deadline) -> aiosqlite.Connection:
        # Every waiter is woken on a change, never one: on Python 3.12 a notified waiter cancelled
        # in the same loop iteration — its deadline's expiry, a client gone — takes the notification
        # with it, and the next waiter would sleep out its budget beside an idle connection. Each
        # waiter re-checks the predicate, so waking all costs only that.
        async with self._changed:
            while not self._idle and self._opened >= POOL_SIZE:
                remaining = deadline.remaining()
                if remaining <= 0:
                    raise LockWaitExpired(set_by_caller=deadline.set_by_caller)
                try:
                    async with asyncio.timeout(remaining):
                        await self._changed.wait()
                except TimeoutError:
                    raise LockWaitExpired(set_by_caller=deadline.set_by_caller) from None
            if self._idle:
                return self._idle.pop()
            self._opened += 1
        # Opened outside the condition, so a slow open holds up no lease being returned.
        try:
            db = await self._opener()
        except BaseException:
            await self._forget_one()
            raise
        hold(db, immediate=False)
        return db

    async def _give_back(self, db: aiosqlite.Connection) -> None:
        holder = holder_of(db)
        holder.lease_deadline = None
        try:
            # A handle a failed rollback closed is dropped rather than handed on.
            if not self._closed and not holder.closed:
                async with self._changed:
                    self._idle.append(db)
                    self._changed.notify_all()
                return
            with contextlib.suppress(Exception):
                await db.close()
            await self._forget_one()
        except asyncio.CancelledError:
            # Nothing awaits after the append, so a handle cut short here never reached `_idle`.
            self._abandoned.append(db)
            raise

    async def _forget_one(self) -> None:
        async with self._changed:
            self._opened -= 1
            self._changed.notify_all()

    async def close(self) -> None:
        """Close every idle connection, every leased one as its lease returns, and any whose return
        a cancellation cut short.

        An abandoned handle is either fully open — the cut landed at the condition's lock — or
        already stopped, since `aiosqlite`'s `close` finishes its own stop in a `finally` even when
        cancelled; so the close here is real for the first and a suppressed no-op for the second.
        The service cancels its handlers before it closes the store, so a return cannot be cut short
        after this has run.
        """
        async with self._changed:
            self._closed = True
            idle, self._idle = self._idle, []
            abandoned, self._abandoned = self._abandoned, []
            self._opened -= len(idle)
        for db in idle:
            await db.close()
        for db in abandoned:
            with contextlib.suppress(Exception):
                await db.close()


def lease_deadline(db: aiosqlite.Connection) -> Deadline:
    """The deadline `db` was leased under, or the service's budget from now if it was not leased.

    Not leased is a connection a caller handed over directly — a test, or a writer — which has no
    earlier wait for this one to share a budget with.
    """
    deadline = holder_of(db).lease_deadline
    return Deadline.budget() if deadline is None else deadline
