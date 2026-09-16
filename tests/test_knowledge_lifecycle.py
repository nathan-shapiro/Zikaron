"""The verbs that change a knowledge base, and the interrupted states their ordering produces.

The whole point of mutating the registry before the file, in both directions, is that each
interruption lands in the better of its two possible states — and both of those are asserted here
rather than argued for in prose: an interrupted `add` leaves a name one `remove` clears, and an
interrupted `remove` leaves a file nothing opens.
"""

import os
import sqlite3
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.knowledge_fixtures import add_base, config_for, corpus_root, open_store
from zikaron.core.knowledge import (
    builds,
    database,
    ddl,
    lifecycle,
    lock,
    meta,
    paths,
    registry,
    reporting,
)
from zikaron.core.knowledge.errors import (
    DanglingKnowledgeBaseError,
    DuplicateNameError,
    IndexerBusyError,
    InvalidNameError,
    InvalidRootError,
    InvalidSettingError,
    UnknownKnowledgeBaseError,
)
from zikaron.core.knowledge.state import KnowledgeState
from zikaron.core.store.connection import open_connection
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.core.store.transactions import in_one_transaction

#: A pid no process can have, so *not running* is a fact rather than a race with the scheduler.
_DEAD_PID: Final = 2**22 + 7


class TestTheWholeLifecycle:
    async def test_a_knowledge_base_survives_create_rename_list_and_remove(
        self, tmp_path: Path
    ) -> None:
        """The milestone's headline clause, asserted end to end with the file watched throughout —
        it has to appear on create and be gone after remove, since a registry that agreed with
        itself while the filesystem did not is exactly the desync this ordering exists to bound."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = corpus_root(tmp_path)

            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="Design Docs", root=root, description="records"),
            )
            assert created.database_path.is_file()
            assert created.knowledge_base.name == "design docs"

            renamed = await lifecycle.rename(
                store_dir, db, config, name="design docs", new_name="Design Records"
            )
            assert renamed.summary.name == "design records"
            assert created.database_path.is_file(), "a rename must touch no file"

            listing = await reporting.list_bases(store_dir, db, config)
            (listed,) = listing.knowledge_bases
            assert listed.summary.name == "design records"
            assert listed.summary.description == "records"

            removed = await lifecycle.remove(store_dir, db, config, name="design records")
            assert removed.knowledge_base.name == "design records"
            assert not created.database_path.exists()
            assert (await reporting.list_bases(store_dir, db, config)).knowledge_bases == ()

    async def test_remove_leaves_no_file_of_that_knowledge_base_behind(
        self, tmp_path: Path
    ) -> None:
        """In WAL mode a live database is three files, and a journal left behind would be inherited
        by whatever is created at that path next. So the property asserted is the postcondition —
        nothing named for this corpus survives — rather than a count of unlink calls.

        The count would in fact be misleading. Reading a knowledge base's state opens and closes
        it, and SQLite reclaims its own `-wal` and `-shm` on the last close, so by the time the
        unlink runs there is usually only one file left to remove. `files_unlinked` reports what
        was actually there, which is why it is normally one rather than three.
        """
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            stem = created.database_path.name

            removed = await lifecycle.remove(store_dir, db, config, name="docs")

            assert removed.files_unlinked, "remove must report what it destroyed"
            survivors = [
                path.name
                for path in paths.knowledge_dir(store_dir).iterdir()
                if path.name.startswith(stem)
            ]
            assert survivors == []

    async def test_remove_reports_a_final_snapshot_of_what_it_destroyed(
        self, tmp_path: Path
    ) -> None:
        """Its corpus no longer exists to poll, so the snapshot is the only record the caller
        gets — and it is taken before the row is deleted, not reconstructed after."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="what"),
            )
            removed = await lifecycle.remove(store_dir, db, config, name="docs")
            assert removed.status.summary.description == "what"
            assert removed.status.details is not None


