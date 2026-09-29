"""Bringing a store forward from an older schema version to this build's.

`schema.md` §"Migration posture" is normative: which versions open, which opener may move a store
through them, and when the version moves — *when a binary at either version would use the store
wrongly*, which is a wider test than an old binary misreading a new store.

**Only one opener migrates.** `service/context.py` holds the store at startup with write intent and
is the only caller that asks for it; the indexer and the MCP identity read open a store at any
supported version and change nothing. A store the service has not yet reopened is therefore readable
at its old version by everything else, which is what keeps a version bump from being a flag day.

**A migration is idempotent by position, not by inspection.** Each step declares the version it
produces, and a step runs only when `meta.schema_version` is below it — so reopening a migrated
store runs nothing and reads nothing extra.
"""

from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Final

import aiosqlite

from zikaron.core.store import meta


@dataclass(frozen=True, slots=True)
class Migration:
    """One step, and the `meta.schema_version` a store carries once it has run.

    `apply` runs inside a transaction this module owns and must neither begin nor commit one: a step
    that committed halfway would leave a store at a version its `meta` does not name.
    """

    to_version: int
    apply: Callable[[aiosqlite.Connection], Coroutine[object, object, None]]


#: Version 2's `event`, **frozen**. A step must produce the schema of the version it names, not
#: whatever `ddl` says today: a later step that changes `event` would otherwise make this one build
#: that newer table and then fail copying a v1 store's rows into it, so every store still at version
#: 1 would stop migrating. Version 3 froze its own copy below, which is that rule in action.
_V2_EVENT: Final = """
CREATE TABLE event_migrated (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL,
  session_id  TEXT,
  client_kind TEXT NOT NULL CHECK (client_kind IN ('hook', 'mcp', 'consolidator', 'cli')),
  op_id       TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN (
                'surface_call', 'surface', 'search', 'fetch', 'remember', 'amend', 'retire',
                'merge', 'promote', 'discard', 'dedup_offered', 'version_conflict',
                'no_receipt', 'group_served', 'consolidate_run'
              )),
  memory_uuid TEXT,
  detail      TEXT
)"""

#: Version 3's, frozen on the same rule. `test_store_migration.py` asserts this equals `ddl`'s text
#: *today* — it is the newest step, so the two must agree — and the day that fails is the day the
#: table moved again, at which point this literal stays put and the next step is written.
_V3_EVENT: Final = """
CREATE TABLE event_migrated (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL,
  session_id  TEXT,
  client_kind TEXT NOT NULL CHECK (client_kind IN ('hook', 'mcp', 'consolidator', 'cli',
                                                   'indexer')),
  op_id       TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN (
                'surface_call', 'surface', 'search', 'fetch', 'remember', 'amend', 'retire',
                'merge', 'promote', 'discard', 'dedup_offered', 'version_conflict',
                'no_receipt', 'group_served', 'consolidate_run', 'call', 'knowledge_build'
              )),
  memory_uuid TEXT,
  detail      TEXT
)"""

#: `event`'s indexes, identical at versions 2 and 3 — neither step touched a column any of them
#: names. Shared rather than frozen per step: a step that *did* change one would carry its own copy,
#: on the same rule as the table text, and sharing until then keeps the two steps from disagreeing
#: about a set they both rebuild unchanged.
_EVENT_INDEXES: Final[tuple[str, ...]] = (
    "CREATE INDEX idx_event_kind_at ON event(kind, at)",
    "CREATE INDEX idx_event_session ON event(session_id)",
    "CREATE INDEX idx_event_session_kind ON event(session_id, client_kind)",
    "CREATE INDEX idx_event_op ON event(op_id)",
    "CREATE INDEX idx_event_uuid_at ON event(memory_uuid, at)",
)


