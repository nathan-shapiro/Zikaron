"""At most one indexer per knowledge base: who may take the lock, and who may take it over.

The reclaim rule is the interesting half, and it is deliberately weaker than the consolidation
lease's: a wrongly reclaimed indexer costs one rescan, where a wrongly displaced consolidator
costs a worker's reasoning. Weaker in one direction only — a lock recorded by another host is
never reclaimed here at all.
"""

import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from tests.knowledge_fixtures import config_for, corpus_root, open_store
from zikaron.core.knowledge import database, lock, meta
from zikaron.core.knowledge.database import KnowledgeDatabase, NewKnowledgeBase, seed_identity
from zikaron.core.knowledge.errors import IndexerBusyError
from zikaron.core.knowledge.registry import KnowledgeBase, ensure_table, insert
from zikaron.core.store.transactions import in_one_transaction, propagate

_NOW = "2026-01-01T00:00:00+00:00"
#: A pid that no process can have, so "not alive" is a fact rather than a race with the scheduler.
_DEAD_PID = 2**22 + 7
#: The init process: always running, and owned by root, so an ordinary user is refused permission
#: to signal it rather than told it does not exist.
_INIT_PID = 1


def _rows(pid: object = 4242, host: str = "somewhere", started: str = _NOW) -> dict[str, str]:
    return {
        meta.LOCK_PID_KEY: str(pid),
        meta.LOCK_HOST_KEY: host,
        meta.LOCK_STARTED_AT_KEY: started,
    }


class TestReadingALock:
    def test_no_rows_is_no_holder(self) -> None:
        assert lock.read({}) is None
        assert not lock.is_held({})

    def test_the_recorded_pid_is_what_says_a_lock_exists(self) -> None:
        """Presence rather than liveness: acting as though a lock were absent while a writer holds
        it is the unrecoverable direction."""
        assert lock.is_held({meta.LOCK_PID_KEY: "4242"})

    def test_a_holder_comes_back_with_everything_recorded(self) -> None:
        holder = lock.read(_rows(pid=99, host="box", started=_NOW))
        assert holder == lock.LockHolder(pid=99, host="box", started_at=_NOW)

    def test_a_pid_that_is_not_a_number_still_counts_as_held(self) -> None:
        """A row edited by hand. Reading it as *no lock* would let a scan start beside whatever
        wrote it, so the unreadable pid is carried rather than discarded."""
        holder = lock.read(_rows(pid="not-a-pid"))
        assert holder is not None
        assert holder.pid is None

    def test_a_partially_written_lock_still_counts_as_held(self) -> None:
        holder = lock.read({meta.LOCK_PID_KEY: "4242"})
        assert holder is not None
        assert (holder.host, holder.started_at) == ("", "")

    def test_an_unreadable_holder_describes_itself_without_pretending(self) -> None:
        holder = lock.read({meta.LOCK_PID_KEY: "not-a-pid"})
        assert holder is not None
        assert "unreadable pid" in holder.describe()


class TestWhoMayTakeItOver:
    def test_a_dead_process_on_this_host_is_reclaimable(self) -> None:
        holder = lock.LockHolder(pid=_DEAD_PID, host=lock.this_host(), started_at=_NOW)
        assert lock.is_reclaimable(holder, host=lock.this_host())

    def test_a_live_process_on_this_host_is_not(self) -> None:
        holder = lock.LockHolder(pid=os.getpid(), host=lock.this_host(), started_at=_NOW)
        assert not lock.is_reclaimable(holder, host=lock.this_host())

    def test_another_host_is_never_reclaimable_however_dead_its_pid_looks(self) -> None:
        """A local process probe says nothing about a foreign one, and the reading that says
        *reclaim it* is the one that lets two indexers write one database."""
        holder = lock.LockHolder(pid=_DEAD_PID, host="another-machine", started_at=_NOW)
        assert not lock.is_reclaimable(holder, host=lock.this_host())

    def test_an_unreadable_pid_is_never_reclaimable(self) -> None:
        holder = lock.LockHolder(pid=None, host=lock.this_host(), started_at=_NOW)
        assert not lock.is_reclaimable(holder, host=lock.this_host())

    @pytest.mark.parametrize("pid", [0, -1])
    def test_a_pid_that_names_no_process_is_not_alive(self, pid: int) -> None:
        """Zero and the negatives address a process *group* rather than a process, so they are
        refused rather than probed."""
        holder = lock.LockHolder(pid=pid, host=lock.this_host(), started_at=_NOW)
        assert lock.is_reclaimable(holder, host=lock.this_host())

    @pytest.mark.skipif(os.getuid() == 0, reason="running as root, which may signal any process")
    def test_a_process_this_user_may_not_signal_is_alive_rather_than_gone(self) -> None:
        """Being refused permission to signal a process is evidence it *exists*, and reading it as
        absence would reclaim a lock from a live indexer running as somebody else."""
        holder = lock.LockHolder(pid=_INIT_PID, host=lock.this_host(), started_at=_NOW)
        assert not lock.is_reclaimable(holder, host=lock.this_host())