class TestTheInterruptedStates:
    async def test_an_interrupted_add_leaves_a_knowledge_base_needing_a_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A crash between the registry commit and the file creation. Simulated by failing the
        creation itself, which is the same interruption from the registry's point of view: the row
        is committed and no file exists."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            request = lifecycle.AddRequest(
                name="docs",
                root=corpus_root(tmp_path),
                description="a",
                home=tmp_path / "not-home",
            )

            async def _die(*_args: object, **_kwargs: object) -> None:
                raise OSError("interrupted between the registry commit and the file")

            monkeypatch.setattr(database.KnowledgeDatabase, "create", _die)
            with pytest.raises(OSError, match="interrupted"):
                await lifecycle.add(store_dir, db, config, request)
            monkeypatch.undo()

            listing = await reporting.list_bases(store_dir, db, config)
            (report,) = listing.knowledge_bases
            assert report.summary.state is KnowledgeState.REINDEX_REQUIRED
            assert report.summary.files_indexed == 0
            assert listing.orphans == (), "an interrupted add must not leave an orphan"

    async def test_a_create_that_fails_after_making_the_file_still_leaves_the_absent_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The third interrupted state, and why it is folded into the first.

        Connecting to a knowledge base's database *creates the file*, before any table is in it. So
        a failure between those two points leaves a registered name pointing at an empty database —
        which reads back as *this index cannot be opened*, the one state an operator is told to
        look at by hand, for a condition removing the name and adding it again fixes entirely.
        Creation removes what it made, and the result must be the absent-database state instead:
        the same remedy, with nothing to diagnose first.
        """
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            broken = (*ddl.FIXED_STATEMENTS, "CREATE TABLE this is not valid sql")
            monkeypatch.setattr(ddl, "FIXED_STATEMENTS", broken)

            with pytest.raises(aiosqlite.Error):
                await add_base(
                    store_dir,
                    db,
                    config,
                    lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
                )
            monkeypatch.undo()

            listing = await reporting.list_bases(store_dir, db, config)
            (report,) = listing.knowledge_bases
            assert report.summary.state is KnowledgeState.REINDEX_REQUIRED, (
                "a failed create must not leave a knowledge base reporting an unreadable index"
            )
            assert listing.orphans == ()
            assert paths.orphan_candidates(store_dir) == ()

    async def test_an_interrupted_remove_leaves_an_orphan_that_status_reports(
        self, tmp_path: Path
    ) -> None:
        """A crash between the registry commit and the unlink. The file is unreferenced, reported,
        and never opened by anything that answers a query."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )

            async def _work(connection: aiosqlite.Connection) -> registry.KnowledgeBase:
                return await registry.delete(connection, name="docs")

            await in_one_transaction(db, _work, failure=lambda _error: None)

            listing = await reporting.status(store_dir, db, config)
            assert listing.knowledge_bases == ()
            (orphan,) = listing.orphans
            assert orphan.path == created.database_path
            assert orphan.breadcrumb_name == "docs"

    async def test_remove_commits_the_registry_row_before_it_unlinks_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ordering decision itself, which is otherwise invisible: both orders reach the same
        end state when nothing goes wrong, and differ only in what an interruption leaves behind.

        Forced by failing the unlink, which is the step after the commit. Under the order this
        module chose, that leaves a file nothing references — an orphan, reported and inert. Under
        the reverse, the same interruption would leave a **name with no file** — a knowledge base
        that still answers for a corpus the caller had asked to destroy, which no build can rebuild
        and only another `remove` can clear.
        """
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )

            def _refuse(_path: Path) -> bool:
                raise OSError("interrupted between the registry commit and the unlink")

            monkeypatch.setattr(lifecycle, "_unlink_if_present", _refuse)
            with pytest.raises(OSError, match="interrupted"):
                await lifecycle.remove(store_dir, db, config, name="docs")

            assert await registry.find(db, "docs") is None, (
                "the registry row must already be committed when the unlink runs"
            )
            assert created.database_path.is_file(), "the file survives as an orphan"

            monkeypatch.undo()
            listing = await reporting.list_bases(store_dir, db, config)
            assert listing.knowledge_bases == ()
            assert [orphan.path for orphan in listing.orphans] == [created.database_path]

    async def test_orphans_are_reported_only_when_no_name_was_given(self, tmp_path: Path) -> None:
        """An orphan belongs to no knowledge base, so attaching one to a report about a named
        knowledge base would be attaching it arbitrarily."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            stray = paths.knowledge_dir(store_dir) / f"{uuid.uuid4()}.db"
            stray.write_bytes(b"")

            assert (await reporting.status(store_dir, db, config, name="docs")).orphans == ()
            assert len((await reporting.status(store_dir, db, config)).orphans) == 1


