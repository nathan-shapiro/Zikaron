"""The writer: one connection, its transactions serialized, one wait budget, and its replacement.

`architecture.md` §Lifecycle is normative. Every test here drives the dispatcher or the transaction
primitive directly, and each property is one the pre-serialization service got wrong: two requests
nesting their transactions on one handle, a writer waiting the budget twice, a handle a failed
rollback closed answering every later request with a failure, and a connection opened after startup
onto a file that is no longer the store.
"""

import asyncio
import shutil
import time
from pathlib import Path

import aiosqlite
import pytest

from tests.contention_fixtures import call, error_of, external_writer, patch_budget
from tests.service_fixtures import open_context
from zikaron.core.knowledge import registry
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.store import holders, transactions
from zikaron.core.store.deadline import Deadline
from zikaron.core.store.holders import NestedTransactionError
from zikaron.core.store.store import Store
from zikaron.knowledge.indexer import detach
from zikaron.service.context import ServiceContext

_STORE_BUSY = -32020
_INTERNAL_ERROR = -32603
_STORE_UNAVAILABLE = -32025


@pytest.fixture(autouse=True)
def no_real_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """`knowledge_add` spawns a detached indexer; nothing here wants one."""

    def _no_spawn(
        name: str, *, project: Path, full: bool = False, spawned_by_op_id: str | None = None
    ) -> list[str]:
        del full, spawned_by_op_id
        return detach.command(name, project=project, full=False)

    monkeypatch.setattr(detach, "spawn", _no_spawn)


async def _memory_count(ctx: ServiceContext) -> int:
    rows = await ctx.store.connection.execute_fetchall("SELECT count(*) FROM memory")
    return int(next(iter(rows))[0])


async def test_a_task_that_asks_again_for_a_transaction_it_holds_fails_at_once(
    tmp_path: Path,
) -> None:
    """Waiting would wait on itself for the whole budget and then answer a retryable `store_busy`
    for a programming error no retry fixes; it must keep failing loudly, and at once."""
    async with open_context(tmp_path) as ctx:

        async def nested(db: aiosqlite.Connection) -> None:
            await transactions.in_one_transaction(db, _noop, failure=transactions.propagate)

        started = time.monotonic()
        with pytest.raises(NestedTransactionError):
            await transactions.in_one_transaction(
                ctx.store.connection, nested, failure=transactions.propagate
            )
        assert time.monotonic() - started < 0.5


async def _noop(_db: aiosqlite.Connection) -> None:
    return None


async def test_no_two_transactions_nest_on_the_writer_whatever_the_interleaving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One write held open briefly — well inside every budget — while reads and writes arrive
    concurrently. Every one succeeds; before serialization the writes met a nested `BEGIN` and
    answered `internal_error`. Which reads retry depends on timing, so outcomes are asserted, not
    retries."""
    async with open_context(tmp_path) as ctx:
        real_finalize = transactions.finalize

        async def slow_finalize(
            db: aiosqlite.Connection, error: BaseException | None, **options: object
        ) -> None:
            await asyncio.sleep(0.05)
            await real_finalize(db, error, **options)  # type: ignore[arg-type]

        monkeypatch.setattr(transactions, "finalize", slow_finalize)
        requests = [
            call(ctx, "memory_remember", {"gist": f"gist {index}", "content": "content"})
            for index in range(4)
        ] + [call(ctx, "memory_search", {"query": "gist"}) for _ in range(4)]
        answers = await asyncio.gather(*requests)
        assert [error_of(answer) for answer in answers] == [None] * len(answers), answers
        assert await _memory_count(ctx) == 4


async def test_a_writers_whole_wait_is_one_budget_whichever_side_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two writers dispatched together behind another process's lock, held for about 2.4 budgets.
    The first polls for the write lock; the second waits for the first's hold on the connection's
    lock. Each answers `store_busy` about one budget from its dispatch — the second whether its
    connection-lock wait or the poll refuses it. With the two waits compounding, the second answers
    at about two."""
    budget_ms = 500
    patch_budget(monkeypatch, budget_ms)
    async with open_context(tmp_path) as ctx:
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            writer.release_after(2.4 * budget_ms / 1000)

            async def timed(index: int) -> tuple[float, tuple[int, dict[str, object]] | None]:
                started = time.monotonic()
                answer = await call(ctx, "memory_remember", {"gist": f"g{index}", "content": "c"})
                return time.monotonic() - started, error_of(answer)

            answers = await asyncio.gather(timed(0), timed(1))
        for elapsed, refused in answers:
            assert refused is not None, refused
            assert refused[0] == _STORE_BUSY, refused
            assert 0.8 * budget_ms / 1000 <= elapsed <= 1.5 * budget_ms / 1000, answers