class TestTheLivenessProbeAndItsTwoReadings:
    """One probe, two questions. *May I take this over* and *can I show the holder is running* are
    both strictly narrower than the negation of the other, and the gap between them is every lock
    the probe cannot answer for — a foreign host, or a pid that is not a number. A caller that
    collapsed the two would either start a second indexer beside a live one or refuse a knowledge
    base for good."""

    @pytest.mark.parametrize(
        ("holder", "expected"),
        [
            (lock.LockHolder(pid=os.getpid(), host=lock.this_host(), started_at=_NOW), True),
            (lock.LockHolder(pid=_DEAD_PID, host=lock.this_host(), started_at=_NOW), False),
            (lock.LockHolder(pid=_DEAD_PID, host="another-machine", started_at=_NOW), None),
            (lock.LockHolder(pid=None, host=lock.this_host(), started_at=_NOW), None),
        ],
        ids=["local and running", "local and gone", "foreign", "unreadable pid"],
    )
    def test_the_probe_answers_none_wherever_it_cannot_tell(
        self, holder: lock.LockHolder, expected: bool | None
    ) -> None:
        assert lock.probe(holder, host=lock.this_host()) is expected

    def test_a_foreign_lock_is_neither_reclaimable_nor_provably_live(self) -> None:
        holder = lock.LockHolder(pid=_DEAD_PID, host="another-machine", started_at=_NOW)
        assert not lock.is_reclaimable(holder, host=lock.this_host())
        assert not lock.is_provably_live(holder, host=lock.this_host())

    def test_only_a_local_running_process_is_provably_live(self) -> None:
        here = lock.this_host()
        assert lock.is_provably_live(
            lock.LockHolder(pid=os.getpid(), host=here, started_at=_NOW), host=here
        )
        assert not lock.is_provably_live(
            lock.LockHolder(pid=_DEAD_PID, host=here, started_at=_NOW), host=here
        )

    def test_nothing_blocks_a_build_when_no_lock_is_recorded(self) -> None:
        assert lock.running_holder({}, host=lock.this_host()) is None

    def test_a_lock_a_crashed_indexer_left_blocks_nothing(self) -> None:
        """Those rows survive on purpose. Treating them as a live writer would make one dead
        process enough to make a knowledge base unbuildable and unremovable at once."""
        rows = _rows(pid=_DEAD_PID, host=lock.this_host())
        assert lock.running_holder(rows, host=lock.this_host()) is None

    @pytest.mark.parametrize(
        "rows",
        [
            _rows(pid=os.getpid(), host=lock.this_host()),
            _rows(pid=_DEAD_PID, host="another-machine"),
            _rows(pid="not-a-pid", host=lock.this_host()),
        ],
        ids=["local and running", "foreign", "unreadable pid"],
    )
    def test_every_lock_that_cannot_be_shown_dead_blocks(self, rows: dict[str, str]) -> None:
        assert lock.running_holder(rows, host=lock.this_host()) is not None


@pytest.fixture
async def knowledge_db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """One registered knowledge base's own connection, which is where a lock lives."""
    async with open_store(tmp_path) as (store_dir, memory_db):
        config = config_for(tmp_path)

        async def _register(connection: aiosqlite.Connection) -> KnowledgeBase:
            await ensure_table(connection)
            return await insert(connection, name="docs", description="a corpus", created_at=_NOW)

        registered = await in_one_transaction(memory_db, _register, failure=propagate)
        spec = NewKnowledgeBase(
            name=registered.name, root=corpus_root(tmp_path), description="a corpus"
        )
        async with await KnowledgeDatabase.create(
            store_dir, seed_identity(registered.id, spec, config)
        ) as opened:
            yield opened.connection


