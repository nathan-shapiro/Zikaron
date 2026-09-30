"""A write on the writer claims SQLite's write lock at `BEGIN`, so another process cannot refuse it.

`architecture.md` §Lifecycle is normative. A deferred transaction that reads before it writes is
refused at once with `SQLITE_BUSY_SNAPSHOT` when another connection commits between the read and the
write, and `busy_timeout` never retries that. Another connection means another process — the
detached indexer's build row, a second service, an operator's shell — so no lock inside this
process closes it; `BEGIN IMMEDIATE` does, because the write lock is then held from the first read.

**The fixture is the failure itself, played into every write verb.** Inside each transaction on the
writer, after a read, a raw connection outside the service commits a write. Under `IMMEDIATE` that
write must wait: it is still pending when the verb's work ends, the verb answers, and the write
lands after it. Under the old deferred `BEGIN` the same fixture refuses the verb `store_busy`,
which is how the test is shown to test something.
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.contention_fixtures import (
    ExternalWriter,
    call,
    error_of,
    external_writer,
    patch_budget,
)
from tests.served_group_fixtures import CONSOLIDATOR
from tests.service_fixtures import open_context
from tests.test_access_log import _ARMS, _answer, _line, _remembered
from zikaron.core.knowledge import lifecycle, registry
from zikaron.core.store import transactions
from zikaron.knowledge.indexer import detach
from zikaron.service.context import ServiceContext
from zikaron.service.methods import Access
from zikaron.service.server import METHODS

#: Long enough for an unblocked commit on an idle connection to land many times over, so a write
#: still pending after it is one that is waiting for the lock.
_SETTLE_SECONDS: Final = 0.3

_WRITES: Final = sorted(name for name, method in METHODS.items() if method.access is Access.WRITE)


@pytest.fixture(autouse=True)
def no_real_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """`knowledge_add` spawns a detached indexer; nothing here wants one."""

    def _no_spawn(
        name: str, *, project: Path, full: bool = False, spawned_by_op_id: str | None = None
    ) -> list[str]:
        del full, spawned_by_op_id
        return detach.command(name, project=project, full=False)

    monkeypatch.setattr(detach, "spawn", _no_spawn)


def _interleave_commits(
    monkeypatch: pytest.MonkeyPatch, ctx: ServiceContext, writer: ExternalWriter
) -> list[tuple[asyncio.Future[int], bool]]:
    """Commit an outside write inside every transaction on the writer, after that transaction's
    first read, recording each write's future and whether it had landed when the work ended."""
    interleaved: list[tuple[asyncio.Future[int], bool]] = []
    real = transactions.in_one_transaction

    async def wrapped[T](
        db: aiosqlite.Connection,
        work: Callable[[aiosqlite.Connection], Awaitable[T]],
        **options: object,
    ) -> T:
        if db is not ctx.store.connection:
            return await real(db, work, **options)  # type: ignore[arg-type]

        async def with_an_outside_commit(connection: aiosqlite.Connection) -> T:
            await connection.execute_fetchall("SELECT count(*) FROM memory")
            landed = asyncio.ensure_future(asyncio.to_thread(writer.commit_a_write))
            await asyncio.wait([landed], timeout=_SETTLE_SECONDS)
            result = await work(connection)
            interleaved.append((landed, landed.done()))
            return result

        return await real(db, with_an_outside_commit, **options)  # type: ignore[arg-type]

    for module in (transactions, lifecycle, registry):
        monkeypatch.setattr(module, "in_one_transaction", wrapped)
    return interleaved


async def _arms_for(method: str, ctx: ServiceContext) -> tuple[dict[str, object], str]:
    """The succeeding params for `method`, and the envelope kind to send them under.

    `next_group` is given a run to serve from, so its first transaction writes: on an empty store it
    only asks whether a run exists, which no outside commit can refuse.
    """
    if method == "memory_next_group":
        await _remembered(ctx)
        await _answer(ctx, _line("memory_plan_groups", {}, kind=CONSOLIDATOR.kind))
        return {}, CONSOLIDATOR.kind
    arms = await _ARMS[method](ctx)
    return arms.succeeding, arms.kind


def test_the_method_table_classifies_every_method_as_the_design_does() -> None:
    """A method is a write if it can write `memory.db` other than the event rows it emits about
    itself, whatever its name suggests: `memory_fetch` mints receipts, and `knowledge_unlock`
    writes only the corpus's own database. Held equal to the design's two sets, so a method cannot
    arrive unclassified."""
    classified = {name: method.access for name, method in METHODS.items()}
    assert classified == {
        "memory_remember": Access.WRITE,
        "memory_amend": Access.WRITE,
        "memory_retire": Access.WRITE,
        "memory_fetch": Access.WRITE,
        "memory_plan_groups": Access.WRITE,
        "memory_next_group": Access.WRITE,
        "memory_apply_merge": Access.WRITE,
        "memory_apply_promote": Access.WRITE,
        "memory_apply_discard": Access.WRITE,
        "knowledge_add": Access.WRITE,
        "knowledge_rename": Access.WRITE,
        "knowledge_remove": Access.WRITE,
        "memory_search": Access.READ,
        "memory_surface": Access.READ,
        "knowledge_search": Access.READ,
        "knowledge_list": Access.READ,
        "knowledge_status": Access.READ,
        "knowledge_refresh": Access.READ,
        "knowledge_unlock": Access.READ,
    }


@pytest.mark.parametrize("method", _WRITES)
async def test_another_connections_commit_cannot_refuse_a_write_verb(
    method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with open_context(tmp_path) as ctx:
        params, kind = await _arms_for(method, ctx)
        with external_writer(ctx.store.path) as writer:
            interleaved = _interleave_commits(monkeypatch, ctx, writer)
            answered = await _answer(ctx, _line(method, params, kind=kind))
            await asyncio.gather(*(landed for landed, _ in interleaved))
        assert error_of(answered) is None, answered
        assert interleaved, f"{method} ran no transaction on the writer"
        assert [landed_early for _, landed_early in interleaved] == [False] * len(interleaved), (
            "an outside write committed inside the verb's transaction"
        )


async def test_contention_on_fetch_and_retire_is_store_busy_not_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both used to open a raw `BEGIN` with no failure map, so a locked store reached their callers
    as `internal_error`. Held for longer than the budget, the lock is contention, and the answer is
    the retryable one."""
    patch_budget(monkeypatch, 300)
    async with open_context(tmp_path) as ctx:
        uuid = await _remembered(ctx)
        fetched = await call(ctx, "memory_fetch", {"uuids": [uuid]})
        version = fetched["result"]["records"][0]["version"]  # type: ignore[index]
        cases: list[tuple[str, dict[str, object]]] = [
            ("memory_fetch", {"uuids": [uuid]}),
            ("memory_retire", {"uuid": uuid, "version": version}),
        ]
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            for method, params in cases:
                refused = error_of(await call(ctx, method, params))
                assert refused is not None
                assert refused[0] == -32020, (method, refused)
