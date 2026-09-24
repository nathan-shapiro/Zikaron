"""Bringing a store forward from schema version 1, and what every other opener does meanwhile.

The tests that matter here run against a store actually built at version 1 — a fresh store is at
`CURRENT_SCHEMA_VERSION` and exercises no step at all, so a suite that only creates stores would
pass with the migration deleted.
"""

import sqlite3
from pathlib import Path

import aiosqlite
import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.events import ClientKind
from zikaron.core.store import ddl, meta, migration
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import CURRENT_SCHEMA_VERSION, Store

#: Version 1's `event`, literal rather than derived from `ddl`. It is a historical artifact: a
#: version that is done moving, which is exactly what `ddl` is not.
_NARROW_EVENT = (
    "CREATE TABLE event (\n"
    "  id          INTEGER PRIMARY KEY,\n"
    "  at          TEXT NOT NULL,\n"
    "  session_id  TEXT,\n"
    "  client_kind TEXT NOT NULL CHECK (client_kind IN ('hook', 'mcp', 'consolidator')),\n"
    "  op_id       TEXT NOT NULL,\n"
    "  kind        TEXT NOT NULL CHECK (kind IN (\n"
    "                'surface_call', 'surface', 'search', 'fetch', 'remember', 'amend', 'retire',\n"
    "                'merge', 'promote', 'discard', 'dedup_offered', 'version_conflict',\n"
    "                'no_receipt', 'group_served', 'consolidate_run'\n"
    "              )),\n"
    "  memory_uuid TEXT,\n"
    "  detail      TEXT\n"
    ")"
)


def _config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


async def _store_at_version_one(store_dir: Path, config: EffectiveConfig) -> Path:
    """A store as a version-1 build left it: the narrow `CHECK`, and `meta` saying so.

    Built by creating a current store and putting `event` back the way version 1 had it, rather
    than by carrying a fixture database: a checked-in binary would stop tracking the rest of the
    schema the moment anything else in it moved.
    """
    async with await Store.create(store_dir, config, FakeEmbedder("BAAI/bge-small-en-v1.5", 384)):
        pass
    db_path = store_dir / "memory.db"
    db = sqlite3.connect(db_path)
    try:
        db.execute("DROP TABLE event")
        db.execute(_NARROW_EVENT)
        for statement in ddl.EVENT_INDEXES:
            db.execute(statement)
        db.execute("UPDATE meta SET value = '1' WHERE key = ?", (meta.SCHEMA_VERSION_KEY,))
        db.commit()
    finally:
        db.close()
    return db_path


async def _count(db: aiosqlite.Connection, sql: str) -> int:
    rows = list(await db.execute_fetchall(sql))
    return int(rows[0][0])


async def _record(db: aiosqlite.Connection, kind: ClientKind) -> None:
    await db.execute(
        "INSERT INTO event (at, session_id, client_kind, op_id, kind) VALUES (?, ?, ?, ?, ?)",
        ("2026-09-24T00:00:00Z", "zk-1", str(kind), "op", "search"),
    )
    await db.commit()


async def test_a_version_one_store_refuses_a_cli_event_before_it_is_migrated(
    tmp_path: Path,
) -> None:
    """The condition the migration exists for, stated as the failure it prevents."""
    store_dir = tmp_path / ".zikaron"
    db_path = await _store_at_version_one(store_dir, _config(tmp_path))
    db = await aiosqlite.connect(db_path)
    try:
        with pytest.raises(aiosqlite.IntegrityError):
            await _record(db, ClientKind.CLI)
    finally:
        await db.close()


