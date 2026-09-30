"""A read's one retry, and its one wait budget.

`retrieval.md` §"One read is one transaction" and `architecture.md` §Lifecycle are normative. A
`memory_search` or `memory_surface` reads before it writes its own events, so its upgrade to the
write lock is refused at once — a held lock and a commit since its snapshot alike — without the busy
handler running. It retries once, from `BEGIN IMMEDIATE`, for which the primitive polls within what
is left of the read's budget.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.contention_fixtures import call, error_of, external_writer, patch_budget
from tests.service_fixtures import open_context
from zikaron.core.retrieval import reads
from zikaron.core.store import transactions
from zikaron.core.store.deadline import Deadline
from zikaron.core.store.pool import POOL_SIZE

_STORE_BUSY: Final = -32020


async def _seeded(ctx: object) -> None:
    await call(ctx, "memory_remember", {"gist": "the proto codegen drifts", "content": "pin it"})  # type: ignore[arg-type]


def _count_attempts(monkeypatch: pytest.MonkeyPatch) -> list[bool | None]:
    """Record each read transaction's requested mode — `None` deferred, `True` for the retry."""
    attempts: list[bool | None] = []
    real = transactions.in_one_transaction

    async def counted(
        db: aiosqlite.Connection,
        work: Callable[[aiosqlite.Connection], Awaitable[object]],
        **options: object,
    ) -> object:
        attempts.append(options.get("immediate"))  # type: ignore[arg-type]
        return await real(db, work, **options)  # type: ignore[arg-type]

    monkeypatch.setattr(transactions, "in_one_transaction", counted)
    return attempts


async def test_a_reads_first_attempt_is_refused_at_a_held_lock_within_milliseconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQLite runs the busy handler for a write-lock request only from a connection with no
    transaction open, and a read has read by the time it inserts its event. With the retry taken
    away, the read answers at once, far inside the budget."""

    async def first_attempt_only(
        db: aiosqlite.Connection, work: Callable[..., Awaitable[object]], **_options: object
    ) -> object:
        return await transactions.in_one_transaction(
            db, work, failure=reads._retry_failure_map("search", Deadline.budget())
        )

    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        monkeypatch.setattr(reads, "_read_with_one_retry", first_attempt_only)
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            started = time.monotonic()
            refused = error_of(await call(ctx, "memory_search", {"query": "proto"}))
            elapsed = time.monotonic() - started
        assert refused is not None, refused
        assert refused[0] == _STORE_BUSY, refused
        assert elapsed < 0.5, elapsed


async def test_a_read_retries_once_and_succeeds_when_the_hold_ends_inside_its_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        attempts = _count_attempts(monkeypatch)
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            writer.release_after(0.3)
            answered = await call(ctx, "memory_search", {"query": "proto"})
        assert error_of(answered) is None, answered
        assert attempts == [None, True]


async def test_a_read_whose_hold_outlasts_its_budget_answers_store_busy_after_one_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget_ms = 400
    patch_budget(monkeypatch, budget_ms)
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        attempts = _count_attempts(monkeypatch)
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            started = time.monotonic()
            refused = error_of(await call(ctx, "memory_search", {"query": "proto"}))
            elapsed = time.monotonic() - started
        assert refused is not None, refused
        assert refused[0] == _STORE_BUSY, refused
        assert attempts == [None, True]
        assert 0.8 * budget_ms / 1000 <= elapsed <= 1.3 * budget_ms / 1000, elapsed


async def test_a_reads_lease_wait_and_retry_share_one_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every lease is held until about half the budget, and another process's write lock outlasts
    one and a half. The read gets a lease at half, is refused at its upgrade, and its retry waits
    only what is left: it answers about one budget from its dispatch. With the retry waiting a whole
    budget of its own instead, it answers at about one and a half. A pool that stayed
    exhausted throughout would answer at one budget either way and test nothing."""
    budget_ms = 500
    patch_budget(monkeypatch, budget_ms)
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        release = asyncio.Event()
        leased = 0

        async def pin() -> None:
            nonlocal leased
            async with ctx.store.pool.lease(Deadline.budget()):
                leased += 1
                await release.wait()

        pinned = [asyncio.create_task(pin()) for _ in range(POOL_SIZE)]
        while leased < POOL_SIZE:
            await asyncio.sleep(0.01)
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            writer.release_after(1.6 * budget_ms / 1000)
            asyncio.get_running_loop().call_later(0.5 * budget_ms / 1000, release.set)
            started = time.monotonic()
            refused = error_of(await call(ctx, "memory_search", {"query": "proto"}))
            elapsed = time.monotonic() - started
            await asyncio.gather(*pinned)
        assert refused is not None, refused
        assert refused[0] == _STORE_BUSY, refused
        assert 0.8 * budget_ms / 1000 <= elapsed <= 1.25 * budget_ms / 1000, elapsed


async def test_a_read_at_an_exhausted_pool_answers_store_busy_at_its_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget_ms = 300
    patch_budget(monkeypatch, budget_ms)
    async with open_context(tmp_path) as ctx:
        release = asyncio.Event()
        leased = 0

        async def pin() -> None:
            nonlocal leased
            async with ctx.store.pool.lease(Deadline.budget()):
                leased += 1
                await release.wait()

        pinned = [asyncio.create_task(pin()) for _ in range(POOL_SIZE)]
        while leased < POOL_SIZE:
            await asyncio.sleep(0.01)
        started = time.monotonic()
        refused = error_of(await call(ctx, "memory_search", {"query": "proto"}))
        elapsed = time.monotonic() - started
        release.set()
        await asyncio.gather(*pinned)
        assert refused == (_STORE_BUSY, {"verb": "memory_search"}), refused
        assert 0.8 * budget_ms / 1000 <= elapsed <= 1.5 * budget_ms / 1000, elapsed
