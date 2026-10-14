"""A build waits out another writer's brief hold on its corpus rather than ending.

`knowledge-index.md` §6.2 is normative. Every transaction a build opens reads before it writes, and
SQLite refuses a deferred one at its first write whenever another connection holds the write lock
or has committed since its read began, without consulting `busy_timeout`. Two writers reach a
corpus while it builds — a second build's lock acquisition and a search's counter write — so each
of a build's transactions opens `IMMEDIATE` and waits instead. The operator's lock clearing reads
then deletes, and opens `IMMEDIATE` for the same reason.

Each interleaving here is pinned rather than timed, so a build that does not wait fails every run.
"""

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from pathlib import Path

import aiosqlite
import pytest

from tests.knowledge_fixtures import (
    DEAD_PID,
    Corpus,
    add_request,
    build_settings,
    open_corpus,
    write_meta,
)
from zikaron.core.knowledge import database, ddl, disposal, lifecycle, lock, meta, scan, writes
from zikaron.core.knowledge.counters import SearchTally, record_search
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.paths import knowledge_db_path
from zikaron.core.knowledge.registry import require
from zikaron.core.store.connection import open_connection


@asynccontextmanager
async def _corpus(tmp_path: Path) -> AsyncIterator[Corpus]:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_bytes(b"alpha\n")
    (root / "b.md").write_bytes(b"beta\n")
    async with open_corpus(tmp_path, add_request(root, git_mode=meta.GitMode.OFF)) as corpus:
        yield corpus


async def _db_path(corpus: Corpus) -> Path:
    return knowledge_db_path(corpus.store_dir, (await require(corpus.db, corpus.name)).id)


async def _scan(corpus: Corpus, statements: list[str] | None = None) -> scan.ScanResult:
    registered = await require(corpus.db, corpus.name)
    async with await KnowledgeDatabase.open(
        corpus.store_dir, registered.id, migrate=True
    ) as opened:
        if statements is not None:
            await opened.connection.set_trace_callback(statements.append)
        return await scan.run(opened, build_settings(corpus.config))


async def _count_a_search(db_path: Path) -> bool:
    """A search's counter write, on a connection of its own, as the service makes one."""
    db, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS, existing_only=True)
    try:
        return await record_search(db, SearchTally(results=1, stale=0))
    finally:
        await db.close()


async def test_a_writer_holding_the_lock_as_the_index_phase_begins_is_waited_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another connection takes the write lock as the index phase begins, and lets it go once the
    build's first transaction there has either begun waiting for it or ended — well inside the
    build's `busy_timeout`."""
    async with _corpus(tmp_path) as corpus:
        db_path = await _db_path(corpus)
        loop = asyncio.get_running_loop()
        real_run = disposal.run
        with closing(sqlite3.connect(db_path, isolation_level=None)) as other:
            holding = False

            def let_go() -> None:
                nonlocal holding
                if holding:
                    other.execute("COMMIT")
                    holding = False

            def on_statement(statement: str) -> None:
                if statement == "BEGIN IMMEDIATE":
                    loop.call_later(0.2, let_go)
                elif statement in {"COMMIT", "ROLLBACK"}:
                    let_go()

            async def held_index_phase(db: aiosqlite.Connection, *args: object) -> int:
                nonlocal holding
                other.execute("BEGIN IMMEDIATE")
                holding = True
                await db.set_trace_callback(
                    lambda statement: loop.call_soon_threadsafe(on_statement, statement)
                )
                return await real_run(db, *args)  # type: ignore[arg-type]

            monkeypatch.setattr(disposal, "run", held_index_phase)
            try:
                result = await _scan(corpus)
            finally:
                let_go()
    assert result.counters.files_indexed == 2
    assert result.files_remaining == 0


async def test_a_search_counted_between_a_builds_read_and_its_write_does_not_end_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counter write lands after the per-file transaction's first read and before its first
    write. Waited for, it is refused, which is the counter's own contract: it never waits."""
    async with _corpus(tmp_path) as corpus:
        db_path = await _db_path(corpus)
        real_stored = writes._stored_chunks
        counted: list[bool] = []

        async def stored_then_searched(
            db: aiosqlite.Connection, path: str
        ) -> tuple[writes._StoredChunk, ...]:
            stored = await real_stored(db, path)
            counted.append(await _count_a_search(db_path))
            return stored

        monkeypatch.setattr(writes, "_stored_chunks", stored_then_searched)
        result = await _scan(corpus)
    assert result.counters.files_indexed == 2
    assert counted == [False, False]


async def test_invariant_18_every_begin_a_build_issues_is_immediate(tmp_path: Path) -> None:
    """Over two builds, the second of which reindexes one file, deletes one and skips one."""
    async with _corpus(tmp_path) as corpus:
        statements: list[str] = []
        await _scan(corpus, statements)
        (corpus.root / "a.md").write_bytes(b"alpha, again\n")
        (corpus.root / "b.md").unlink()
        (corpus.root / "c.md").write_bytes(b"\x00\x01\x02binary\n")
        second = await _scan(corpus, statements)
    assert second.files_deleted == 1
    assert second.counters.files_skipped == 1
    begins = [s for s in statements if s.split(maxsplit=1)[0].upper() in {"BEGIN", "SAVEPOINT"}]
    assert begins
    assert set(begins) == {"BEGIN IMMEDIATE"}


async def test_clearing_a_lock_waits_out_a_search_counted_between_its_read_and_its_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _corpus(tmp_path) as corpus:
        db_path = await _db_path(corpus)
        await write_meta(
            db_path,
            **{
                meta.LOCK_PID_KEY: str(DEAD_PID),
                meta.LOCK_HOST_KEY: lock.this_host(),
                meta.LOCK_STARTED_AT_KEY: "2026-01-01T00:00:00+00:00",
            },
        )
        real_clear = database.clear_meta
        counted: list[bool] = []

        async def searched_then_cleared(db: aiosqlite.Connection, keys: tuple[str, ...]) -> None:
            counted.append(await _count_a_search(db_path))
            await real_clear(db, keys)

        monkeypatch.setattr(database, "clear_meta", searched_then_cleared)
        cleared = await lifecycle.unlock(
            corpus.store_dir, corpus.db, name=corpus.name, migrate=True
        )
    assert cleared is not None
    assert cleared.pid == DEAD_PID
    assert counted == [False]
