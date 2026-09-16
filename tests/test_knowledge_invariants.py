"""The three properties this layer must hold, each tested by trying to break it.

- **No caller-supplied string ever becomes a path segment under `.zikaron/`.** Every knowledge
  database is named by a server-generated uuid, so `remove(name="../memory")` cannot reach the
  memory store. This is the security one.
- **Knowledge-base names are stored lower-cased, and unique by plain string equality.** `Docs` and
  `docs` are one name rather than two corpora, because the normalization happens on write.
- **The registry row is the sole authority for a knowledge base's existence; its database file is
  derived state that may be absent.** A row with no file reads as an empty corpus; a file with no
  row is an orphan that is reported, never opened, and never deleted on its own.

These are what make the design enforceable rather than aspirational, so each test is written to
**fail if the property is violated** rather than to demonstrate the happy path.

The invariants a *build* must hold — every chunk's path naming a row, a file's rows moving in one
transaction, and the pending table being emptied only by a disposal or a wholesale replacement —
are in `test_knowledge_build_invariants.py`, which needs a built corpus rather than a registry.
"""

import sqlite3
import uuid
from pathlib import Path

import pytest

from tests.knowledge_fixtures import add_base, config_for, corpus_root, open_store
from zikaron.core.knowledge import lifecycle, paths, registry, reporting
from zikaron.core.knowledge.errors import DuplicateNameError, UnknownKnowledgeBaseError
from zikaron.core.knowledge.state import KnowledgeState


class TestNoSuppliedStringReachesAPath:
    """Every knowledge database path is `knowledge/<id>.db` for a server-generated uuid4."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "../memory",
            "../../etc/passwd",
            "..",
            "/etc/passwd",
            "memory.db",
            "a/b",
            "....//memory",
        ],
    )
    async def test_a_hostile_name_never_names_a_file(self, tmp_path: Path, hostile: str) -> None:
        """The attack this closes by construction: `remove(name="../memory")` resolving to the
        memory store, which would let one call destroy every memory in the project.

        It fails as *no such knowledge base* rather than as a rejected path, and that is the point
        — the name is looked up in a table, so there is no path for it to be hostile in.
        """
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            memory_db = store_dir / "memory.db"
            before = memory_db.read_bytes()

            with pytest.raises(UnknownKnowledgeBaseError):
                await lifecycle.remove(store_dir, db, config, name=hostile)

            assert memory_db.exists()
            assert memory_db.read_bytes() == before

    async def test_a_hostile_name_that_is_registered_still_names_a_generated_file(
        self, tmp_path: Path
    ) -> None:
        """The stronger form: even a knowledge base *actually called* `../memory` gets an ordinary
        generated filename, because the name and the path have no relationship at all."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(
                    name="../memory", root=corpus_root(tmp_path), description="hostile"
                ),
            )

            assert created.database_path.parent == paths.knowledge_dir(store_dir)
            assert created.database_path.name == f"{created.knowledge_base.id}.db"
            uuid.UUID(created.database_path.stem)

            await lifecycle.remove(store_dir, db, config, name="../memory")
            assert (store_dir / "memory.db").exists()

    def test_the_path_builder_will_not_accept_a_string_at_all(self, tmp_path: Path) -> None:
        """The type signature says `UUID`, but an f-string formats whatever it is handed — so a
        string passed by an untyped caller would have become path segments. Measured: it did,
        producing `knowledge/../memory.db`. Re-parsing the id is what closes that, and this is the
        test that found the annotation alone was not enough."""
        with pytest.raises((AttributeError, TypeError, ValueError)):
            paths.knowledge_db_path(tmp_path, "../memory")  # type: ignore[arg-type]


