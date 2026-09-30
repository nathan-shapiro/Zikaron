"""The read pool and the connection holders, below the dispatcher.

`architecture.md` §"The service's connections" is normative. The dispatcher-level tests drive these
through requests; what is here are the edges a request cannot reach deterministically.
"""

import asyncio
import contextlib
import time
from pathlib import Path

import aiosqlite
import pytest

from tests.contention_fixtures import patch_budget
from tests.service_fixtures import open_context
from zikaron.core.store import holders
from zikaron.core.store.deadline import Deadline
from zikaron.core.store.holders import LockWaitExpired
from zikaron.core.store.pool import POOL_SIZE


def _spent(*, set_by_caller: bool) -> Deadline:
    return Deadline(at=time.monotonic() - 1, set_by_caller=set_by_caller)


async def _busy_timeout(db: aiosqlite.Connection) -> int:
    rows = await db.execute_fetchall("PRAGMA busy_timeout")
    return int(next(iter(rows))[0])


@pytest.mark.parametrize("set_by_caller", [True, False])
async def test_an_exhausted_pool_refuses_a_spent_deadline_at_once_naming_its_bound(
    tmp_path: Path, set_by_caller: bool
) -> None:
    async with open_context(tmp_path) as ctx:
        pool = ctx.store.pool
        held = [pool.lease(Deadline.budget()) for _ in range(POOL_SIZE)]
        for lease in held:
            _ = await lease.__aenter__()
        try:
            with pytest.raises(LockWaitExpired) as refused:
                async with pool.lease(_spent(set_by_caller=set_by_caller)):
                    pass
            assert refused.value.set_by_caller is set_by_caller
        finally:
            for lease in held:
                await lease.__aexit__(None, None, None)


async def test_a_held_connection_lock_refuses_a_spent_deadline_at_once(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        holder = holders.holder_of(ctx.store.connection)
        await holder.acquire(Deadline.budget())
        try:
            with pytest.raises(LockWaitExpired):
                await asyncio.create_task(holder.acquire(_spent(set_by_caller=False)))
        finally:
            holder.release()


async def test_a_wait_that_begins_as_the_lock_is_released_still_ends_at_its_deadline(
    tmp_path: Path,
) -> None:
    """Between a release and its woken waiter running, the lock reports itself free while that
    waiter is still first in line. An acquisition arriving then queues behind it, and that wait is
    bounded by its deadline like any other."""
    async with open_context(tmp_path) as ctx:
        holder = holders.holder_of(ctx.store.connection)
        await holder.acquire(Deadline.budget())
        queued = asyncio.create_task(holder.acquire(Deadline.budget()))
        await asyncio.sleep(0)
        holder.release()
        with pytest.raises(LockWaitExpired):
            await asyncio.wait_for(holder.acquire(_spent(set_by_caller=False)), timeout=1.0)
        await queued
        holder.release()


async def test_a_free_lock_is_taken_whatever_the_deadline(tmp_path: Path) -> None:
    """Nothing to wait for is not a wait: a spent deadline is refused only when it would queue."""
    async with open_context(tmp_path) as ctx:
        holder = holders.holder_of(ctx.store.connection)
        await holder.acquire(_spent(set_by_caller=True))
        holder.release()


async def test_a_notification_a_cancelled_waiter_consumed_still_reaches_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lease returns to a waiter that is cancelled in the same loop iteration — its deadline's
    expiry is a cancel. The next waiter must still get the idle connection rather than sleep out its
    budget beside it. Red on Python 3.12 with a single-waiter wake; later versions re-notify."""
    patch_budget(monkeypatch, 300)
    async with open_context(tmp_path) as ctx:
        pool = ctx.store.pool
        held = [pool.lease(Deadline.budget()) for _ in range(POOL_SIZE)]
        for lease in held:
            _ = await lease.__aenter__()
        first = asyncio.create_task(pool._take(Deadline.budget()))
        second = asyncio.create_task(pool._take(Deadline.budget()))
        await asyncio.sleep(0.01)
        await held[0].__aexit__(None, None, None)
        first.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            _ = await first
        db = await asyncio.wait_for(second, timeout=0.15)
        await pool._give_back(db)
        for lease in held[1:]:
            await lease.__aexit__(None, None, None)


async def test_a_lease_whose_return_is_cut_short_is_closed_with_the_pool(tmp_path: Path) -> None:
    """A handler cancelled while its lease is being returned — waiting for the pool's condition —
    leaves the connection neither idle nor closed. It is closed with the pool, or its worker thread
    keeps the process alive after a clean stop."""
    async with open_context(tmp_path) as ctx:
        pool = ctx.store.pool
        leased: list[aiosqlite.Connection] = []
        leased_one = asyncio.Event()
        condition_held = asyncio.Event()

        async def one_read() -> None:
            async with pool.lease(Deadline.budget()) as db:
                leased.append(db)
                leased_one.set()
                await condition_held.wait()

        task = asyncio.create_task(one_read())
        await leased_one.wait()
        async with pool._changed:
            condition_held.set()
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await pool.close()
        with pytest.raises(ValueError, match=r"active connection|closed"):
            await leased[0].execute("SELECT 1")


async def test_every_serving_connection_leaves_the_wait_to_the_primitive(tmp_path: Path) -> None:
    """The writer, a pool connection and a reopened writer all run at `busy_timeout = 0`: a wait
    inside SQLite cannot be cut at a deadline, and on some builds overruns its own timeout."""
    async with open_context(tmp_path) as ctx:
        assert await _busy_timeout(ctx.store.connection) == 0
        async with ctx.store.pool.lease(Deadline.budget()) as db:
            assert await _busy_timeout(db) == 0
        closing = ctx.store.connection
        holders.holder_of(closing).closed = True
        await closing.close()
        assert await _busy_timeout(await ctx.store.writer()) == 0


async def test_a_connection_handed_back_closed_is_dropped_and_replaced(tmp_path: Path) -> None:
    """Closed by a failed rollback: it is dropped, and the next lease opens a new one."""
    async with open_context(tmp_path) as ctx:
        async with ctx.store.pool.lease(Deadline.budget()) as db:
            holders.holder_of(db).closed = True
            await db.close()
        async with ctx.store.pool.lease(Deadline.budget()) as replacement:
            assert replacement is not db


async def test_a_lease_out_when_the_pool_closes_is_closed_when_it_returns(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        async with ctx.store.pool.lease(Deadline.budget()):
            pass
        async with ctx.store.pool.lease(Deadline.budget()) as db:
            await ctx.store.pool.close()
            assert await _busy_timeout(db) == 0
        with pytest.raises(ValueError, match=r"active connection|closed"):
            await db.execute("SELECT 1")
