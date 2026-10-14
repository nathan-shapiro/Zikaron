"""Bringing one knowledge base's database from schema 1 to schema 4.

`knowledge-index.md` §7.7.1 is normative. The step adds `files`' four link columns and `meta`'s four
link counters, reads every row's link from its stored chunks, and records it against the row's
`content_hash` — in one `BEGIN IMMEDIATE` transaction that reads the version again first, so two
processes migrating one database at once leave it migrated once, and one stopped before its commit
leaves it at schema 1, whole.

**A corpus schema version is the `memory.db` version that introduced its shape**, so a corpus is
brought no further forward than the store its opener opened: a process whose store is below version
4 builds and serves a corpus at schema 1 and migrates nothing. A store is therefore never behind its
corpora — even when an old service, still running across an upgrade, spawns a build from the new
code. The opener passes the answer down as `migrate`.
"""

from typing import Final

import aiosqlite

from zikaron.core.knowledge import link_store, meta
from zikaron.core.store.transactions import in_one_transaction, propagate

#: Version 4's columns, **frozen**: a step produces the schema of the version it names rather than
#: whatever `ddl` says today, so a later change to `files` cannot change what this step builds.
#: Added at the end of the table, which is where `ddl` declares them, so a migrated table and a
#: created one have the same columns in the same order.
_V4_COLUMNS: Final[tuple[str, ...]] = (
    "ALTER TABLE files ADD COLUMN link_read_from TEXT",
    "ALTER TABLE files ADD COLUMN link_declared INTEGER CHECK (link_declared IN (0, 1))",
    "ALTER TABLE files ADD COLUMN source_path TEXT",
    "ALTER TABLE files ADD COLUMN source_blob TEXT",
)

#: Version 4's counters, frozen on the same rule.
_V4_COUNTERS: Final[tuple[str, ...]] = (
    "results_linked",
    "results_source_changed",
    "results_source_missing",
    "results_source_unverifiable",
)

_FROM_VERSION: Final = 1
_TO_VERSION: Final = 4


def may_migrate(store_version: int) -> bool:
    """Whether a process that opened `memory.db` at `store_version` may bring a corpus forward: a
    step to corpus version N runs only for an opener whose store is at N or later."""
    return store_version >= _TO_VERSION


async def _recorded_version(db: aiosqlite.Connection) -> int:
    rows = list(
        await db.execute_fetchall(
            "SELECT value FROM meta WHERE key = ?", (meta.SCHEMA_VERSION_KEY,)
        )
    )
    ((value,),) = rows
    return int(value)


async def migrate(db: aiosqlite.Connection) -> bool:
    """Bring this corpus from schema 1 to schema 4, and say whether it moved.

    A corpus at any other version is left as it is. The caller holds no transaction on `db`.

    Raises:
        aiosqlite.Error: the write lock was not had within the connection's `busy_timeout`, or a
            statement failed. Nothing was written.
    """

    async def _work(connection: aiosqlite.Connection) -> bool:
        if await _recorded_version(connection) != _FROM_VERSION:
            return False
        for statement in _V4_COLUMNS:
            await connection.execute(statement)
        await connection.executemany(
            "INSERT INTO meta (key, value) VALUES (?, '0') ON CONFLICT(key) DO NOTHING",
            [(key,) for key in _V4_COUNTERS],
        )
        await link_store.write_records(
            connection, await link_store.records_of_every_row(connection)
        )
        await connection.execute(
            "UPDATE meta SET value = ? WHERE key = ?",
            (str(_TO_VERSION), meta.SCHEMA_VERSION_KEY),
        )
        return True

    return await in_one_transaction(db, _work, failure=propagate, immediate=True)
