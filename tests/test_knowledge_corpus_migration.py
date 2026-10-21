"""A corpus database at schema 1 is brought to schema 4 only by an opener whose store allows it.

`knowledge-index.md` §7.7.1 is normative. The step adds the link columns and counters, reads every
row's link from its stored chunks and records it against the row's own hash, in one transaction.
A corpus schema version is the `memory.db` version that introduced its shape, so whether a process
may run it is decided by the version it opened `memory.db` at: below 4, a build works the corpus at
schema 1 and nothing reads or writes a link column.

The schema-1 `files` table is frozen here as it shipped, because a fixture derived from today's DDL
would stop being schema 1 the moment the DDL moved.
"""

import hashlib
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Final

import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import (
    Corpus,
    add_request,
    build_settings,
    open_corpus,
    stub_spawn,
    write_tree,
)
from tests.service_fixtures import envelope, open_context
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.knowledge import (
    ddl,
    groups,
    lifecycle,
    link_store,
    meta,
    migration,
    registry,
    reporting,
)
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.paths import knowledge_db_path
from zikaron.core.store.connection import open_connection
from zikaron.knowledge.indexer import detach
from zikaron.knowledge.indexer import main as indexer_main
from zikaron.knowledge.scope import OpenStore
from zikaron.service import dispatch_knowledge
from zikaron.service.context import ServiceContext

#: `files` as schema 1 created it, before the link columns.
_V1_FILES: Final = """
CREATE TABLE files (
  path            TEXT    PRIMARY KEY,
  size            INTEGER NOT NULL,
  content_hash    TEXT    NOT NULL,
  git_blob_hash   TEXT,
  chunk_count     INTEGER NOT NULL,
  indexed_at      TEXT    NOT NULL,

  CHECK (length(path) > 0),
  CHECK (size >= 0),
  CHECK (chunk_count >= 0)
)
"""

_SOURCE: Final = b"def a():\n    return 1\n"


def _blob(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content, usedforsecurity=False).hexdigest()


def _documents() -> dict[str, bytes]:
    linked = f"---\nzikaron-source: src/a.py\nzikaron-source-blob: {_blob(_SOURCE)}\n---\n"
    return {
        "linked.md": (linked + "# a\nWhat a does, linked.\n").encode(),
        "malformed.md": b"---\nzikaron-source: src/a.py\n---\n# half a link\n",
        "plain.md": b"# plain\nNo front matter at all.\n",
    }


@pytest.fixture(autouse=True)
def _no_repository_above(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@asynccontextmanager
async def _corpus(tmp_path: Path) -> AsyncIterator[Corpus]:
    write_tree(tmp_path / "src", {"a.py": _SOURCE})
    root = write_tree(tmp_path / "docs", _documents())
    async with open_corpus(tmp_path, add_request(root, git_mode=meta.GitMode.OFF)) as corpus:
        yield corpus


async def _db_path(corpus: Corpus) -> Path:
    return knowledge_db_path(corpus.store_dir, (await registry.require(corpus.db, corpus.name)).id)


def _to_schema_one(db_path: Path) -> None:
    """Put a corpus database back as schema 1 left it, rows and all."""
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("ALTER TABLE files RENAME TO files_current")
        db.execute(_V1_FILES)
        db.execute(
            "INSERT INTO files SELECT path, size, content_hash, git_blob_hash, chunk_count, "
            "indexed_at FROM files_current"
        )
        db.execute("DROP TABLE files_current")
        db.executemany("DELETE FROM meta WHERE key = ?", [(key,) for key in meta.LINK_COUNTER_KEYS])
        db.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
        db.commit()


def _version(db_path: Path) -> int:
    with closing(sqlite3.connect(db_path)) as db:
        ((value,),) = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchall()
    return int(value)


def _columns(db_path: Path) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(db_path)) as db:
        return db.execute("PRAGMA table_info(files)").fetchall()


def _meta_keys(db_path: Path) -> set[str]:
    with closing(sqlite3.connect(db_path)) as db:
        return {str(key) for (key,) in db.execute("SELECT key FROM meta")}


def _link_rows(db_path: Path) -> dict[str, tuple[object, ...]]:
    with closing(sqlite3.connect(db_path)) as db:
        rows = db.execute(
            "SELECT path, content_hash, link_read_from, link_declared, source_path, source_blob "
            "FROM files"
        ).fetchall()
    return {str(row[0]): tuple(row[1:]) for row in rows}


async def _build(corpus: Corpus, *, migrate: bool, full: bool = False) -> lifecycle.Refreshed:
    return await lifecycle.refresh(
        corpus.store_dir,
        corpus.db,
        corpus.config,
        name=corpus.name,
        build=build_settings(corpus.config, full=full),
        migrate=migrate,
    )


async def _schema_one_corpus_built(corpus: Corpus) -> Path:
    db_path = await _db_path(corpus)
    _to_schema_one(db_path)
    await _build(corpus, migrate=False)
    assert _version(db_path) == 1
    return db_path