async def test_the_wait_for_the_write_lock_ends_at_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write-lock half of the one budget: a transaction whose deadline is half spent polls for
    the write lock only for the other half, so behind another process's lock it is refused at the
    deadline — not a whole budget after it, and not wherever SQLite's own sleep lands."""
    budget_ms = 500
    patch_budget(monkeypatch, budget_ms)
    async with open_context(tmp_path) as ctx:
        deadline = Deadline.budget()
        await asyncio.sleep(0.5 * budget_ms / 1000)
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            with pytest.raises(aiosqlite.OperationalError):
                await transactions.in_one_transaction(
                    ctx.store.connection, _noop, failure=transactions.propagate, deadline=deadline
                )
            overrun = time.monotonic() - deadline.at
        assert overrun < 0.25 * budget_ms / 1000, overrun


async def test_a_write_lock_freed_during_the_wait_is_taken(tmp_path: Path) -> None:
    """Refused at once while another process holds the lock, the `BEGIN` is retried, and the
    transaction proceeds within a few polls of the lock's release — not at the budget's end, and not
    at a pause long enough to cost a request its deadline."""
    async with open_context(tmp_path) as ctx:
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            writer.release_after(0.3)
            started = time.monotonic()
            await transactions.in_one_transaction(
                ctx.store.connection, _noop, failure=transactions.propagate
            )
            late = time.monotonic() - started - 0.3
        # A fixed bound, four times the longest pause, rather than one read from the constant it
        # exists to hold down.
        assert 0 <= late < 0.1, late


async def test_the_wait_for_the_writers_lock_ends_at_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The connection-lock half: a writer queued behind another request's long transaction on the
    writer — a plan fallback, say — is refused `store_busy` at its budget rather than waiting for
    that transaction however long it lasts, which would be a wedge by construction."""
    budget_ms = 400
    patch_budget(monkeypatch, budget_ms)
    async with open_context(tmp_path) as ctx:

        async def long_transaction(_db: aiosqlite.Connection) -> None:
            await asyncio.sleep(2.5 * budget_ms / 1000)

        holding = asyncio.create_task(
            transactions.in_one_transaction(
                ctx.store.connection, long_transaction, failure=transactions.propagate
            )
        )
        await asyncio.sleep(0.05)
        started = time.monotonic()
        refused = error_of(await call(ctx, "memory_remember", {"gist": "g", "content": "c"}))
        elapsed = time.monotonic() - started
        await holding
        assert refused == (_STORE_BUSY, {"verb": "memory_remember"}), refused
        assert 0.8 * budget_ms / 1000 <= elapsed <= 1.4 * budget_ms / 1000, elapsed


async def _close_the_writer_on_the_next_failed_commit(
    monkeypatch: pytest.MonkeyPatch, ctx: ServiceContext, *, hold_seconds: float = 0.0
) -> None:
    """Make the next commit on the writer fail and its rollback fail too, so `finalize` closes the
    handle — the one path by which a connection the service holds stops working."""
    db = ctx.store.connection
    real_commit = transactions.commit_or_roll_back
    real_rollback = db.rollback
    armed = True

    async def failing_commit(connection: aiosqlite.Connection, error: BaseException | None) -> None:
        nonlocal armed
        if connection is db and armed:
            armed = False
            await asyncio.sleep(hold_seconds)
            raise aiosqlite.OperationalError("disk I/O error")
        await real_commit(connection, error)

    async def failing_rollback() -> None:
        if not holders.holder_of(db).closed:
            raise aiosqlite.OperationalError("disk I/O error")
        await real_rollback()

    monkeypatch.setattr(transactions, "commit_or_roll_back", failing_commit)
    monkeypatch.setattr(db, "rollback", failing_rollback)


async def test_a_writer_a_failed_rollback_closed_is_replaced_for_the_next_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with open_context(tmp_path) as ctx:
        closed = ctx.store.connection
        await _close_the_writer_on_the_next_failed_commit(monkeypatch, ctx)
        failed = error_of(await call(ctx, "memory_remember", {"gist": "g", "content": "c"}))
        assert failed is not None
        assert holders.holder_of(closed).closed

        answered = await call(ctx, "memory_remember", {"gist": "g2", "content": "c2"})
        assert error_of(answered) is None, answered
        assert ctx.store.connection is not closed


async def test_two_writes_into_the_gap_share_one_reopened_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two writes dispatched after the close both succeed, over one reopen — a second would be
    abandoned with a live worker thread, which the suite's leak check fails on."""
    async with open_context(tmp_path) as ctx:
        await _close_the_writer_on_the_next_failed_commit(monkeypatch, ctx)
        await call(ctx, "memory_remember", {"gist": "g", "content": "c"})
        opened: list[aiosqlite.Connection] = []
        real_open = Store._open_checked

        async def counted(self: Store) -> aiosqlite.Connection:
            connection = await real_open(self)
            opened.append(connection)
            return connection

        monkeypatch.setattr(Store, "_open_checked", counted)
        answers = await asyncio.gather(
            call(ctx, "memory_remember", {"gist": "g2", "content": "c2"}),
            call(ctx, "memory_remember", {"gist": "g3", "content": "c3"}),
        )
        assert [error_of(answer) for answer in answers] == [None, None], answers
        assert opened == [ctx.store.connection]


