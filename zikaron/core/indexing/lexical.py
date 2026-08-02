"""`memory_fts` maintenance: the lexical index, unchunked, over the whole record.

Invariant 13 and D28: the dense side is chunked and the lexical side is not, because BM25 already
applies document-length normalization, so chunking it would be redundant work against a mechanism
that is already correct. The asymmetry is easy to break by reflex, which is why it has an invariant
of its own and why this module indexes one document per memory.

`memory_fts` is an **external-content** table (`content='memory'`), which means SQLite maintains
nothing automatically: an `UPDATE` of `memory` leaves the index exactly as it was, with no error of
any kind. Every function here is therefore called explicitly by the write path, inside the same
transaction as the row it describes (invariant 2).
"""

from dataclasses import dataclass

import aiosqlite

#: `memory_fts`'s columns, in declaration order. The `'delete'` command below matches values to
#: columns **by position**, so this order is part of the contract rather than a formatting choice —
#: which is also why the values travel as a `Document` rather than as two loose strings.
_FTS_COLUMNS = "gist, content"


@dataclass(frozen=True, slots=True)
class Document:
    """One memory's indexed prose: the two columns `memory_fts` holds, in its own column order.

    A type rather than two parameters because every function here needs both together and the
    `'delete'` command is positional — a call that transposed them would remove postings for terms
    the row never had, leaving the real ones matchable, with no error to notice.
    """

    gist: str
    content: str


async def insert(db: aiosqlite.Connection, *, rowid: int, document: Document) -> None:
    """Index one memory's prose at `rowid`, which must be the `memory` row's own rowid.

    `rowid` is the linkage an external-content FTS5 table is built on (`content_rowid='rowid'`): a
    row indexed under any other value would match queries and then resolve to the wrong record, or
    to none.
    """
    await db.execute(
        f"INSERT INTO memory_fts (rowid, {_FTS_COLUMNS}) VALUES (?, ?, ?)",  # noqa: S608
        (rowid, document.gist, document.content),
    )


async def remove(db: aiosqlite.Connection, *, rowid: int, document: Document) -> None:
    """Remove one memory's postings, naming the values that were indexed rather than reading them.

    This is FTS5's `'delete'` command, and preferring it to `DELETE FROM memory_fts WHERE rowid = ?`
    is load-bearing rather than stylistic. The plain `DELETE` on an external-content table **reads
    the content table** to discover which terms to remove, so it is correct only while `memory`
    still holds the old prose — which means before the row is updated, and therefore before the
    version and receipt rungs have finished, since the update and those rungs are one indivisible
    step. Staging index work ahead of authorization is unsafe in the quietest possible way:
    invariant 10's carve-out **commits** a rejected call's audit event and receipt, so a `DELETE`
    staged before the version check would be durably committed by a *rejected* amend, leaving a
    live row with no lexical index and no error anywhere. Naming the values instead consults no
    table, so this runs after the update and nothing is staged before the call is authorized. It is
    the same command the operator erasure procedure uses, for the same reason.

    Args:
        rowid: the `memory` row's own rowid, as indexed.
        document: the prose **as it was when indexed** — the pre-write values on an amend.
    """
    await db.execute(
        f"INSERT INTO memory_fts (memory_fts, rowid, {_FTS_COLUMNS}) "  # noqa: S608
        "VALUES ('delete', ?, ?, ?)",
        (rowid, document.gist, document.content),
    )


async def resync(
    db: aiosqlite.Connection, *, rowid: int, before: Document, after: Document
) -> None:
    """Replace one memory's postings: remove the old prose's, then index the new prose.

    Both halves are required, and in this order. Indexing the new prose without removing the old
    leaves every stale term matchable, which is worse than a missing index: a memory the agent
    repaired goes on being retrieved by the wording it was repaired *out of*.
    """
    await remove(db, rowid=rowid, document=before)
    await insert(db, rowid=rowid, document=after)
