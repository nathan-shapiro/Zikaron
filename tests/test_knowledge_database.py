"""Creating and opening one knowledge base's own database file.

Two things are worth more than the happy path here. The schema has to be created **atomically**,
because a half-created knowledge base that survived a failure is indistinguishable from a complete
one on every later open. And the files have to land at `0600`: a knowledge base holds the text of
every file it indexed, so it is exactly as sensitive as whatever it was pointed at.
"""

import dataclasses
import subprocess
import sys
import uuid
from pathlib import Path

import aiosqlite
import pytest

from tests.knowledge_fixtures import config_for
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.knowledge import database, ddl, meta, paths
from zikaron.core.store import permissions
from zikaron.core.store.connection import open_connection
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store

_EXPECTED_TABLES = {"files", "pending", "chunks", "chunks_fts", "chunks_vec", "meta"}


def _spec(root: Path) -> database.NewKnowledgeBase:
    return database.NewKnowledgeBase(name="docs", root=root, description="a corpus")


def _identity(tmp_path: Path, **overrides: object) -> meta.KnowledgeMeta:
    identity = database.seed_identity(uuid.uuid4(), _spec(tmp_path), config_for(tmp_path))
    if not overrides:
        return identity
    return dataclasses.replace(identity, **overrides)  # type: ignore[arg-type]


