"""Two builds reaching one corpus's lock together: the loser is refused as busy, not by the driver.

`knowledge-index.md` §"6. The indexer process" is normative. A build first reads the holder with no
transaction and refuses at once on a live one; only a build that saw *no holder* opens `BEGIN
IMMEDIATE` and reads again. So the second of two simultaneous builds waits for the first's short
acquisition to commit, reads it, and refuses `IndexerBusyError` — where a deferred acquisition let
both read *no holder* and the loser met `database is locked` instead.

Driven through `scan.run` directly: the build's own pre-checks refuse a committed holder before
the scan starts, and what is under test is the acquisition inside it.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import pytest

from tests.knowledge_fixtures import Corpus, add_request, build_settings, open_corpus
from zikaron.core.knowledge import disposal, lock, scan
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.errors import IndexerBusyError
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.knowledge.registry import require


@asynccontextmanager
async def _corpus(tmp_path: Path) -> AsyncIterator[Corpus]:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_bytes(b"alpha\n")
    async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
        yield corpus


async def _scan(corpus: Corpus) -> scan.ScanResult:
    registered = await require(corpus.db, corpus.name)
    async with await KnowledgeDatabase.open(corpus.store_dir, registered.id) as opened:
        return await scan.run(opened, build_settings(corpus.config))


async def test_the_second_of_two_simultaneous_acquisitions_is_refused_as_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One acquisition's transaction is held open — for well under the corpus connection's
    `busy_timeout` — while the other attempts its own. The first build is then kept in its index
    phase, holding no transaction, until the second has answered: a first build that finished
    meanwhile would have released the lock, and the second would rightly take it."""
    async with _corpus(tmp_path) as corpus:
        real_acquire = lock.acquire
        real_run = disposal.run
        acquiring = asyncio.Event()
        release_acquisition = asyncio.Event()
        release_index_phase = asyncio.Event()
        calls = 0

        async def held_acquire(db: aiosqlite.Connection, **options: object) -> None:
            nonlocal calls
            calls += 1
            await real_acquire(db, **options)  # type: ignore[arg-type]
            if calls == 1:
                acquiring.set()
                await release_acquisition.wait()

        async def held_index_phase(db: aiosqlite.Connection, *args: object) -> int:
            await release_index_phase.wait()
            return await real_run(db, *args)  # type: ignore[arg-type]

        monkeypatch.setattr(lock, "acquire", held_acquire)
        monkeypatch.setattr(disposal, "run", held_index_phase)
        first = asyncio.create_task(_scan(corpus))
        await acquiring.wait()
        second = asyncio.create_task(_scan(corpus))
        await asyncio.sleep(0.2)
        release_acquisition.set()
        with pytest.raises(IndexerBusyError):
            await second
        release_index_phase.set()
        await first


async def test_a_build_arriving_during_the_winners_index_phase_is_refused_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fast read refuses a live holder without waiting. Opening `IMMEDIATE` on every
    acquisition would wait out the winner's current transaction instead."""
    async with _corpus(tmp_path) as corpus:
        real_run = disposal.run
        indexing = asyncio.Event()
        release = asyncio.Event()

        async def held_index_phase(db: aiosqlite.Connection, *args: object) -> int:
            await db.execute("BEGIN IMMEDIATE")
            indexing.set()
            await release.wait()
            await db.rollback()
            return await real_run(db, *args)  # type: ignore[arg-type]

        monkeypatch.setattr(disposal, "run", held_index_phase)
        winner = asyncio.create_task(_scan(corpus))
        await indexing.wait()
        started = time.monotonic()
        with pytest.raises(IndexerBusyError):
            await _scan(corpus)
        elapsed = time.monotonic() - started
        release.set()
        await winner
        assert elapsed < 0.5, elapsed