async def test_opening_with_migrate_brings_a_version_one_store_forward(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _store_at_version_one(store_dir, config)
    async with await Store.open(store_dir, config, migrate=True) as store:
        assert store.meta.schema_version == CURRENT_SCHEMA_VERSION
        for kind in ClientKind:
            await _record(store.connection, kind)
        written = await _count(store.connection, "SELECT count(*) FROM event")
    assert written == len(ClientKind)


async def test_every_kind_is_writable_against_a_store_this_build_created(tmp_path: Path) -> None:
    """The other half of the pair above: created and migrated stores are two different tables."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, FakeEmbedder("BAAI/bge-small-en-v1.5", 384)):
        pass
    async with await Store.open(store_dir, config) as store:
        for kind in ClientKind:
            await _record(store.connection, kind)
        written = await _count(store.connection, "SELECT count(*) FROM event")
    assert written == len(ClientKind)


async def test_opening_without_migrate_leaves_a_version_one_store_alone(tmp_path: Path) -> None:
    """The indexer and the MCP identity read open an older store and change nothing about it."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _store_at_version_one(store_dir, config)
    async with await Store.open(store_dir, config) as store:
        assert store.meta.schema_version == 1
        with pytest.raises(aiosqlite.IntegrityError):
            await _record(store.connection, ClientKind.CLI)
    async with await Store.open(store_dir, config) as reopened:
        assert reopened.meta.schema_version == 1


async def test_the_events_a_version_one_store_already_held_survive_the_rebuild(
    tmp_path: Path,
) -> None:
    """Every column, not only the count: the rebuild copies by position and a reordered column
    list would move `op_id` into `kind` without dropping a row."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    db_path = await _store_at_version_one(store_dir, config)
    db = await aiosqlite.connect(db_path)
    try:
        await db.execute(
            "INSERT INTO event (at, session_id, client_kind, op_id, kind, memory_uuid, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2026-01-01T00:00:00Z", "zk-old", "hook", "op-old", "surface", "uuid-1", "{}"),
        )
        await db.commit()
    finally:
        await db.close()

    async with await Store.open(store_dir, config, migrate=True) as store:
        rows = await store.connection.execute_fetchall(
            "SELECT at, session_id, client_kind, op_id, kind, memory_uuid, detail FROM event"
        )
    assert list(rows) == [
        ("2026-01-01T00:00:00Z", "zk-old", "hook", "op-old", "surface", "uuid-1", "{}")
    ]


async def test_the_rebuilt_table_carries_every_index_the_original_had(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _store_at_version_one(store_dir, config)
    async with await Store.open(store_dir, config, migrate=True) as store:
        rows = await store.connection.execute_fetchall(
            "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='event' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    assert [row[0] for row in rows] == sorted(
        statement.split()[2] for statement in ddl.EVENT_INDEXES
    )


async def test_migrating_a_store_already_at_this_version_does_nothing(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, FakeEmbedder("BAAI/bge-small-en-v1.5", 384)):
        pass
    async with await Store.open(store_dir, config, migrate=True) as store:
        before = await store.connection.execute_fetchall(
            "SELECT sql FROM sqlite_schema WHERE name='event'"
        )
    async with await Store.open(store_dir, config, migrate=True) as store:
        after = await store.connection.execute_fetchall(
            "SELECT sql FROM sqlite_schema WHERE name='event'"
        )
    assert list(before) == list(after)


async def test_a_step_that_raises_leaves_the_store_at_its_old_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transaction across every pending step, so an interrupted migration is not a third state.

    The substituted step drops a table before raising, since a step that fails without touching
    anything would pass this whether or not the transaction exists.
    """
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _store_at_version_one(store_dir, config)

    async def _explode(db: aiosqlite.Connection) -> None:
        await db.execute("DROP TABLE event")
        raise RuntimeError("interrupted")

    monkeypatch.setattr(
        migration, "MIGRATIONS", (migration.Migration(to_version=2, apply=_explode),)
    )
    with pytest.raises(RuntimeError):
        await Store.open(store_dir, config, migrate=True)

    async with await Store.open(store_dir, config) as store:
        assert store.meta.schema_version == 1
        surviving = await _count(
            store.connection, "SELECT count(*) FROM sqlite_schema WHERE name='event'"
        )
    assert surviving == 1


async def test_a_store_migrated_by_one_opener_is_at_the_new_version_for_the_next(
    tmp_path: Path,
) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _store_at_version_one(store_dir, config)
    async with await Store.open(store_dir, config, migrate=True):
        pass
    async with await Store.open(store_dir, config) as reader:
        assert reader.meta.schema_version == CURRENT_SCHEMA_VERSION
        await _record(reader.connection, ClientKind.CLI)


async def test_a_second_opener_that_read_the_old_version_does_no_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The version is decided inside the transaction, not from what the caller read before it.

    Two openers can both read version 1 before either acquires, so both call with
    `from_version=1`. Re-running the step would be *correct* — `DROP TABLE` takes its indexes with
    it, so the rebuild simply happens twice — which is why this counts the runs rather than
    checking the result: what the re-read buys is not correctness but half a second of copying a
    table that did not need copying.
    """
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    db_path = await _store_at_version_one(store_dir, config)
    runs = 0
    step = migration.MIGRATIONS[-1]

    async def _counted(db: aiosqlite.Connection) -> None:
        nonlocal runs
        runs += 1
        await step.apply(db)

    monkeypatch.setattr(
        migration,
        "MIGRATIONS",
        (migration.Migration(to_version=step.to_version, apply=_counted),),
    )
    db = await aiosqlite.connect(db_path)
    try:
        assert await migration.migrate(db, from_version=1) == CURRENT_SCHEMA_VERSION
        assert await migration.migrate(db, from_version=1) == CURRENT_SCHEMA_VERSION
        indexes = await _count(
            db,
            "SELECT count(*) FROM sqlite_schema WHERE type='index' AND tbl_name='event' "
            "AND name NOT LIKE 'sqlite_%'",
        )
    finally:
        await db.close()
    assert runs == 1, "the second call read the version inside the transaction and stopped"
    assert indexes == len(ddl.EVENT_INDEXES)


def test_version_twos_frozen_event_is_still_what_this_build_creates() -> None:
    """The step's DDL is a historical artifact, and this is the alarm on it moving.

    A step must produce the schema of the version it names. While version 2 is the newest, that is
    also what `ddl` creates — so the two agree today and this asserts it. **The day this fails is
    the day `event` moved**, and the answer is to leave `_V2_EVENT` alone and write the next step:
    changing it would make this step build the newer table and then fail copying a version-1
    store's rows into it, stranding every store that has not yet migrated.
    """
    assert migration._V2_EVENT.strip() == ddl.event_statement("event_migrated").strip()
    assert migration._V2_EVENT_INDEXES == ddl.EVENT_INDEXES