async def test_a_write_queued_when_the_writer_closed_answers_store_busy_and_ran_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with open_context(tmp_path) as ctx:
        await _close_the_writer_on_the_next_failed_commit(monkeypatch, ctx, hold_seconds=0.3)
        closing = asyncio.create_task(
            call(ctx, "memory_remember", {"gist": "closing", "content": "c"})
        )
        await asyncio.sleep(0.1)
        queued = await call(ctx, "memory_remember", {"gist": "queued", "content": "c"})
        await closing
        refused = error_of(queued)
        assert refused == (_STORE_BUSY, {"verb": "memory_remember"}), queued
        gists = await (await ctx.store.writer()).execute_fetchall("SELECT gist FROM memory")
        assert "queued" not in {str(gist) for (gist,) in gists}


def _replace_the_store_file(ctx: ServiceContext) -> None:
    """Move `memory.db` aside and put a copy back at its path: same content, a different inode."""
    path = ctx.store.path
    aside = path.with_suffix(".aside")
    path.rename(aside)
    shutil.copy2(aside, path)


@pytest.mark.parametrize(
    ("method", "params", "answered"),
    [
        ("knowledge_list", {}, _STORE_UNAVAILABLE),
        ("memory_search", {"query": "q"}, _INTERNAL_ERROR),
    ],
)
async def test_a_connection_opened_onto_a_replaced_store_is_refused_by_its_family(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    method: str,
    params: dict[str, object],
    answered: int,
) -> None:
    """A read's first pool connection opens after startup; opened onto a replacement it would read
    one file while the writer writes another. A knowledge verb answers `store_unavailable`, a memory
    verb `internal_error` with a log line naming the drift."""
    async with open_context(tmp_path) as ctx:
        _replace_the_store_file(ctx)
        refused = error_of(await call(ctx, method, params))
        assert refused is not None, refused
        assert refused[0] == answered, refused
        if answered == _INTERNAL_ERROR:
            assert "was replaced since the service opened it" in caplog.text