class TestTakingAndReleasing:
    async def test_taking_a_free_lock_records_this_process(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await lock.acquire(knowledge_db, pid=os.getpid(), host=lock.this_host(), started_at=_NOW)
        holder = lock.read(await database.read_meta(knowledge_db))
        assert holder == lock.LockHolder(pid=os.getpid(), host=lock.this_host(), started_at=_NOW)

    async def test_a_live_holder_refuses_the_next_taker(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await lock.acquire(knowledge_db, pid=os.getpid(), host=lock.this_host(), started_at=_NOW)
        with pytest.raises(IndexerBusyError, match="already running"):
            await lock.acquire(
                knowledge_db, pid=os.getpid(), host=lock.this_host(), started_at=_NOW
            )

    async def test_a_dead_holder_on_this_host_is_taken_over(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await lock.acquire(knowledge_db, pid=_DEAD_PID, host=lock.this_host(), started_at=_NOW)
        await lock.acquire(knowledge_db, pid=os.getpid(), host=lock.this_host(), started_at=_NOW)
        holder = lock.read(await database.read_meta(knowledge_db))
        assert holder is not None
        assert holder.pid == os.getpid()

    async def test_a_foreign_holder_refuses_and_says_since_when(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """Nothing here can show a foreign holder is dead, so the age is reported for a human who
        can judge what this one is worth."""
        await database.write_meta(knowledge_db, _rows(pid=_DEAD_PID, host="another-machine"))
        with pytest.raises(IndexerBusyError, match=re.escape(f"another-machine, since {_NOW}")):
            await lock.acquire(
                knowledge_db, pid=os.getpid(), host=lock.this_host(), started_at=_NOW
            )

    async def test_releasing_clears_every_row_the_holder_wrote(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await lock.acquire(knowledge_db, pid=os.getpid(), host=lock.this_host(), started_at=_NOW)
        await lock.release(knowledge_db)
        raw = await database.read_meta(knowledge_db)
        assert not any(key in raw for key in lock.LOCK_KEYS)

    async def test_releasing_a_lock_nobody_holds_is_not_an_error(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """It runs from the path that unwinds a failed scan as well as a successful one, so it has
        to be safe on a knowledge base whose lock was never taken."""
        await lock.release(knowledge_db)
        assert not lock.is_held(await database.read_meta(knowledge_db))


class TestClearingALockByHand:
    """The exit from a lock nothing clears on its own. Automatic reclamation is same-host only, so
    a crash on another machine leaves a knowledge base every verb refuses and no clock runs out on.
    This moves that judgement to whoever can see what is running, and declines only where a process
    on this host answers to the recorded pid."""

    async def test_a_foreign_lock_is_cleared_and_reported(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await database.write_meta(knowledge_db, _rows(pid=_DEAD_PID, host="another-machine"))
        cleared = await lock.force_release(knowledge_db, host=lock.this_host())
        assert cleared == lock.LockHolder(pid=_DEAD_PID, host="another-machine", started_at=_NOW)
        assert not lock.is_held(await database.read_meta(knowledge_db))

    async def test_a_lock_whose_pid_cannot_be_read_is_cleared(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """No other path resolves it: it is never reclaimable, and nothing can probe a pid that is
        not a number. Leaving it would make a hand-edited row permanent."""
        await database.write_meta(knowledge_db, _rows(pid="not-a-pid", host=lock.this_host()))
        assert await lock.force_release(knowledge_db, host=lock.this_host()) is not None
        assert not lock.is_held(await database.read_meta(knowledge_db))

    async def test_a_dead_local_lock_is_cleared_even_though_a_build_would_reclaim_it(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await database.write_meta(knowledge_db, _rows(pid=_DEAD_PID, host=lock.this_host()))
        assert await lock.force_release(knowledge_db, host=lock.this_host()) is not None
        assert not lock.is_held(await database.read_meta(knowledge_db))

    async def test_a_running_local_holder_is_refused_and_keeps_its_lock(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await lock.acquire(knowledge_db, pid=os.getpid(), host=lock.this_host(), started_at=_NOW)
        with pytest.raises(IndexerBusyError, match="still answers to the lock"):
            await lock.force_release(knowledge_db, host=lock.this_host())
        assert lock.is_held(await database.read_meta(knowledge_db))

    async def test_no_lock_at_all_is_reported_rather_than_refused(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """An operator reaching for this cannot see whether a lock is still there, which is the
        whole reason they are reaching for it."""
        assert await lock.force_release(knowledge_db, host=lock.this_host()) is None
