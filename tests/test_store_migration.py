"""Bringing a store forward from an older schema version, and what other openers do meanwhile.

The tests that matter here run against a store actually built at an older version — a fresh store is
at `CURRENT_SCHEMA_VERSION` and exercises no step at all, so a suite that only creates stores would
pass with the migration deleted.
"""

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.events import ClientKind, EventKind
from zikaron.core.store import ddl, meta, migration
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import CURRENT_SCHEMA_VERSION, Store
from zikaron.knowledge.indexer import build_log

#: Version 1's `event`, literal rather than derived from `ddl`. It is a historical artifact: a
#: version that is done moving, which is exactly what `ddl` is not. No step declares it, since the
#: first step is the one that produces version 2.
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

#: What a build at each older version left `event` as. Version 2's is its own step's frozen text
#: under the table's final name rather than a second copy: that text is already frozen once, and a
#: transcription of it here could drift from the thing it is meant to reproduce.
_EVENT_AT_VERSION: Final[Mapping[int, str]] = {
    1: _NARROW_EVENT,
    2: migration._V2_EVENT.replace("event_migrated", "event"),
    3: migration._V3_EVENT.replace("event_migrated", "event"),
}


def _config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


async def _store_at_version(store_dir: Path, config: EffectiveConfig, version: int) -> Path:
    """A store as a build at `version` left it: that version's `CHECK`, and `meta` saying so.

    Built by creating a current store and putting `event` back the way that version had it, rather
    than by carrying a fixture database: a checked-in binary would stop tracking the rest of the
    schema the moment anything else in it moved.
    """
    async with await Store.create(store_dir, config, FakeEmbedder("BAAI/bge-small-en-v1.5", 384)):
        pass
    db_path = store_dir / "memory.db"
    db = sqlite3.connect(db_path)
    try:
        db.execute("DROP TABLE event")
        db.execute(_EVENT_AT_VERSION[version])
        for statement in ddl.EVENT_INDEXES:
            db.execute(statement)
        db.execute(
            "UPDATE meta SET value = ? WHERE key = ?", (str(version), meta.SCHEMA_VERSION_KEY)
        )
        db.commit()
    finally:
        db.close()
    return db_path


async def _store_at_version_one(store_dir: Path, config: EffectiveConfig) -> Path:
    return await _store_at_version(store_dir, config, 1)


async def _count(db: aiosqlite.Connection, sql: str) -> int:
    rows = list(await db.execute_fetchall(sql))
    return int(rows[0][0])


async def _record(
    db: aiosqlite.Connection, kind: ClientKind, event_kind: EventKind = EventKind.SEARCH
) -> None:
    await db.execute(
        "INSERT INTO event (at, session_id, client_kind, op_id, kind) VALUES (?, ?, ?, ?, ?)",
        ("2026-09-24T00:00:00Z", "zk-1", str(kind), "op", str(event_kind)),
    )
    await db.commit()


async def test_a_version_one_store_refuses_a_cli_event_before_it_is_migrated(
    tmp_path: Path,
) -> None:
    """The condition the first migration exists for, stated as the failure it prevents."""
    store_dir = tmp_path / ".zikaron"
    db_path = await _store_at_version_one(store_dir, _config(tmp_path))
    db = await aiosqlite.connect(db_path)
    try:
        with pytest.raises(aiosqlite.IntegrityError):
            await _record(db, ClientKind.CLI)
    finally:
        await db.close()


@pytest.mark.parametrize(
    ("client_kind", "event_kind"),
    [
        (ClientKind.MCP, EventKind.CALL),
        (ClientKind.INDEXER, EventKind.KNOWLEDGE_BUILD),
    ],
)
async def test_a_version_two_store_refuses_the_new_rows_before_it_is_migrated(
    tmp_path: Path, client_kind: ClientKind, event_kind: EventKind
) -> None:
    """Both halves of version 3, each shown as the insert that fails without it.

    Two `CHECK`s widen in one step, so a test that exercised only one would pass with half the step
    written — and the half left out is whichever one the author was not looking at.
    """
    store_dir = tmp_path / ".zikaron"
    db_path = await _store_at_version(store_dir, _config(tmp_path), 2)
    db = await aiosqlite.connect(db_path)
    try:
        with pytest.raises(aiosqlite.IntegrityError):
            await _record(db, client_kind, event_kind)
    finally:
        await db.close()


async def test_migrating_a_version_two_store_admits_both_new_kinds(tmp_path: Path) -> None:
    """The 2→3 step on its own, rather than only as part of the walk from version 1.

    A store at 2 is what every store this project has in the field is, so the step that moves it is
    the one that runs in production; reaching version 3 only through a version-1 store would leave
    that path covered by nothing.
    """
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _store_at_version(store_dir, config, 2)
    async with await Store.open(store_dir, config, migrate=True) as store:
        assert store.meta.schema_version == CURRENT_SCHEMA_VERSION
        await _record(store.connection, ClientKind.MCP, EventKind.CALL)
        await _record(store.connection, ClientKind.INDEXER, EventKind.KNOWLEDGE_BUILD)
        written = await _count(store.connection, "SELECT count(*) FROM event")
    assert written == 2


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


@pytest.mark.parametrize("admits", [False, True])
async def test_the_version_a_build_waits_for_is_the_first_that_admits_its_row(
    tmp_path: Path, admits: bool
) -> None:
    """`build_log.FIRST_SCHEMA_VERSION` against the `CHECK`s, not against an already-widened table.

    **Both arms are needed and the pair has to be absolute**, which is the trap here. The build's
    own tests edit `meta` and leave the table at 3, so they exercise the *guard* and not the
    *number*: set the constant to 2 and they stay green while a build against a real schema-2 store
    writes into a `CHECK` that refuses it. A first attempt here had the same defect, for the reason
    it asked only whether `FIRST_SCHEMA_VERSION - 1` refuses, which is true of *any* value, since
    every version below 3 refuses. What binds the number is the other arm: the version it names must
    **admit** the row.
    """
    version = build_log.FIRST_SCHEMA_VERSION - (0 if admits else 1)
    store_dir = tmp_path / f"at-{version}"
    await _store_at_version(store_dir, _config(tmp_path), version)
    db = await aiosqlite.connect(store_dir / "memory.db")
    try:
        if admits:
            await _record(db, ClientKind.INDEXER, EventKind.KNOWLEDGE_BUILD)
            assert await _count(db, "SELECT count(*) FROM event") == 1
        else:
            with pytest.raises(aiosqlite.IntegrityError):
                await _record(db, ClientKind.INDEXER, EventKind.KNOWLEDGE_BUILD)
    finally:
        await db.close()


def test_the_newest_steps_frozen_event_is_still_what_this_build_creates() -> None:
    """A step's DDL is a historical artifact, and this is the alarm on it moving.

    A step must produce the schema of the version it names, so only the **newest** step's text can
    agree with what `ddl` creates; every earlier one is frozen at a shape `ddl` has moved past.
    **The day this fails is the day `event` moved again**, and the answer is to leave the literal
    alone, write the next step with its own frozen copy, and re-point this test at it: editing the
    old text would make that step build the newer table and then fail copying an older store's rows
    into it, stranding every store that has not yet migrated.
    """
    assert migration._V3_EVENT.strip() == ddl.event_statement("event_migrated").strip()
    assert migration._EVENT_INDEXES == ddl.EVENT_INDEXES