class TestNamesAreLowerCasedAndUnique:
    """`Docs` and `docs` are one name, because the normalization happens on write."""

    async def test_two_names_differing_only_by_case_collide_on_the_unique_constraint(
        self, tmp_path: Path
    ) -> None:
        """On the constraint, not on a preceding `SELECT` — asserted by reading the cause, because
        a check-then-insert would pass this test while losing the race two callers create."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = corpus_root(tmp_path)
            await add_base(
                store_dir, db, config, lifecycle.AddRequest(name="Docs", root=root, description="a")
            )

            with pytest.raises(DuplicateNameError) as caught:
                await add_base(
                    store_dir,
                    db,
                    config,
                    lifecycle.AddRequest(name="DOCS", root=root, description="b"),
                )

            cause = caught.value.__cause__
            assert isinstance(cause, sqlite3.IntegrityError)
            assert cause.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE

    async def test_a_second_corpus_is_not_created_when_the_name_collides(
        self, tmp_path: Path
    ) -> None:
        """The refusal has to leave nothing behind: a registry row rolled back but a database file
        already written would be the permanent orphan the ordering exists to rule out."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = corpus_root(tmp_path)
            first = await add_base(
                store_dir, db, config, lifecycle.AddRequest(name="Docs", root=root, description="a")
            )
            with pytest.raises(DuplicateNameError):
                await add_base(
                    store_dir,
                    db,
                    config,
                    lifecycle.AddRequest(name="DOCS", root=root, description="b"),
                )

            assert [path.name for path in paths.orphan_candidates(store_dir)] == [
                first.database_path.name
            ]

    async def test_a_name_is_stored_lower_cased_and_found_by_any_case(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(
                    name="Design Records", root=corpus_root(tmp_path), description="a"
                ),
            )
            assert created.knowledge_base.name == "design records"

            for spelling in ("design records", "DESIGN RECORDS", "Design Records"):
                found = await registry.find(db, spelling)
                assert found is not None
                assert found.id == created.knowledge_base.id

    async def test_the_stored_column_never_holds_an_upper_case_name(self, tmp_path: Path) -> None:
        """Read straight out of the column rather than through the code that wrote it, so the
        assertion is about what is stored rather than about what a getter returns."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(
                    name="MiXeD Case", root=corpus_root(tmp_path), description="a"
                ),
            )
            rows = await db.execute_fetchall("SELECT name FROM knowledge_bases")
            assert [str(name) for (name,) in rows] == ["mixed case"]

    async def test_the_table_itself_refuses_an_un_normalized_ascii_name(
        self, tmp_path: Path
    ) -> None:
        """The `CHECK` is a backstop against a writer that skipped the normalization, and it is
        asserted here because it is only a *partial* one: SQLite's `lower()` is ASCII-only, so
        this catches the common mistake and not every one. Written as a direct insert, since going
        through the registry is what the backstop exists to survive the absence of."""
        async with open_store(tmp_path) as (_store_dir, db):
            await db.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_bases ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL,"
                " created_at TEXT NOT NULL, CHECK (length(trim(name)) > 0),"
                " CHECK (name = lower(name)))"
            )
            with pytest.raises(sqlite3.IntegrityError) as caught:
                await db.execute(
                    "INSERT INTO knowledge_bases VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), "NotLowered", "d", "now"),
                )
            assert caught.value.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_CHECK


class TestTheRegistryIsTheAuthorityOnExistence:
    """A row without a file is an empty knowledge base; a file without a row is an orphan."""

    async def test_a_row_without_a_file_is_an_empty_knowledge_base(self, tmp_path: Path) -> None:
        """The state an interrupted `add` leaves. Everything that reads treats it as an empty
        corpus rather than an error; a *build* refuses it, because the file that is missing is the
        only place this corpus's definition was ever written."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            created.database_path.unlink()

            listing = await reporting.list_bases(store_dir, db, config)
            (report,) = listing.knowledge_bases
            assert report.summary.state is KnowledgeState.REINDEX_REQUIRED
            assert report.summary.files_indexed == 0
            assert report.details is None
            assert listing.orphans == ()

    async def test_a_file_without_a_row_is_an_orphan_that_is_reported_and_left_alone(
        self, tmp_path: Path
    ) -> None:
        """The state an interrupted `remove` leaves. It is never opened for a query and never
        deleted on its own, because an unreferenced database may hold a corpus somebody wants
        back."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await add_base(
                store_dir,
                db,
                config,
                lifecycle.AddRequest(name="docs", root=corpus_root(tmp_path), description="a"),
            )
            await db.execute("DELETE FROM knowledge_bases")
            await db.commit()

            listing = await reporting.list_bases(store_dir, db, config)
            assert listing.knowledge_bases == ()
            (orphan,) = listing.orphans
            assert orphan.path == created.database_path
            assert orphan.breadcrumb_name == "docs"
            assert orphan.size_bytes > 0
            assert created.database_path.exists()

    async def test_something_in_the_knowledge_directory_that_is_not_a_database_is_reported(
        self, tmp_path: Path
    ) -> None:
        """A directory named like a knowledge base, which is what a half-finished copy or an
        unpacked backup leaves behind.

        It cannot be opened at all, so it has no name to report and no size to read — and the
        listing has to survive that rather than raise, because the caller is asking *what is in
        this directory* and refusing to answer would hide the very thing it should surface.
        """
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            directory = paths.knowledge_dir(store_dir)
            directory.mkdir(exist_ok=True)
            stray = directory / f"{uuid.uuid4()}.db"
            stray.mkdir()

            listing = await reporting.list_bases(store_dir, db, config)

            (orphan,) = listing.orphans
            assert orphan.path == stray
            assert orphan.breadcrumb_name is None
            assert orphan.size_bytes == 0

    async def test_reporting_an_orphan_does_not_modify_it(self, tmp_path: Path) -> None:
        """The promise made about an orphan is that it is reported and otherwise left alone, and
        reading its name is the one time anything opens it at all.

        Measured, because the obvious implementation breaks the promise invisibly: opening through
        the ordinary opener applies `journal_mode = WAL`, which is a persistent header write. Every
        orphan this project made is already in WAL, so nothing would be observed — which is why the
        database here is deliberately left in the default rollback journal, the state a file that
        is *not* ours can be in. Asserted on the bytes, not on the journal mode, so any other write
        fails it too.
        """
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            directory = paths.knowledge_dir(store_dir)
            directory.mkdir(exist_ok=True)
            foreign = directory / f"{uuid.uuid4()}.db"
            handmade = sqlite3.connect(foreign)
            try:
                handmade.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                handmade.execute("INSERT INTO meta VALUES ('name_breadcrumb', 'someone elses')")
                handmade.commit()
            finally:
                handmade.close()
            ((journal_mode,),) = sqlite3.connect(foreign).execute("PRAGMA journal_mode").fetchall()
            assert journal_mode == "delete", "the fixture must not already be in WAL"
            before = foreign.read_bytes()

            listing = await reporting.list_bases(store_dir, db, config)

            (orphan,) = listing.orphans
            assert orphan.breadcrumb_name == "someone elses"
            assert foreign.read_bytes() == before
            assert not foreign.with_name(foreign.name + "-wal").exists()

    async def test_an_orphan_that_cannot_be_read_is_still_reported(self, tmp_path: Path) -> None:
        """Exactly when a breadcrumb is unavailable is when a human most needs telling the file is
        there, so an unreadable orphan is reported with no name rather than omitted."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            stray = paths.knowledge_dir(store_dir)
            stray.mkdir(exist_ok=True)
            broken = stray / f"{uuid.uuid4()}.db"
            broken.write_bytes(b"not a database at all")

            listing = await reporting.list_bases(store_dir, db, config)
            (orphan,) = listing.orphans
            assert orphan.path == broken
            assert orphan.breadcrumb_name is None
