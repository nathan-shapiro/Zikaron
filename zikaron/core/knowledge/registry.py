"""The `knowledge_bases` table in `memory.db`: what corpora exist, and what each one is called.

`schema.md` is the contract for this table's shape and for why it is created here rather than by
store creation; `knowledge-index.md` for what it means.

**Authority is split deliberately.** This table owns `name` and `description` — the two fields a
caller needs in order to *choose* a corpus without opening it. Everything else about a knowledge
base lives in that knowledge base's own database. The registry is also the sole authority on
*existence*: a row without a file is an empty knowledge base needing a build, and a file without a
row is an orphan nothing will open.
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
        raise InvalidNameError("a knowledge base's name cannot be empty or blank")
    return name.lower()


async def ensure_table(db: aiosqlite.Connection) -> None:
    """Create `knowledge_bases` if this store does not have it yet.

    Cheap enough to run on every open, and measured to be: `CREATE TABLE IF NOT EXISTS` against a
    table that already exists takes no write lock at all — it succeeds while another connection
    holds the writer lock — so the steady-state cost is a schema read, and the one occasion it
    contends is the one occasion it has real work to do.

    Must be called inside a transaction the caller owns. A bare `CREATE TABLE` with no transaction
    open runs in autocommit, which would leave the table behind after a caller's later statement
    failed and rolled back.
    """
    await db.execute(CREATE_TABLE)


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
    name whose corpus the next build would silently recreate.

    Raises:
        InvalidNameError: `name` is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`.
    """
    current = await require(db, name)
    await db.execute("DELETE FROM knowledge_bases WHERE id = ?", (str(current.id),))
    return current


async def find(db: aiosqlite.Connection, name: str) -> KnowledgeBase | None:
    """The corpus registered under `name`, or `None`.

    Raises:
        InvalidNameError: `name` is empty or blank.
    """
    stored = normalize_name(name)
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
    """
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