async def _rebuild_event(db: aiosqlite.Connection, statement: str) -> None:
    """Replace `event` with the table `statement` declares, carrying every row across.

    SQLite has no `ALTER TABLE ... ADD/DROP CONSTRAINT` and no `ALTER COLUMN`, so a `CHECK` changes
    only by rebuilding the table around it. Rewriting `sqlite_schema.sql` under `PRAGMA
    writable_schema` is far faster and bypasses every validation SQLite has, leaving a malformed
    schema undetected until the next open. This route measures ~530 ms against a 25,836-event store
    (`spikes/m31_check_widening.py`), paid once, behind a socket that is not yet bound.

    `statement` creates `event_migrated`, not `event`, and each step passes its own frozen text.
    """
    await db.execute(statement)
    await db.execute("INSERT INTO event_migrated SELECT * FROM event")
    await db.execute("DROP TABLE event")
    await db.execute("ALTER TABLE event_migrated RENAME TO event")
    for index in _EVENT_INDEXES:
        await db.execute(index)


async def _widen_event_client_kind(db: aiosqlite.Connection) -> None:
    """Rebuild `event` so its `client_kind` `CHECK` admits `cli`."""
    await _rebuild_event(db, _V2_EVENT)


async def _widen_event_for_the_access_log(db: aiosqlite.Connection) -> None:
    """Rebuild `event` so it admits the access log and the build log, in one pass.

    Two `CHECK`s widen together — `kind` for `call` and `knowledge_build`, `client_kind` for
    `indexer` — because the rebuild is what costs and it is amortised across everything added in it.
    A step per kind would pay that half-second twice and strand stores at two different versions.
    """
    await _rebuild_event(db, _V3_EVENT)


#: Every step this build knows, in the order they run. `store.py` declares
#: `CURRENT_SCHEMA_VERSION` separately and `test_store.py` asserts it equals the last `to_version`,
#: so neither can move without the other.
MIGRATIONS: Final[Sequence[Migration]] = (
    Migration(to_version=2, apply=_widen_event_client_kind),
    Migration(to_version=3, apply=_widen_event_for_the_access_log),
)


async def migrate(db: aiosqlite.Connection, *, from_version: int) -> int:
    """Run every step above `from_version`, in one transaction, and return the version reached.

    Whether anything is pending is decided here rather than by the caller, so a store already at
    this build's version takes the same path as one that needs work and gets an early return.

    One transaction across all pending steps rather than one each: a store interrupted between two
    steps would sit at a version no build in existence implements, and there is no third state worth
    having between "the old schema" and "this one".

    **The version is read again inside the transaction, and that read is what decides.** The caller
    read `meta` before `BEGIN IMMEDIATE` acquired, so another opener can have migrated the store in
    between. Re-running the steps over an already-migrated schema is *correct* — `DROP TABLE` takes
    its indexes with it, so the rebuild simply happens twice — but it is half a second of copying a
    table that did not need copying, measured on a 25,836-event store. The re-read makes the second
    opener a no-op instead. One service per store makes even that unreachable today; this keeps the
    cost at zero without depending on that.
    """
    if not any(step.to_version > from_version for step in MIGRATIONS):
        return from_version
    await db.execute("BEGIN IMMEDIATE")
    try:
        current = await _recorded_version(db)
        pending = [step for step in MIGRATIONS if step.to_version > current]
        if not pending:
            await db.rollback()
            return current
        for step in pending:
            await step.apply(db)
        reached = pending[-1].to_version
        await db.execute(
            "UPDATE meta SET value = ? WHERE key = ?", (str(reached), meta.SCHEMA_VERSION_KEY)
        )
    except BaseException:
        await db.rollback()
        raise
    await db.commit()
    return reached


async def _recorded_version(db: aiosqlite.Connection) -> int:
    """`meta.schema_version` as it stands right now, read for a decision inside a transaction."""
    rows = list(
        await db.execute_fetchall(
            "SELECT value FROM meta WHERE key = ?", (meta.SCHEMA_VERSION_KEY,)
        )
    )
    ((value,),) = rows
    return int(value)