class TestRefusals:
    async def test_add_refuses_a_name_that_is_already_taken(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = corpus_root(tmp_path)
            await add_base(
                store_dir, db, config, lifecycle.AddRequest(name="docs", root=root, description="a")
            )
            with pytest.raises(DuplicateNameError):
                await add_base(
                    store_dir,
                    db,
                    config,
                    lifecycle.AddRequest(name="docs", root=root, description="b"),
                )

    async def test_a_refused_duplicate_leaves_the_first_corpus_untouched(
        self, tmp_path: Path
    ) -> None:
        """Never an upsert: the refusal must not have reconfigured the corpus it collided with."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            first = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(
                    name="docs", root=corpus_root(tmp_path, "one"), description="first"
                ),
            )
            with pytest.raises(DuplicateNameError):
                await add_base(
                    store_dir,
                    db,
                    config,
                    lifecycle.AddRequest(
                        name="docs", root=corpus_root(tmp_path, "two"), description="second"
                    ),
                )

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.description == "first"
            assert report.details is not None
            assert report.details.root_path == str(corpus_root(tmp_path, "three").parent / "one")
            assert first.database_path.is_file()

    @pytest.mark.parametrize("name", ["", "   ", "\t\n"])
    async def test_a_blank_name_is_refused(self, tmp_path: Path, name: str) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            with pytest.raises(InvalidNameError):
                await add_base(
                    config=config_for(tmp_path),
                    store_dir=store_dir,
                    db=db,
                    request=lifecycle.AddRequest(
                        name=name, root=corpus_root(tmp_path), description="a"
                    ),
                )

    async def test_an_absent_root_is_refused_before_anything_is_registered(
        self, tmp_path: Path
    ) -> None:
        """Validation precedes the registry write, so a bad root leaves no dangling name."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            with pytest.raises(InvalidRootError):
                await add_base(
                    store_dir,
                    db,
                    config,
                    lifecycle.AddRequest(
                        name="docs", root=tmp_path / "nothing-here", description="a"
                    ),
                )
            assert (await reporting.list_bases(store_dir, db, config)).knowledge_bases == ()

    async def test_a_file_as_a_root_is_refused(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            not_a_dir = tmp_path / "a-file.md"
            not_a_dir.write_text("x", encoding="utf-8")
            with pytest.raises(InvalidRootError, match="not a directory"):
                await add_base(
                    store_dir,
                    db,
                    config_for(tmp_path),
                    lifecycle.AddRequest(name="docs", root=not_a_dir, description="a"),
                )

    async def test_an_out_of_range_size_cap_is_refused_before_anything_is_registered(
        self, tmp_path: Path
    ) -> None:
        """A per-corpus override and the global default are the same quantity, so they are held to
        one range — and the check runs before the registry write, like every other refusal.

        **Refused as a rejection of the caller's own value, not as a complaint about
        configuration.** The range is read from the configuration schema, which is what keeps a
        corpus created this way reproducible by writing a configuration file; the *refusal* must
        not be, because a caller that typed a number would then go looking in a file for a typo
        that is in its own request. The exception carries the key, the value and the range so
        whoever is answering a caller can say all three without re-deriving them."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            with pytest.raises(InvalidSettingError) as caught:
                await add_base(
                    store_dir,
                    db,
                    config,
                    lifecycle.AddRequest(
                        name="docs",
                        root=corpus_root(tmp_path),
                        description="a",
                        max_file_bytes=0,
                    ),
                )
            _bounds, expected = meta.bounds_for(meta.MAX_FILE_BYTES_KEY)
            assert caught.value.bounds.key == meta.MAX_FILE_BYTES_KEY
            assert caught.value.bounds.value == 0
            assert caught.value.bounds.expected == expected, (
                "one phrasing of the range, shared with the stored-value path"
            )
            assert (await reporting.list_bases(store_dir, db, config)).knowledge_bases == ()

    async def test_rename_refuses_a_name_that_is_taken(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = corpus_root(tmp_path)
            await add_base(
                store_dir, db, config, lifecycle.AddRequest(name="one", root=root, description="a")
            )
            await add_base(
                store_dir, db, config, lifecycle.AddRequest(name="two", root=root, description="b")
            )
            with pytest.raises(DuplicateNameError):
                await lifecycle.rename(store_dir, db, config, name="one", new_name="TWO")

    @pytest.mark.parametrize("verb", ["remove", "rename", "status"])
    async def test_every_verb_refuses_an_unregistered_name(self, tmp_path: Path, verb: str) -> None:
        """Every verb that takes a name, not a sample of them: a verb that answered for a corpus
        nobody registered would be answering about nothing."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            calls: dict[str, Callable[[], Awaitable[object]]] = {
                "remove": lambda: lifecycle.remove(store_dir, db, config, name="absent"),
                "rename": lambda: lifecycle.rename(
                    store_dir, db, config, name="absent", new_name="x"
                ),
                "status": lambda: reporting.status(store_dir, db, config, name="absent"),
            }
            with pytest.raises(UnknownKnowledgeBaseError):
                await calls[verb]()

    async def test_remove_refuses_while_the_lock_is_held(self, tmp_path: Path) -> None:
        """Refusing to unlink a database a writer may hold is recoverable; unlinking one it does
        hold is not. The lock is read directly rather than off the reported state, because the
        state's own precedence reports an unbuilt corpus as needing a build whether or not a build
        is running — which is right for that question and wrong for this one."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            await _write_lock(created.database_path)

            with pytest.raises(IndexerBusyError):
                await lifecycle.remove(store_dir, db, config, name="docs")

            assert created.database_path.is_file()
            listing = await reporting.list_bases(store_dir, db, config)
            assert len(listing.knowledge_bases) == 1

    async def test_remove_is_not_stopped_by_a_lock_a_crashed_build_left(
        self, tmp_path: Path
    ) -> None:
        """Those rows survive a crash on purpose, and nothing but another build clears them. A
        corpus that could never be removed again after one crash would be the worse failure, and
        there is no writer to protect: the recorded process is gone."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            await _write_lock(created.database_path, pid=_DEAD_PID, host=lock.this_host())

            await lifecycle.remove(store_dir, db, config, name="docs")

            assert not created.database_path.exists()
            assert (await reporting.list_bases(store_dir, db, config)).knowledge_bases == ()


class TestTheMigrationIsAdditive:
    async def test_a_store_predating_the_registry_opens_and_answers_normally(
        self, tmp_path: Path
    ) -> None:
        """The clause the no-bump decision rests on. A store created with the registry table
        dropped stands in for one created before the table existed: it must open through the
        ordinary memory path, at the same `schema_version`, and gain the table on first use."""
        store_dir = tmp_path / ".zikaron"
        config = config_for(tmp_path)
        embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
        async with await Store.create(store_dir, config, embedder) as store:
            await store.connection.execute("DROP TABLE IF EXISTS knowledge_bases")
            await store.connection.commit()

        async with await Store.open(store_dir, config) as reopened:
            assert reopened.meta.schema_version == 1
            with pytest.raises(sqlite3.OperationalError):
                await reopened.connection.execute_fetchall("SELECT 1 FROM knowledge_bases")

            listing = await reporting.list_bases(store_dir, reopened.connection, config)
            assert listing.knowledge_bases == ()
            created = await add_base(
                store_dir,
                reopened.connection,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            assert created.database_path.is_file()

    async def test_the_store_schema_version_is_unchanged_by_the_registry(
        self, tmp_path: Path
    ) -> None:
        """Stated as an assertion rather than as prose: bumping it would make every older build
        refuse the store, which is the outcome the additive-table rule exists to avoid."""
        async with open_store(tmp_path) as (_store_dir, db):
            await registry.ensure(db)
            rows = await db.execute_fetchall("SELECT value FROM meta WHERE key = 'schema_version'")
            ((version,),) = list(rows)
            assert int(version) == 1

    async def test_ensuring_the_registry_twice_is_a_no_op(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            await registry.ensure(db)
            await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            await registry.ensure(db)
            assert len((await reporting.list_bases(store_dir, db, config)).knowledge_bases) == 1


class TestClearingALockByHand:
    """The exit from the state nothing clears on its own: a lock recorded on another machine, which
    is never reclaimed here, and which leaves a corpus every verb refuses with no clock running
    out on it."""

    async def test_a_foreign_lock_is_cleared_and_the_holder_reported(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            await _write_lock(created.database_path)

            cleared = await lifecycle.unlock(store_dir, db, name="docs")

            assert cleared is not None
            assert cleared.host == "somehost"
            assert (await builds.prepare(store_dir, db, config, name="docs")).name == "docs"

    async def test_a_running_local_build_is_refused(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            await _write_lock(created.database_path, pid=os.getpid(), host=lock.this_host())

            with pytest.raises(IndexerBusyError, match="still answers to the lock"):
                await lifecycle.unlock(store_dir, db, name="docs")

    async def test_a_corpus_with_no_lock_answers_that_rather_than_refusing(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )

            assert await lifecycle.unlock(store_dir, db, name="docs") is None

    async def test_an_unregistered_name_is_refused(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            with pytest.raises(UnknownKnowledgeBaseError):
                await lifecycle.unlock(store_dir, db, name="absent")

    async def test_a_corpus_with_no_database_is_refused(self, tmp_path: Path) -> None:
        """There is no lock to clear, and nothing that could have taken one."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            created.database_path.unlink()

            with pytest.raises(DanglingKnowledgeBaseError):
                await lifecycle.unlock(store_dir, db, name="docs")


async def _write_lock(db_path: Path, *, pid: int = 4242, host: str = "somehost") -> None:
    """Record a build lock by writing the `meta` keys a build writes when it starts.

    Written directly rather than by starting a build, because the interesting holders are the two
    no build of this suite's own could produce: one on another machine, and one whose process has
    died. The default is the first of those.
    """
    db, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS, existing_only=True)
    try:
        for key, value in (
            (meta.LOCK_PID_KEY, str(pid)),
            (meta.LOCK_HOST_KEY, host),
            (meta.LOCK_STARTED_AT_KEY, "2026-01-01T00:00:00+00:00"),
        ):
            await db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        await db.commit()
    finally:
        await db.close()