async def test_a_connection_opened_onto_an_absent_store_is_refused_too(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        ctx.store.path.rename(ctx.store.path.with_suffix(".aside"))
        refused = error_of(await call(ctx, "knowledge_list", {}))
        assert refused is not None, refused
        assert refused[0] == _STORE_UNAVAILABLE, refused
        assert "is gone since the service opened it" in str(refused[1]["cause"])


async def _registry_exists(ctx: ServiceContext) -> bool:
    rows = await ctx.store.connection.execute_fetchall(
        "SELECT 1 FROM sqlite_master WHERE name = 'knowledge_bases'"
    )
    return bool(list(rows))


@pytest.mark.parametrize(
    ("method", "params", "answered"),
    [
        ("knowledge_list", {}, None),
        ("knowledge_search", {"query": "q"}, None),
        ("knowledge_refresh", {}, None),
        ("knowledge_status", {"knowledge_base": "docs"}, -32040),
        ("knowledge_unlock", {"knowledge_base": "docs"}, -32040),
        ("knowledge_refresh", {"name": "docs"}, -32040),
        ("knowledge_rename", {"name": "docs", "new_name": "notes"}, -32040),
        ("knowledge_remove", {"name": "docs", "confirm": True}, -32040),
    ],
)
async def test_a_store_without_the_registry_answers_as_an_empty_one_and_stays_without_it(
    tmp_path: Path, method: str, params: dict[str, object], answered: int | None
) -> None:
    """No read writes DDL — a presence read followed by a `CREATE` on a pool connection is the
    stale-snapshot failure's shape on the read path — and neither does a write with nothing to act
    on."""
    async with open_context(tmp_path) as ctx:
        response = await call(ctx, method, params)
        refused = error_of(response)
        assert (None if refused is None else refused[0]) == answered, response
        assert not await _registry_exists(ctx)


async def test_a_knowledge_writes_registry_read_sees_nothing_of_another_handlers_open_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the writer a statement outside a transaction would run inside whichever request's
    transaction is open there and read its uncommitted rows. So the registry read is a transaction
    of its own: it waits for the open one, which rolls back here, and finds nothing — where a bare
    read would have found the row and asked to confirm destroying a corpus that never existed."""
    async with open_context(tmp_path) as ctx:
        real_insert = registry.insert
        inserted = asyncio.Event()

        async def insert_then_fail(db: aiosqlite.Connection, **options: object) -> object:
            await real_insert(db, **options)  # type: ignore[arg-type]
            inserted.set()
            await asyncio.sleep(0.2)
            raise RuntimeError("the add fails after its insert, inside its transaction")

        monkeypatch.setattr(registry, "insert", insert_then_fail)
        root = tmp_path / "docs"
        root.mkdir()
        adding = asyncio.create_task(
            call(
                ctx,
                "knowledge_add",
                {"name": "docs", "path": str(root), "description": "a corpus"},
            )
        )
        await inserted.wait()
        preview = error_of(await call(ctx, "knowledge_remove", {"name": "docs"}))
        added = error_of(await adding)
        assert added is not None, added
        assert added[0] == _INTERNAL_ERROR, added
        assert preview is not None, preview
        assert preview[0] == -32040, preview


async def test_a_knowledge_write_opens_no_corpus_while_it_holds_the_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the registry statements are in the transaction; every corpus open follows it, or the
    writer's lock would be held across one open per corpus."""
    async with open_context(tmp_path) as ctx:
        root = tmp_path / "docs"
        root.mkdir()
        (root / "a.md").write_bytes(b"alpha\n")
        await call(ctx, "knowledge_add", {"name": "docs", "path": str(root), "description": "d"})
        real_open = KnowledgeDatabase.open
        writer_in_transaction: list[bool] = []

        async def recording_open(*args: object, **options: object) -> KnowledgeDatabase:
            writer_in_transaction.append((await ctx.store.writer()).in_transaction)
            return await real_open(*args, **options)  # type: ignore[arg-type]

        monkeypatch.setattr(KnowledgeDatabase, "open", staticmethod(recording_open))
        await call(ctx, "knowledge_remove", {"name": "docs"})
        await call(ctx, "knowledge_rename", {"name": "docs", "new_name": "notes"})
        assert writer_in_transaction, "no corpus was opened, so this tested nothing"
        assert not any(writer_in_transaction)
