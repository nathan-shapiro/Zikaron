"""The `knowledge_bases` table in `memory.db`: what corpora exist, and what each one is called.

`schema.md` is the contract for this table's shape and for why it is created here rather than by
store creation; `knowledge-index.md` for what it means.

**Authority is split deliberately.** This table owns `name` and `description` — the two fields a
caller needs in order to *choose* a corpus without opening it. Everything else about a knowledge
base lives in that knowledge base's own database. The registry is also the sole authority on
*existence*: a row without a file is a knowledge base whose definition is gone, reported as empty
and rebuilt by removing the name and adding it again, and a file without a row is an orphan nothing
will open.
"""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

import aiosqlite

from zikaron.core.knowledge import meta
from zikaron.core.knowledge.errors import (
    DuplicateNameError,
    InvalidNameError,
    UnknownKnowledgeBaseError,
)
from zikaron.core.store.transactions import in_one_transaction, propagate

#: The one table the knowledge index keeps in `memory.db`. Named apart from the DDL below because
#: `ensure_table` asks whether it is there before creating it, and two spellings of one table name
#: is one way for the question and the answer to be about different tables.
TABLE_NAME: Final = "knowledge_bases"

#: Transcribed from `schema.md`, which is the contract for it; a test compares the two.
#:
#: `IF NOT EXISTS` is load-bearing rather than defensive. This is the **only** site that creates
#: the table, for every store alike including one created before the table existed, and that is
#: what lets `memory.db`'s `schema_version` stay where it is: the change is additive, so no older
#: build needs to refuse the store, and no second creation path exists to disagree with this one.
CREATE_TABLE: Final = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL,
  created_at  TEXT NOT NULL,

  CHECK (length(trim(name)) > 0),
  CHECK (name = lower(name))
)
"""


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    """One registered corpus, as the registry holds it.

    `id` is a `UUID` rather than its string form because it names a file: keeping it typed is what
    makes a path built from it unforgeable, and it means a registry row whose `id` column has been
    corrupted into something path-shaped fails when it is read rather than when it is joined onto
    a directory.
    """

    id: UUID
    name: str
    description: str
    created_at: str


def _is_unique_violation(error: sqlite3.IntegrityError) -> bool:
    """Whether this integrity failure is the name collision, rather than some other constraint.

    Read off the exception's own extended SQLite result code rather than its message text: the
    message is prose that varies between builds, while the code is the contract SQLite publishes.
    The distinction is not academic — one `IntegrityError` class covers three genuinely different
    faults on this table. A `UNIQUE` failure is the name already being taken, which is an ordinary
    refusal a caller acts on; a `CHECK` failure means a value reached the insert un-normalized,
    which is a defect in this module; and a `PRIMARY KEY` failure means two uuid4 values collided,
    which is not something to report as a name conflict. Collapsing them would hand a caller a
    confident, wrong explanation for two of the three.
    """
    return error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE


def normalize_name(name: str) -> str:
    """The stored form of a supplied name: lower-cased, and nothing else.

    `str.lower()` rather than `str.casefold()`. Casefold is the right tool for caseless
    *comparison*, but this is a canonical value being stored, and its extra folding — `ß` becoming
    `ss` — would alter names more than whoever typed one expects.

    Lower-casing is a collision concern rather than a filesystem one, since no name reaches a
    path. `Docs` and `docs` *could* safely be two corpora; they should not be, because whoever
    created one and later asks for the other gets a confident miss, and not doing that is this
    system's whole job.

    **Case is the only normalization**, so surrounding whitespace is preserved rather than
    stripped: a name is free-form text, and silently returning something other than what was
    asked for is a worse answer than storing it as given. The one thing a name may not be is
    blank, since a name is how a corpus is asked for again.

    Raises:
        InvalidNameError: the name is empty or is entirely whitespace.
    """
    if name.strip() == "":
        raise InvalidNameError("a knowledge base's name cannot be empty or blank", value=name)
    return name.lower()


async def ensure_table(db: aiosqlite.Connection) -> None:
    """Create `knowledge_bases` if this store does not have it yet.

    **Only a write creates the table**: `knowledge_add`, and the indexer, each on its writer and so
    under `IMMEDIATE`. A read on a store without it answers from the presence read in `find` and
    `list_all` — an empty registry — so no read path ever writes DDL, and a knowledge read's `call`
    row is its only `memory.db` write on every store.

    `CREATE TABLE IF NOT EXISTS` against a table that already exists still asks for the write lock
    (`research/m33-registry-ensure-takes-the-write-lock.md`), which is why a read must never reach
    this function; its two callers already hold that lock.

    Must be called inside a transaction the caller owns. A bare `CREATE TABLE` with no transaction
    open runs in autocommit, which would leave the table behind after a caller's later statement
    failed and rolled back.
    """
    if await _table_exists(db):
        return
    await db.execute(CREATE_TABLE)


async def _table_exists(db: aiosqlite.Connection) -> bool:
    # `sqlite_master`, not its `sqlite_schema` alias, which SQLite added in 3.33.0. D35 declares no
    # SQLite floor for a host-Python install, and the store's own two readers of this table
    # (`core/store/store.py`, `core/knowledge/database.py`) use the older name — so a floor must not
    # arrive here silently, in a statement nothing would fail on until somebody's build was old.
    rows = await db.execute_fetchall(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE_NAME,)
    )
    return bool(list(rows))


async def ensure(db: aiosqlite.Connection) -> None:
    """`ensure_table` in a transaction of its own, for the indexer, which has none to run it in."""
    await in_one_transaction(db, ensure_table, failure=propagate)


async def lookup(db: aiosqlite.Connection, name: str) -> KnowledgeBase:
    """`require`, in one transaction of its own that covers nothing else.

    What every verb resolves a corpus through. On the service's writer a statement outside a
    transaction would run inside another request's open one and read its uncommitted rows, so the
    registry read is a transaction; and it is only the registry read, so no corpus is opened while
    the writer's lock or a read snapshot is held.

    Raises:
        InvalidNameError: `name` is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`, or the store has no registry.
    """

    async def _work(connection: aiosqlite.Connection) -> KnowledgeBase:
        return await require(connection, name)

    return await in_one_transaction(db, _work, failure=propagate)


async def lookup_each(db: aiosqlite.Connection, names: Sequence[str]) -> tuple[KnowledgeBase, ...]:
    """`require` for each of `names`, in order, in one transaction — see `lookup`.

    Raises:
        InvalidNameError: a name is empty or blank.
        UnknownKnowledgeBaseError: a name is registered under nothing.
    """

    async def _work(connection: aiosqlite.Connection) -> tuple[KnowledgeBase, ...]:
        return tuple([await require(connection, name) for name in names])

    return await in_one_transaction(db, _work, failure=propagate)


async def lookup_all(db: aiosqlite.Connection) -> tuple[KnowledgeBase, ...]:
    """`list_all`, in one transaction of its own — see `lookup`."""
    return await in_one_transaction(db, list_all, failure=propagate)


async def insert(
    db: aiosqlite.Connection, *, name: str, description: str, created_at: str
) -> KnowledgeBase:
    """Register a new corpus under a freshly generated id, or refuse a name already taken.

    The id is generated here rather than supplied, which is what makes the database's path
    unforgeable: there is no parameter a caller could use to influence where its file lands.

    Raises:
        InvalidNameError: `name` is empty or blank.
        DuplicateNameError: the normalized name is already registered. Enforced by the table's own
            `UNIQUE` constraint rather than by a preceding `SELECT`, which could race.
    """
    stored = normalize_name(name)
    kb_id = uuid4()
    try:
        await db.execute(
            "INSERT INTO knowledge_bases (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (str(kb_id), stored, description, created_at),
        )
    except aiosqlite.IntegrityError as error:
        if not _is_unique_violation(error):
            raise
        raise DuplicateNameError(f"a knowledge base named {stored!r} already exists") from error
    return KnowledgeBase(id=kb_id, name=stored, description=description, created_at=created_at)


async def rename(db: aiosqlite.Connection, *, name: str, new_name: str) -> KnowledgeBase:
    """Change a corpus's name, touching no file.

    Safe while an indexer is running and deliberately does not check the lock: the name lives in
    this table alone, so nothing about a rename can disturb a database being written.

    Raises:
        InvalidNameError: either name is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`.
        DuplicateNameError: `new_name` is already taken.
    """
    current = await require(db, name)
    stored = normalize_name(new_name)
    try:
        await db.execute(
            "UPDATE knowledge_bases SET name = ? WHERE id = ?", (stored, str(current.id))
        )
    except aiosqlite.IntegrityError as error:
        if not _is_unique_violation(error):
            raise
        raise DuplicateNameError(f"a knowledge base named {stored!r} already exists") from error
    return KnowledgeBase(
        id=current.id,
        name=stored,
        description=current.description,
        created_at=current.created_at,
    )


async def delete(db: aiosqlite.Connection, *, name: str) -> KnowledgeBase:
    """Remove a corpus's registry row and return what it held.

    A hard `DELETE`. The memory store never deletes a row — it retires one, so a bad session
    cannot destroy what was learned — and that rule deliberately does not reach here: this row is
    a pointer to a corpus somebody has explicitly asked to destroy, it records nothing that was
    learned, and keeping it would leave a name resolving to nothing.

    Deleting the row is only the first half of destroying a knowledge base. The caller unlinks the
    file afterwards, in that order, so an interruption leaves an unreferenced file rather than a
    name that still answers for a corpus somebody asked to destroy — which nothing could rebuild
    and only another `remove` could clear.

    Raises:
        InvalidNameError: `name` is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`.
    """
    current = await require(db, name)
    await db.execute("DELETE FROM knowledge_bases WHERE id = ?", (str(current.id),))
    return current


async def find(db: aiosqlite.Connection, name: str) -> KnowledgeBase | None:
    """The corpus registered under `name`, or `None` — including on a store with no registry.

    Raises:
        InvalidNameError: `name` is empty or blank.
    """
    stored = normalize_name(name)
    if not await _table_exists(db):
        return None
    rows = await db.execute_fetchall(
        "SELECT id, name, description, created_at FROM knowledge_bases WHERE name = ?", (stored,)
    )
    found = list(rows)
    if not found:
        return None
    return _row(found[0])


async def require(db: aiosqlite.Connection, name: str) -> KnowledgeBase:
    """The corpus registered under `name`.

    Raises:
        InvalidNameError: `name` is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`.
    """
    found = await find(db, name)
    if found is None:
        raise UnknownKnowledgeBaseError(f"no knowledge base named {normalize_name(name)!r}")
    return found


async def list_all(db: aiosqlite.Connection) -> tuple[KnowledgeBase, ...]:
    """Every registered corpus, ordered by name.

    Ordered in SQL rather than by the caller so that two runs over one store produce the same
    listing — a caller comparing output across runs should be comparing content, not sort luck.
    Empty on a store with no registry.
    """
    if not await _table_exists(db):
        return ()
    rows = await db.execute_fetchall(
        "SELECT id, name, description, created_at FROM knowledge_bases ORDER BY name"
    )
    return tuple(_row(row) for row in rows)


def _row(row: Sequence[object]) -> KnowledgeBase:
    """One result row as a `KnowledgeBase`, with its `id` parsed rather than trusted.

    Parsing here is what keeps the path unforgeable even against a registry somebody has edited
    by hand: an `id` that is not a uuid never becomes a `UUID`, so it never reaches
    `knowledge_db_path` and never names a file. Through the same parser the knowledge base's own
    `meta` uses, so one value is not fatal in one place and accepted in the other.
    """
    kb_id, name, description, created_at = row
    return KnowledgeBase(
        id=meta.parse_id(str(kb_id)),
        name=str(name),
        description=str(description),
        created_at=str(created_at),
    )
