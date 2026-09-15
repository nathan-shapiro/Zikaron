"""At most one indexer per knowledge base, as three `meta` rows and a liveness probe.

**This is deliberately a weaker test than the consolidation lease uses, and the difference is the
point.** That lease is taken over only by an explicit human act, because a spurious takeover there
destroys a worker's in-flight *reasoning*. An indexer has no reasoning in flight: it is code
walking a filesystem, and a wrongly reclaimed lock costs one rescan, which resuming from the
`files` table makes idempotent. So a probe of whether the recorded process is alive is enough here
where it would not be there.

**A lock recorded by another host is never reclaimed automatically**, because a local process
probe says nothing about a foreign one. The conservative reading is also the honest one — we
cannot show the holder is dead — and it composes into a knowledge base nothing can manage until an
operator clears the lock, which is why the age of the lock is reported for a human to judge.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

import aiosqlite

from zikaron.core.knowledge import database, meta
from zikaron.core.knowledge.errors import IndexerBusyError

#: The three keys one holder writes. Cleared together, because two of the three left behind would
#: describe a holder nothing can identify.
LOCK_KEYS: tuple[str, ...] = (
    meta.LOCK_PID_KEY,
    meta.LOCK_HOST_KEY,
    meta.LOCK_STARTED_AT_KEY,
)


@dataclass(frozen=True, slots=True)
class LockHolder:
    """Who is recorded as indexing this knowledge base, and since when.

    `pid` is `None` when the recorded value is not a process id at all — a row edited by hand.
    That keeps the distinction a caller needs: a lock *is* recorded, and nothing here can show its
    holder is gone, so it is never reclaimed automatically.
    """

    pid: int | None
    host: str
    started_at: str

    def describe(self) -> str:
        """The holder as a person needs to read it, including when its pid is unreadable."""
        who = "an unreadable pid" if self.pid is None else f"pid {self.pid}"
        return f"{who} on {self.host or 'an unnamed host'}, since {self.started_at or 'unknown'}"


def is_held(raw: Mapping[str, str]) -> bool:
    """Whether a lock is recorded at all, from a knowledge base's `meta` rows.

    Presence of the recorded pid, not liveness of the process it names. Whether a present lock is
    still live is a question only its own host can answer, and the conservative half is the one
    every reader of this wants: acting as though a lock were absent while a writer holds it is the
    unrecoverable direction.
    """
    return meta.LOCK_PID_KEY in raw


def read(raw: Mapping[str, str]) -> LockHolder | None:
    """The recorded holder, or `None` if no lock is held.

    A partially written lock — the pid present, a companion row missing — still counts as held,
    for the same reason `is_held` reads only the pid: the rows are written in one transaction, so
    the case can only arise from an edit by hand, and treating it as *no lock* would let a scan
    start beside whatever wrote it.
    """
    if not is_held(raw):
        return None
    try:
        pid: int | None = int(raw[meta.LOCK_PID_KEY])
    except ValueError:
        pid = None
    return LockHolder(
        pid=pid,
        host=raw.get(meta.LOCK_HOST_KEY, ""),
        started_at=raw.get(meta.LOCK_STARTED_AT_KEY, ""),
    )


def this_host() -> str:
    """The name this machine records in a lock it takes.

    Read through `os.uname` rather than a network lookup: the value only ever has to distinguish
    *this* machine from another one that wrote the same database over a shared filesystem, and a
    resolver that is slow or absent must not be able to stall taking a lock.
    """
    return os.uname().nodename


def _process_is_alive(pid: int) -> bool:
    """Whether a process with this id exists.

    A permission error means it exists and belongs to somebody else, which is alive for this
    question. A pid at or below zero names no process and would address a process *group* if
    passed on, so it is refused rather than probed.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_reclaimable(holder: LockHolder, *, host: str) -> bool:
    """Whether this process may take a lock somebody else recorded.

    Only on the same host, and only when the recorded process is provably gone. A foreign host's
    lock is never reclaimable here whatever its age — pid liveness is meaningless across machines
    — and neither is a lock whose pid cannot be read, because *reclaim it* is the reading that
    lets two indexers write one database.
    """
    return holder.host == host and holder.pid is not None and not _process_is_alive(holder.pid)


async def acquire(db: aiosqlite.Connection, *, pid: int, host: str, started_at: str) -> None:
    """Take the lock, or refuse because somebody else holds it.

    Runs inside the caller's transaction, and must: reading the existing rows and writing the new
    ones in two transactions leaves a window in which two processes both read *no holder*.

    Raises:
        IndexerBusyError: a live local indexer, or any indexer on another host, holds it. The same
            refusal anything else that must not run beside a build raises, so a caller branching
            on it does not have to know which of the two noticed.
    """
    holder = read(await database.read_meta(db))
    if holder is not None and not is_reclaimable(holder, host=host):
        raise IndexerBusyError(
            f"an indexer is already running against this knowledge base ({holder.describe()})"
        )
    await database.write_meta(
        db,
        {
            meta.LOCK_PID_KEY: str(pid),
            meta.LOCK_HOST_KEY: host,
            meta.LOCK_STARTED_AT_KEY: started_at,
        },
    )


async def release(db: aiosqlite.Connection) -> None:
    """Give the lock up, whether or not this process still holds it.

    Deliberately unconditional. It runs from the path that unwinds a failed scan as well as a
    successful one, and a release that first checked ownership would leave the lock held for every
    failure that happened to lose track of it — which is the state that needs an operator, in
    exchange for a check that protects nothing a same-host reclaim would not fix.
    """
    await database.clear_meta(db, LOCK_KEYS)