class TestTheGate:
    def test_only_a_store_at_version_four_or_later_may_migrate_a_corpus(self) -> None:
        assert not migration.may_migrate(3)
        assert migration.may_migrate(4)

    async def test_a_build_against_a_version_three_store_builds_at_schema_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Through the indexer's own entry point, which reads the store's version."""
        async with _corpus(tmp_path) as corpus:
            db_path = await _db_path(corpus)
            _to_schema_one(db_path)

            async def _settings(*_args: object, **_options: object) -> object:
                return build_settings(corpus.config)

            monkeypatch.setattr(indexer_main, "build_settings", _settings)
            store = OpenStore(
                project=tmp_path,
                directory=corpus.store_dir,
                connection=corpus.db,
                config=corpus.config,
                schema_version=3,
            )
            assert await indexer_main.build(store, name=corpus.name) == 0
        assert _version(db_path) == 1
        assert [column[1] for column in _columns(db_path)] == [
            "path",
            "size",
            "content_hash",
            "git_blob_hash",
            "chunk_count",
            "indexed_at",
        ]

    async def test_its_own_observation_reports_no_link_count(self, tmp_path: Path) -> None:
        async with _corpus(tmp_path) as corpus:
            db_path = await _db_path(corpus)
            _to_schema_one(db_path)
            refreshed = await _build(corpus, migrate=False)
        details = refreshed.status.details
        assert details is not None
        assert details.files_linked is None
        assert details.results_linked is None
        assert details.results_source_unverifiable is None
        assert refreshed.result.counters.files_indexed == len(_documents())

    async def test_a_version_four_opener_migrates_it_and_counts_its_links(
        self, tmp_path: Path
    ) -> None:
        async with _corpus(tmp_path) as corpus:
            db_path = await _schema_one_corpus_built(corpus)
            listing = await reporting.status(
                corpus.store_dir, corpus.db, corpus.config, name=corpus.name, migrate=True
            )
        (status,) = listing.knowledge_bases
        assert _version(db_path) == 4
        assert status.details is not None
        assert status.details.files_linked == 2, "the linked and the malformed declaration"
        assert status.details.results_linked == 0
        assert status.details.results_source_changed == 0

    @pytest.mark.parametrize(("migrate", "version"), [(True, 4), (False, 1)])
    async def test_a_search_serves_source_whether_or_not_it_may_migrate_the_corpus(
        self, tmp_path: Path, *, migrate: bool, version: int
    ) -> None:
        """Unmigrated, every link is read from the stored chunks and no link column is named."""
        async with _corpus(tmp_path) as corpus:
            db_path = await _schema_one_corpus_built(corpus)
            response = await groups.search_all(
                corpus.store_dir,
                corpus.db,
                corpus.config,
                groups.SearchRequest(text="linked", limit_per_kb=20),
                encoder=FakeEncoder(),
                migrate=migrate,
            )
        assert _version(db_path) == version
        (group,) = response.groups
        assert isinstance(group, groups.Group)
        results = group.payload()["results"]
        by_path = {result["path"]: result for result in results}  # type: ignore[attr-defined]
        assert by_path["linked.md"]["source"] == {"path": "src/a.py", "state": "fresh"}
        assert by_path["malformed.md"]["source"] == {"path": None, "state": "unverifiable"}
        assert "source" not in by_path["plain.md"]

    async def test_remove_and_rename_migrate_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(detach, "spawn", stub_spawn)
        write_tree(tmp_path / "docs", _documents())
        async with open_context(tmp_path) as ctx:
            await _dispatch(
                ctx,
                "knowledge_add",
                {"name": "docs", "path": str(tmp_path / "docs"), "description": "d"},
            )
            registered = await registry.require(ctx.store.connection, "docs")
            db_path = knowledge_db_path(ctx.store_directory, registered.id)
            _to_schema_one(db_path)

            async def _must_not_migrate(*_args: object) -> bool:
                raise AssertionError("a corpus was migrated")

            monkeypatch.setattr(migration, "migrate", _must_not_migrate)
            await _dispatch(ctx, "knowledge_rename", {"name": "docs", "new_name": "notes"})
            with pytest.raises(ZikaronError) as preview:
                await _dispatch(ctx, "knowledge_remove", {"name": "notes"})
            assert preview.value.code is ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED
            assert _version(db_path) == 1
            removed = await _dispatch(ctx, "knowledge_remove", {"name": "notes", "confirm": True})
        assert removed["removed"] is True
        assert not db_path.exists()


async def _dispatch(
    ctx: ServiceContext, method: str, params: dict[str, object]
) -> dict[str, object]:
    result = await dispatch_knowledge.KNOWLEDGE_METHODS[method].handler(
        ctx.store.connection, ctx, envelope(), params
    )
    payload = result.as_json()
    assert isinstance(payload, dict)
    return payload


class TestTheStep:
    async def test_invariant_18_it_opens_immediate(self, tmp_path: Path) -> None:
        """It reads the version before it writes, so deferred it would be refused at its first
        write by any other writer holding the lock."""
        async with _corpus(tmp_path) as corpus:
            db_path = await _schema_one_corpus_built(corpus)
        db, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS, existing_only=True)
        statements: list[str] = []
        try:
            await db.set_trace_callback(statements.append)
            assert await migration.migrate(db)
        finally:
            await db.close()
        begins = [s for s in statements if s.split(maxsplit=1)[0].upper() == "BEGIN"]
        assert begins == ["BEGIN IMMEDIATE"]

    async def test_a_migrated_database_has_a_created_ones_columns_keys_and_version(
        self, tmp_path: Path
    ) -> None:
        async with _corpus(tmp_path / "migrated") as migrated:
            migrated_path = await _schema_one_corpus_built(migrated)
            async with await KnowledgeDatabase.open(
                migrated.store_dir, (await registry.require(migrated.db, "docs")).id, migrate=True
            ):
                pass
        async with _corpus(tmp_path / "created") as created:
            created_path = await _db_path(created)
        assert _columns(migrated_path) == _columns(created_path)
        assert _meta_keys(migrated_path) - _meta_keys(created_path) <= {
            meta.LAST_SCAN_STARTED_AT_KEY,
            meta.LAST_WALK_COMPLETED_AT_KEY,
            meta.LAST_SCAN_COMPLETED_AT_KEY,
            meta.LAST_SCAN_GIT_MODE_EFFECTIVE_KEY,
        }, "only what a build writes later differs"
        assert _meta_keys(created_path) <= _meta_keys(migrated_path)
        assert _version(migrated_path) == _version(created_path) == meta.CURRENT_SCHEMA_VERSION

    async def test_its_backfill_is_what_a_build_writes(self, tmp_path: Path) -> None:
        async with _corpus(tmp_path) as corpus:
            db_path = await _schema_one_corpus_built(corpus)
            await _build(corpus, migrate=True)
            backfilled = _link_rows(db_path)
            await _build(corpus, migrate=True, full=True)
            rebuilt = _link_rows(db_path)
        assert backfilled == rebuilt
        assert backfilled["linked.md"][2:] == (1, "src/a.py", _blob(_SOURCE))
        assert backfilled["malformed.md"][2:] == (1, None, None)
        assert backfilled["plain.md"][2:] == (0, None, None)
        assert all(row[0] == row[1] for row in backfilled.values()), "read from these bytes"

    async def test_running_it_twice_changes_nothing(self, tmp_path: Path) -> None:
        async with _corpus(tmp_path) as corpus:
            db_path = await _schema_one_corpus_built(corpus)
            registered = await registry.require(corpus.db, corpus.name)
            async with await KnowledgeDatabase.open(
                corpus.store_dir, registered.id, migrate=True
            ) as opened:
                first = _link_rows(db_path)
                assert await migration.migrate(opened.connection) is False
        assert _link_rows(db_path) == first

    async def test_interrupted_it_leaves_schema_one_whole(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async with _corpus(tmp_path) as corpus:
            db_path = await _schema_one_corpus_built(corpus)
            before = _columns(db_path)

            async def _dies(*_args: object) -> None:
                raise RuntimeError("killed mid-step")

            monkeypatch.setattr(link_store, "write_records", _dies)
            registered = await registry.require(corpus.db, corpus.name)
            with pytest.raises(RuntimeError):
                await KnowledgeDatabase.open(corpus.store_dir, registered.id, migrate=True)
        assert _version(db_path) == 1
        assert _columns(db_path) == before
        assert not (_meta_keys(db_path) & set(meta.LINK_COUNTER_KEYS))


class TestTheRecordIsMadeExact:
    async def test_a_build_reads_again_every_record_not_read_from_its_rows_bytes(
        self, tmp_path: Path
    ) -> None:
        """What a build of the previous schema leaves: a record of other bytes, and none at all."""
        async with _corpus(tmp_path) as corpus:
            await _build(corpus, migrate=True)
            db_path = await _db_path(corpus)
            with closing(sqlite3.connect(db_path)) as db:
                db.execute(
                    "UPDATE files SET link_read_from = 'other bytes', source_path = 'wrong.py' "
                    "WHERE path = 'linked.md'"
                )
                db.execute(
                    "UPDATE files SET link_read_from = NULL, link_declared = NULL, "
                    "source_path = NULL, source_blob = NULL WHERE path = 'malformed.md'"
                )
                db.commit()
            refreshed = await _build(corpus, migrate=True)
        rows = _link_rows(db_path)
        assert rows["linked.md"][1:] == (rows["linked.md"][0], 1, "src/a.py", _blob(_SOURCE))
        assert rows["malformed.md"][1:] == (rows["malformed.md"][0], 1, None, None)
        assert refreshed.result.counters.files_indexed == len(_documents())
        assert refreshed.status.details is not None
        assert refreshed.status.details.files_linked == 2

    async def test_the_counters_are_seeded_at_creation(self, tmp_path: Path) -> None:
        async with _corpus(tmp_path) as corpus:
            db_path = await _db_path(corpus)
        assert set(meta.LINK_COUNTER_KEYS) <= _meta_keys(db_path)