class TestCreation:
    async def test_every_table_the_design_specifies_is_created(self, tmp_path: Path) -> None:
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)
        async with await database.KnowledgeDatabase.create(store_dir, identity) as created:
            rows = await created.connection.execute_fetchall(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
            names = {str(name) for (name,) in rows}
        assert names >= _EXPECTED_TABLES
        assert "chunks_path" in names

    async def test_a_knowledge_connection_really_has_foreign_keys_off(self, tmp_path: Path) -> None:
        """Read off the live connection, not off the tuple the module declares.

        The distinction is the whole point of this test. A knowledge database declares no foreign
        key anywhere, and switching the pragma on would advertise a cascade that does not exist —
        the exact wrong mental model that ships orphaned vectors and a corrupt full-text index. A
        guard that compared the declared tuple against the design would pass while the connection
        carried the opposite setting, which is precisely what happened before this test existed:
        the tuple was correct, applied nowhere, and every knowledge connection opened with the
        memory store's three pragmas instead.

        Both paths are checked, because they apply the pragmas independently.
        """
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)

        async with await database.KnowledgeDatabase.create(store_dir, identity) as made:
            ((on_create,),) = list(await made.connection.execute_fetchall("PRAGMA foreign_keys"))
            ((journal_mode,),) = list(await made.connection.execute_fetchall("PRAGMA journal_mode"))
            ((busy_timeout,),) = list(await made.connection.execute_fetchall("PRAGMA busy_timeout"))

        async with await database.KnowledgeDatabase.open(store_dir, identity.id) as opened:
            ((on_open,),) = list(await opened.connection.execute_fetchall("PRAGMA foreign_keys"))

        assert int(on_create) == 0
        assert int(on_open) == 0
        assert str(journal_mode).lower() == "wal"
        assert int(busy_timeout) == 5000

    async def test_the_memory_store_still_has_foreign_keys_on(self, tmp_path: Path) -> None:
        """The other half of the same claim: the two schemas genuinely want different sets, so a
        fix that simply removed the pragma everywhere would break the memory store's own
        constraints while making this file's tests pass."""
        config = config_for(tmp_path)
        embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
        async with await Store.create(tmp_path / ".zikaron", config, embedder) as store:
            rows = await store.connection.execute_fetchall("PRAGMA foreign_keys")
        ((foreign_keys,),) = list(rows)
        assert int(foreign_keys) == 1

    async def test_the_vector_column_is_created_at_the_configured_width(
        self, tmp_path: Path
    ) -> None:
        store_dir = tmp_path / ".zikaron"
        async with await database.KnowledgeDatabase.create(
            store_dir, _identity(tmp_path, embed_dim=7)
        ) as created:
            rows = await created.connection.execute_fetchall(
                "SELECT sql FROM sqlite_master WHERE name = 'chunks_vec'"
            )
            ((sql,),) = list(rows)
        assert "float[7]" in str(sql)

    async def test_the_directory_and_every_file_land_private(self, tmp_path: Path) -> None:
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)
        async with await database.KnowledgeDatabase.create(store_dir, identity) as created:
            await created.connection.execute("INSERT INTO pending VALUES ('a', 'now')")
            await created.connection.commit()
            present = [path for path in permissions.database_files(created.path) if path.is_file()]
            modes = {path.stat().st_mode & 0o777 for path in present}

        assert paths.knowledge_dir(store_dir).stat().st_mode & 0o777 == 0o700
        assert modes == {0o600}

    async def test_a_failed_creation_leaves_no_file_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connecting creates the file, so a failure after that point would otherwise leave a
        registered knowledge base pointing at an empty database — reported as an index that cannot
        be opened, which is the one state saying a rebuild will not help, for a condition a rebuild
        fixes completely."""
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)
        monkeypatch.setattr(
            ddl, "FIXED_STATEMENTS", (*ddl.FIXED_STATEMENTS, "CREATE TABLE this is not valid sql")
        )

        with pytest.raises(aiosqlite.Error):
            await database.KnowledgeDatabase.create(store_dir, identity)
        monkeypatch.undo()

        for path in permissions.database_files(paths.knowledge_db_path(store_dir, identity.id)):
            assert not path.exists(), path

    @pytest.mark.parametrize("failing_step", ["the connection setup", "the permission tightening"])
    async def test_a_failure_anywhere_after_the_file_exists_still_leaves_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_step: str
    ) -> None:
        """The cleanup covers every step from the connect onwards, not only the schema write.

        Both of these fail *after* SQLite has created the file and before the method returns, and
        each used to escape: a failure setting the connection up left an empty database behind, and
        a failure tightening the modes left the database **and** never closed the connection — a
        non-daemon thread that keeps the process alive with nothing printed.
        """
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)

        if failing_step == "the connection setup":
            real_execute = aiosqlite.Connection.execute

            async def _fail_on_pragma(
                self: aiosqlite.Connection, sql: str, parameters: object = None
            ) -> object:
                if sql.strip().upper().startswith("PRAGMA"):
                    raise RuntimeError("simulated failure setting the connection up")
                return await real_execute(self, sql, parameters)

            monkeypatch.setattr(aiosqlite.Connection, "execute", _fail_on_pragma)
        else:

            def _fail_on_chmod(_path: Path) -> None:
                raise PermissionError("simulated failure tightening the modes")

            monkeypatch.setattr(permissions, "enforce_store_file_mode", _fail_on_chmod)

        with pytest.raises((RuntimeError, PermissionError)):
            await database.KnowledgeDatabase.create(store_dir, identity)
        monkeypatch.undo()

        for path in permissions.database_files(paths.knowledge_db_path(store_dir, identity.id)):
            assert not path.exists(), path

    async def test_the_schema_and_its_meta_are_written_in_one_transaction(
        self, tmp_path: Path
    ) -> None:
        """Tested one level below `create`, and that placement is the whole point.

        `create` now deletes the file when it fails, so a test at that level cannot tell a
        transactional implementation from an autocommitting one — both leave nothing, and the
        assertion goes quietly vacuous. What the transaction still buys is the case no handler can
        clean up after: a process killed partway through must not leave a half-built schema that
        opens and looks complete. So the transaction is exercised where it lives, with the file
        left in place afterwards to be inspected.

        Failing the **last** statement is what makes it a real test: every earlier `CREATE` has
        already run, and under autocommit each one would have stuck.
        """
        db_path = tmp_path / "half-built.db"
        broken = (*ddl.FIXED_STATEMENTS, "CREATE TABLE this is not valid sql")
        identity = _identity(tmp_path)

        db, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS)
        try:
            with pytest.raises(aiosqlite.Error):
                await database.KnowledgeDatabase._create_tables_and_meta(db, identity, broken)
            rows = await db.execute_fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")
            assert [str(name) for (name,) in rows] == []
        finally:
            await db.close()

    async def test_creation_refuses_a_path_that_is_already_taken_and_leaves_it_alone(
        self, tmp_path: Path
    ) -> None:
        """The path is named by a freshly generated uuid, so a file there is an anomaly worth
        stopping for rather than a knowledge base to adopt.

        **The surviving file is the assertion that matters**, not the raise. Creation deletes what
        it made when it fails, and this is the one branch that must be excluded from that — the
        file here was not made by this call, so removing it would destroy somebody else's corpus
        on a refused request. A regression that ran the cleanup here would still raise, and would
        pass a test that only checked the raise.
        """
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)
        async with await database.KnowledgeDatabase.create(store_dir, identity) as first:
            await first.connection.execute("INSERT INTO pending VALUES ('a.md', 'now')")
            await first.connection.commit()
        before = first.path.read_bytes()

        with pytest.raises(FileExistsError):
            await database.KnowledgeDatabase.create(store_dir, identity)

        assert first.path.read_bytes() == before


class TestOpening:
    async def test_open_returns_the_meta_it_was_created_with(self, tmp_path: Path) -> None:
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)
        async with await database.KnowledgeDatabase.create(store_dir, identity):
            pass
        async with await database.KnowledgeDatabase.open(store_dir, identity.id) as opened:
            assert opened.meta == identity

    async def test_open_refuses_a_newer_schema_version(self, tmp_path: Path) -> None:
        """A newer writer may have changed tables, indexes or the meaning of an existing key, so
        opening it and reading on would be reading an unknown schema as if it were this one."""
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)
        async with await database.KnowledgeDatabase.create(store_dir, identity) as created:
            await created.connection.execute(
                "UPDATE meta SET value = ? WHERE key = ?",
                (str(meta.SUPPORTED_SCHEMA_VERSION + 1), meta.SCHEMA_VERSION_KEY),
            )
            await created.connection.commit()

        with pytest.raises(ZikaronError) as caught:
            await database.KnowledgeDatabase.open(store_dir, identity.id)
        assert caught.value.code is ErrorCode.SCHEMA_INCOMPATIBLE

    async def test_open_refuses_a_database_with_no_meta_table(self, tmp_path: Path) -> None:
        """A database with no `meta` is one missing every required key, which is exactly true and
        is reported that way rather than through a second error path."""
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path)
        async with await database.KnowledgeDatabase.create(store_dir, identity) as created:
            await created.connection.execute("DROP TABLE meta")
            await created.connection.commit()

        with pytest.raises(ZikaronError) as caught:
            await database.KnowledgeDatabase.open(store_dir, identity.id)
        assert caught.value.code is ErrorCode.BAD_CONFIG

    async def test_open_does_not_create_an_absent_database(self, tmp_path: Path) -> None:
        """Absence is an empty knowledge base rather than an error, and saying so is the caller's
        job — but this must not quietly manufacture one on the way to finding out."""
        store_dir = tmp_path / ".zikaron"
        paths.knowledge_dir(store_dir).mkdir(parents=True)
        missing = uuid.uuid4()

        with pytest.raises(aiosqlite.Error):
            await database.KnowledgeDatabase.open(store_dir, missing)
        assert not paths.knowledge_db_path(store_dir, missing).exists()

    async def test_open_succeeds_while_the_encoder_disagrees_with_configuration(
        self, tmp_path: Path
    ) -> None:
        """A knowledge base whose recorded encoder has diverged is a state to report, not a
        failure to open — refusing here would deny the caller the very fields it needs to say so."""
        store_dir = tmp_path / ".zikaron"
        identity = _identity(tmp_path, embed_model="some/other-model")
        async with await database.KnowledgeDatabase.create(store_dir, identity):
            pass
        async with await database.KnowledgeDatabase.open(store_dir, identity.id) as opened:
            assert not database.encoder_matches_config(opened.meta, config_for(tmp_path))


class TestTheSeededIdentity:
    def test_the_configured_cap_is_used_when_none_is_given(self, tmp_path: Path) -> None:
        config = config_for(tmp_path)
        identity = database.seed_identity(uuid.uuid4(), _spec(tmp_path), config)
        assert identity.max_file_bytes == config.get_int("knowledge_max_file_bytes")

    def test_a_given_cap_overrides_the_configured_one(self, tmp_path: Path) -> None:
        """Persisted at creation rather than read later, so the next build cannot silently undo it
        by re-walking under the global default."""
        spec = database.NewKnowledgeBase(
            name="docs", root=tmp_path, description="a", max_file_bytes=4096
        )
        identity = database.seed_identity(uuid.uuid4(), spec, config_for(tmp_path))
        assert identity.max_file_bytes == 4096

    def test_the_root_is_stored_as_given_and_the_name_only_as_a_breadcrumb(
        self, tmp_path: Path
    ) -> None:
        spec = database.NewKnowledgeBase(name="docs", root=tmp_path, description="a")
        identity = database.seed_identity(uuid.uuid4(), spec, config_for(tmp_path))
        assert identity.root_path == str(tmp_path)
        assert identity.name_breadcrumb == "docs"


@pytest.mark.integration
def test_creating_a_knowledge_base_never_imports_fastembed(tmp_path: Path) -> None:
    """The claim that lets a corpus be created with no model on the critical path, measured.

    A knowledge base's vector column takes its width from configuration rather than from a loaded
    encoder, and the whole value of that is the import and load it avoids — roughly a second,
    measured elsewhere in this project and deliberately kept off any path a person waits on.

    Run in a **fresh subprocess**, because this suite's own process has already imported half the
    third-party stack by the time any given test runs: checking `sys.modules` in-process would
    report whatever an unrelated earlier test happened to import. A fresh interpreter has no such
    history, so what it reports is attributable to this code alone.
    """
    script = (
        "import asyncio, sys, uuid\n"
        "from pathlib import Path\n"
        "from zikaron.core.config.resolution import resolve\n"
        "from zikaron.core.knowledge import database\n"
        f"root = Path({str(tmp_path)!r})\n"
        "config = resolve(root / 'system.toml', root / 'project.toml')\n"
        "spec = database.NewKnowledgeBase(name='docs', root=root, description='a')\n"
        "identity = database.seed_identity(uuid.uuid4(), spec, config)\n"
        "async def go():\n"
        "    async with await database.KnowledgeDatabase.create(root / '.zikaron', identity):\n"
        "        pass\n"
        "asyncio.run(go())\n"
        "print('fastembed' in sys.modules)\n"
    )
    result = subprocess.run(  # noqa: S603 — a fixed, test-constructed script and interpreter path.
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    assert result.stdout.strip() == "False", result.stderr
