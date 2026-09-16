"""`chunks_fts` maintenance: the lexical arm, one row per chunk, kept in step by hand.

`chunks_fts` is an **external-content** table over `chunks`, which means SQLite maintains nothing
automatically: deleting a `chunks` row leaves its postings exactly where they were, with no error of
any kind. Every function here is therefore called explicitly, inside the same transaction as the
chunk row it describes.

**The path is its own column rather than being pasted into the text.** A chunk's text is a verbatim
copy of its file's lines, so anything prepended to it would come back out in a snippet; a second
column keeps the path searchable — its components tokenize into real words — without putting it in
the bytes a reader is handed.
"""

from dataclasses import dataclass

import aiosqlite

#: `chunks_fts`'s columns, in declaration order. FTS5's `'delete'` command matches values to columns
#: **by position**, so this order is part of the contract rather than a formatting choice — which is
#: also why the values travel as a `Document` rather than as two loose strings.
_FTS_COLUMNS = "text, path"


@dataclass(frozen=True, slots=True)
class Document:
    """One chunk's indexed prose: the two columns `chunks_fts` holds, in its own column order.

    A type rather than two parameters because every function here needs both together and the
    `'delete'` command is positional — a call that transposed them would remove postings for terms
    the row never had and leave the real ones matchable, with no error to notice.
    """

    text: str
    path: str


async def insert(db: aiosqlite.Connection, *, chunk_id: int, document: Document) -> None:
    """Index one chunk's prose at `chunk_id`, which must be the `chunks` row's own id.

    That id is the linkage an external-content table is built on (`content_rowid='id'`): a row
    indexed under any other value would match queries and then resolve to the wrong chunk, or to
    none.
    """
    await db.execute(
        f"INSERT INTO chunks_fts (rowid, {_FTS_COLUMNS}) VALUES (?, ?, ?)",  # noqa: S608 — a source-level column list; every value is bound.
        (chunk_id, document.text, document.path),
    )


async def remove(db: aiosqlite.Connection, *, chunk_id: int, document: Document) -> None:
    """Remove one chunk's postings, naming the values that were indexed.

    **The values must be the ones actually indexed, and supplying wrong ones fails silently.**
    FTS5's `'delete'` command takes the row's id and its original column values; given anything else
    it is accepted, removes nothing, and leaves the row matchable — measured, with the index's own
    consistency check still reporting OK afterwards. So a caller reads `chunks.path` and
    `chunks.text` **before** deleting the content rows: an implementation that deletes them first
    has nothing correct left to pass, and corrupts the index while every call returns success.
    """
    await db.execute(
        f"INSERT INTO chunks_fts (chunks_fts, rowid, {_FTS_COLUMNS}) "  # noqa: S608 — a source-level column list; every value is bound.
        "VALUES ('delete', ?, ?, ?)",
        (chunk_id, document.text, document.path),
    )
