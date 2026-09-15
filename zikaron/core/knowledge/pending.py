"""The `pending` table: what the walk phase found changed and the index phase has not yet done.

It exists as a table rather than as a counter because the search path has to read it: a result
whose file has a row here is reported as stale, and "the walk found this changed" needs a
persisted representation for a process that is not the one scanning.

**Replaced wholesale, never appended to.** A file edited and then reverted between two scans
correctly loses its row, where an append would leave it flagged stale forever.

**Nothing sweeps it, and that is the point.** Rows surviving a crash still name every path the
dead scan noticed and never reindexed, and they are the only thing keeping a stale flag honest in
the window between that crash and the next scan. A startup sweep would look tidy and would delete
exactly the signal the table carries.
"""

from collections.abc import Iterable

import aiosqlite


async def replace_all(db: aiosqlite.Connection, paths: Iterable[str], *, noticed_at: str) -> None:
    """Make `paths` the whole of what is pending, discarding whatever was there.

    Called from inside the walk phase's own transaction, so the table is never briefly empty for a
    reader: the previous scan's rows and this scan's replace atomically.
    """
    await db.execute("DELETE FROM pending")
    await db.executemany(
        "INSERT INTO pending (path, noticed_at) VALUES (?, ?)",
        [(path, noticed_at) for path in paths],
    )


async def dispose(db: aiosqlite.Connection, path: str) -> None:
    """Remove one path, in the transaction that disposed of it.

    Every disposal is one of three — the file was reindexed, deleted, or recorded as a skip,
    whether text detection or the size cap refused it — and each removes its row as part of its own
    transaction rather than afterwards. A row removed separately would be a window in which the
    index and the pending list disagree about work that is already done.
    """
    await db.execute("DELETE FROM pending WHERE path = ?", (path,))


async def paths(db: aiosqlite.Connection) -> list[str]:
    """Every pending path, in the order the index phase will dispose of them.

    Ordered by path, because the order decides which files a partially-completed scan has
    committed and an arbitrary one makes two runs over one corpus incomparable.
    """
    rows = await db.execute_fetchall("SELECT path FROM pending ORDER BY path")
    return [str(path) for (path,) in rows]


async def count(db: aiosqlite.Connection) -> int:
    """How many paths are still waiting to be disposed of."""
    rows = await db.execute_fetchall("SELECT count(*) FROM pending")
    ((found,),) = list(rows)
    return int(found)
