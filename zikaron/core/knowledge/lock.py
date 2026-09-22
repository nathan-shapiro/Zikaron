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
operator clears the lock, which is why the holder is reported for a human to judge and why
`force_release` exists as the way out.

**One probe, and three questions that are not the same question.** *May this process take the
lock* admits only a holder that is provably gone. *Is a build running* admits everything except
that, foreign locks included, and is what decides whether a corpus reports itself mid-scan and
whether it may be removed. *May an operator clear this by hand* refuses only a holder that is
answering to that pid. Each is a different reading of `probe`, and each is wrong in the other's
place — which is why none of them is the mere presence of the rows: a killed build leaves those
behind deliberately, and the signal they carry outlives the process that wrote them.
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
    """Whether lock rows are recorded at all, from a knowledge base's `meta` rows.

    **Presence, and only presence** — which is a narrower question than any decision in this system
    turns on, and is deliberately not the one to reach for. *May a build start*, *may this corpus be
    removed*, *is a scan in flight* are all `running_holder`, because rows outlive the build that
    wrote them and a killed build leaves these behind on purpose. This is the test `read` is built
    on, and what a test asserts after a release.
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


def probe(holder: LockHolder, *, host: str) -> bool | None:
    """Whether a process on this host answers to the recorded pid, or `None` where even that cannot
    be established.

    **Not whether the indexer is running**, which no pid can establish: after a crash the number is
    free, and a reused one answers exactly as the process that recorded it did. `force_release` is
    where that limit is acted on, because it is the only reading whose consequence is a refusal an
    operator cannot get past.

    The one liveness question in this module, asked in one place so that no reading of it can drift
    from another. It is unanswerable in two cases, and both answer `None` rather than a guess: a
    lock recorded on another host, where a local process probe means nothing, and one whose pid is
    not a number at all, which only a hand edit produces.

    The asymmetry matters more than the answer. *Provably running* and *provably gone* are both
    strictly narrower than *not the other*, and a caller that treated `None` as either would either
    let a second indexer write beside a live one or refuse a knowledge base forever.
    """
    if holder.host != host or holder.pid is None:
        return None
    return _process_is_alive(holder.pid)


def is_reclaimable(holder: LockHolder, *, host: str) -> bool:
    """Whether this process may take a lock somebody else recorded.

    Only when the recorded process is provably gone. A foreign host's lock is never reclaimable
    here whatever its age, and neither is a lock whose pid cannot be read, because *reclaim it* is
    the reading that lets two indexers write one database.
    """
    return probe(holder, host=host) is False


def is_provably_live(holder: LockHolder, *, host: str) -> bool:
    """Whether something on this host answers to the recorded pid, for an operator clearing a lock.

    *Provably* is as strong as a pid allows and no stronger — it proves a process exists, not that
    it is the one that recorded the lock. `force_release` is what states that limit to whoever hits
    it, since this is the only reading that produces a refusal.

    Deliberately not the negation of `is_reclaimable`: a foreign lock is neither reclaimable nor
    provably live, and the two questions differ in who is asking. An indexer deciding whether to
    start may take a lock only whose holder is gone; an operator clearing one by hand is refused
    only where a process on this host answers to that pid, because everything else is a judgement
    they are better placed to make than this process is.
    """
    return probe(holder, host=host) is True


def running_holder(raw: Mapping[str, str], *, host: str) -> LockHolder | None:
    """The holder of a build this machine cannot show has stopped, or `None` if none is.

    **The single statement of *a build is running here*, and every consumer of that fact uses it**,
    because the alternatives are each wrong somewhere. Reading the rows' mere presence calls a
    killed build live for as long as nobody starts another one — which refuses a removal that is
    safe, and reports a corpus as mid-scan when nothing is scanning it. Reading liveness as
    *provably running* calls a foreign build dead, which is the reading that lets two indexers write
    one database.

    So `None` covers exactly two cases — no lock at all, and a lock whose process this host probed
    and found gone — and everything else, foreign locks included, counts as running.
    """
    holder = read(raw)
    if holder is None or is_reclaimable(holder, host=host):
        return None
    return holder


async def acquire(db: aiosqlite.Connection, *, pid: int, host: str, started_at: str) -> None:
    """Take the lock, or refuse because somebody else holds it.

    Runs inside the caller's transaction, and must: reading the existing rows and writing the new
    ones in *two* transactions would let a second acquisition slip between them and commit over the
    first. What one transaction buys is that at most one of two racing acquisitions commits — it
    does not stop both of them reading *no holder*, which a deferred `BEGIN` allows, and the loser's
    failure is then the driver's rather than the refusal below. `scan._begin` records why that is
    left as it is.

    Raises:
        IndexerBusyError: a live local indexer, or any indexer on another host, holds it. The same
            refusal anything else that must not run beside a build raises, so a caller branching
            on it does not have to know which of the two noticed.
    """
    holder = running_holder(await database.read_meta(db), host=host)
    if holder is not None:
        raise IndexerBusyError(
            f"an indexer is already running against this knowledge base ({holder.describe()})",
            holder=holder,
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


async def force_release(db: aiosqlite.Connection, *, host: str) -> LockHolder | None:
    """Clear a lock on an operator's judgement, refusing the one case the evidence contradicts.

    The exit from the state automatic reclamation is designed not to touch. A lock recorded on
    another machine is never reclaimed on its own, correctly — nothing here can show a foreign
    process is gone — but the rules that follow from it compose into a knowledge base nothing can
    manage: every build reports the corpus busy, removal refuses, and no clock runs out. One
    crashed indexer inside a container is enough to reach it.

    So the judgement moves to whoever knows what else is running, and this refuses only where their
    judgement is contradicted by evidence: a process on this host answers to that pid. Everything
    else is cleared, including a lock whose pid is unreadable, which no other path can resolve
    either.

    **The refusal rests on a pid, and a pid is not an identity.** All the probe establishes is that
    *some* process answers to that number on this host. After a crash the number is free, and on a
    machine that recycles them quickly an unrelated process can inherit it long before anybody
    reaches for this — at which point the corpus is refused a build, refused a removal, and refused
    the clearing that exists to break exactly that deadlock. So the refusal says what it actually
    knows, and names the way out that no check can block: the three `lock_*` rows are ordinary rows
    and an operator who is sure may delete them.

    Runs inside the caller's transaction, so the holder that was read is the holder that is
    cleared.

    Returns:
        The holder that was cleared, or `None` if no lock was recorded — which is the ordinary
        answer for an operator who ran this on a knowledge base that had already recovered.

    Raises:
        IndexerBusyError: some process on this host answers to the recorded pid.
    """
    holder = read(await database.read_meta(db))
    if holder is None:
        return None
    if is_provably_live(holder, host=host):
        raise IndexerBusyError(
            f"a process on this host still answers to the lock's pid ({holder.describe()}); "
            f"wait for it to finish, or stop it first. If that pid has been reused and belongs to "
            f"something else, delete the lock_pid, lock_host and lock_started_at rows from this "
            f"knowledge base's meta table by hand — nothing else can tell the two apart",
            holder=holder,
        )
    await database.clear_meta(db, LOCK_KEYS)
    return holder
