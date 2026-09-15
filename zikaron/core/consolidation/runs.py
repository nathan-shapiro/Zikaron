"""The `consolidation_run` aggregate: one effectively-active run per store, and its lease.

`schema.md` invariants 15 and 17 and `architecture.md` §"Consolidation lifecycle" are normative. Two
rules run through everything here:

**"Effectively active" is the only run test anywhere in the system** — `status='active' AND
expires_at ≥ now`. A stored `'active'` row past its lease constrains nobody, *including the session
that owns it*, and that second half is not a nicety: `next_group` replans only when the caller has
no active run, so an owner whose lease lapsed would otherwise find its own run, be served a group
from it, and be rejected `group_expired` forever — with no way out, since `plan_groups` is a service
RPC and not one of the consolidator's four tools.

**Expiry is derived on the read side and stored only at plan time.** Every reader computes it from
`expires_at`; only `plan_groups` writes `status='expired'`. The alternative — having whichever call
noticed a lapsed lease perform the transition — would make a *rejected* call write
`consolidation_run.status`, which `architecture.md` §"What a rejected call does and does not change"
forbids. The observable consequence is that a store can hold an `active` row whose lease has passed;
that is a lazily-collected tombstone, not drift, because every reader already computes the same
answer from the column beside it.

**The lease arithmetic lives here, with the lease.** It **parses** rather than comparing strings —
not because string order is untrustworthy (`core.clock` states and pins the opposite: lexicographic
order on these strings agrees with temporal order) but because a lease is a start plus a duration,
and adding seconds is not something ordering can do for you. Parsing then makes the comparison that
follows independent of the format as well, which is the cheaper half of a step taken for another
reason. Every timestamp this module stores is either a `core.clock.timestamp` reading or
`lease_expiry`'s parse-add-`isoformat()` of one, and that derivation preserves the format — so
there is still one.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import uuid4

import aiosqlite

from zikaron.core.clock import timestamp
from zikaron.core.consolidation import groups
from zikaron.core.consolidation.context import RunOwner
from zikaron.core.consolidation.groups import RunCounts
from zikaron.core.events import ConsolidateRunDetail, RunPhase
from zikaron.core.records.memory import CallParams, log_event


class RunStatus(StrEnum):
    """`consolidation_run.status`'s five values, exactly as `schema.md`'s `CHECK` states them.

    `ABANDONED` and `TAKEN_OVER` are one producer discriminated by one test — an explicit
    `plan_groups` closing an unexpired run, called by its owner or by somebody else. Both are
    recorded because a takeover is a supported operation with a real cost (the displaced worker's
    work in progress), and because in the likeliest case nothing else distinguishes them: a user
    retrying the skill in one kiro session presents the same `session_id` and only a different pid.
    """

    ACTIVE = "active"
    COMPLETE = "complete"
    EXPIRED = "expired"
    ABANDONED = "abandoned"
    TAKEN_OVER = "taken_over"


#: `RunStatus` → the `consolidate_run` phase recording the transition into it. `ACTIVE` is absent
#: because its phase is named differently — a run is `planned`, and then it *is* active — the one
#: place the two vocabularies do not coincide, and so the one place a mapping is needed at all.
_CLOSING_PHASE: Final[dict[RunStatus, RunPhase]] = {
    RunStatus.COMPLETE: RunPhase.COMPLETE,
    RunStatus.EXPIRED: RunPhase.EXPIRED,
    RunStatus.ABANDONED: RunPhase.ABANDONED,
    RunStatus.TAKEN_OVER: RunPhase.TAKEN_OVER,
}

_RUN_COLUMNS: Final = "run_id, session_id, pid, started_at, expires_at, status"


@dataclass(frozen=True, slots=True)
class Run:
    """One `consolidation_run` row, exactly as stored.

    `effective_status` is computed rather than stored, which is the whole content of the
    derived-expiry rule: two readers of one row must reach the same conclusion about a lapsed lease
    without either of them writing anything.
    """

    run_id: str
    owner: RunOwner
    started_at: str
    expires_at: str
    status: RunStatus

    def has_lapsed(self, *, at: str) -> bool:
        """Whether this run's lease has passed as of `at` — `expires_at < now`."""
        return _parse(self.expires_at) < _parse(at)

    def is_effectively_active(self, *, at: str) -> bool:
        """`status='active' AND expires_at ≥ now`: the only run test the design defines."""
        return self.status is RunStatus.ACTIVE and not self.has_lapsed(at=at)

    def effective_status(self, *, at: str) -> RunStatus:
        """The status a reader should act on: `EXPIRED` for a lapsed `ACTIVE` row, else the stored
        one. Reported in `group_expired`'s payload beside the stored value, so a caller can tell a
        lease that ran out from a run somebody replanned."""
        if self.status is RunStatus.ACTIVE and self.has_lapsed(at=at):
            return RunStatus.EXPIRED
        return self.status


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def lease_expiry(started_at: str, *, seconds: int) -> str:
    """`started_at` plus `seconds`, in the store's own timestamp format.

    Derived from the stored `started_at` rather than from a second clock read, so that
    `expires_at` minus `started_at` is exactly `run_lease` on every row — which is what lets a test
    assert the lease length rather than assert it approximately.
    """
    return (_parse(started_at) + timedelta(seconds=seconds)).isoformat()


def _to_run(row: Sequence[object]) -> Run:
    run_id, session_id, pid, started_at, expires_at, status = row
    return Run(
        run_id=str(run_id),
        owner=RunOwner(session_id=str(session_id), pid=int(str(pid))),
        started_at=str(started_at),
        expires_at=str(expires_at),
        status=RunStatus(str(status)),
    )


async def load(db: aiosqlite.Connection, run_id: str) -> Run | None:
    """One run by id, or `None` if the store holds no such row."""
    rows = await db.execute_fetchall(
        f"SELECT {_RUN_COLUMNS} FROM consolidation_run WHERE run_id = ?",  # noqa: S608 — a source-level column list; the id is bound.
        (run_id,),
    )
    found = list(rows)
    return None if not found else _to_run(tuple(found[0]))


async def stored_active(db: aiosqlite.Connection) -> Run | None:
    """The store's one `status='active'` run, whoever owns it and whether or not its lease holds.

    Returns the **stored** row, deliberately, because two callers want different things from it: a
    write verb needs to know whether the lease has lapsed in order to answer `group_expired`, and
    `next_group` needs to know in order to replan. Deciding here would force one of them to
    reconstruct what it was not told.

    Raises:
        ValueError: the store holds more than one `active` run, which invariant 15 forbids and only
            a bug in this module can produce, since `plan_groups` closes every one of them before
            creating another. Refused rather than resolved by picking the earliest: an
            implementation that quietly served one of two active runs would keep a broken store
            working while two consolidators mutated one journal, which is the precise failure the
            invariant exists to prevent.
    """
    rows = await db.execute_fetchall(
        f"SELECT {_RUN_COLUMNS} FROM consolidation_run WHERE status = 'active'"  # noqa: S608 — a source-level column list; no request value is interpolated.
    )
    found = list(rows)
    if len(found) > 1:
        ids = sorted(str(row[0]) for row in found)
        raise ValueError(f"invariant 15: {len(found)} active consolidation runs at once: {ids}")
    return None if not found else _to_run(tuple(found[0]))


async def log_phase(
    db: aiosqlite.Connection,
    *,
    run_id: str,
    phase: RunPhase,
    run_counts: RunCounts,
    ctx: CallParams,
) -> None:
    """Emit the `consolidate_run` event for one transition, in the caller's own transaction."""
    await log_event(
        db,
        ctx=ctx,
        detail=ConsolidateRunDetail(
            run_id=run_id,
            phase=phase,
            n_groups=run_counts.n_groups,
            n_members=run_counts.n_members,
            n_deferred=run_counts.n_deferred,
        ),
        memory_uuid=None,
    )


async def create(
    db: aiosqlite.Connection, *, owner: RunOwner, started_at: str, lease_seconds: int
) -> Run:
    """Insert a fresh `active` run owned by `owner`, with its lease set from `started_at`.

    Emits no event: the `planned` phase's counts describe the groups this run holds, which do not
    exist until the planner has written them, so the event belongs to the planner rather than here.
    Assumes the caller's open transaction, and assumes the caller has already closed any
    pre-existing `active` run — invariant 15 is enforced by that ordering, and this function
    deliberately does not do it silently, since which status the old run gets is the planner's
    decision to make and to record.
    """
    run = Run(
        run_id=str(uuid4()),
        owner=owner,
        started_at=started_at,
        expires_at=lease_expiry(started_at, seconds=lease_seconds),
        status=RunStatus.ACTIVE,
    )
    await db.execute(
        "INSERT INTO consolidation_run "
        "(run_id, session_id, pid, started_at, expires_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        (
            run.run_id,
            run.owner.session_id,
            run.owner.pid,
            run.started_at,
            run.expires_at,
            run.status.value,
        ),
    )
    return run


async def close(
    db: aiosqlite.Connection, *, run_id: str, status: RunStatus, ctx: CallParams
) -> bool:
    """Transition one `active` run to a terminal status, emitting its phase event if it moved.

    A **guarded** update — `WHERE status='active'` — so it is idempotent under a retry and so two
    paths that both notice a run is finished cannot emit two `complete` events for it. The event is
    emitted only when the update actually changed a row, which is what makes the guard load-bearing
    rather than decorative: `next_group`'s loop and the write verb that dispositions the last member
    can both reach the same conclusion in the same transaction.

    Counts are read **after** the transition, so a `complete` event's `n_deferred` reflects every
    group this run ended up deferring.

    Returns:
        Whether this call performed the transition.

    Raises:
        KeyError: `status` is `ACTIVE`, which is not a close. Raised rather than silently accepted
            because the guarded update would then be a no-op that looks like an already-closed run.
    """
    phase = _CLOSING_PHASE[status]
    cursor = await db.execute(
        "UPDATE consolidation_run SET status = ? WHERE run_id = ? AND status = 'active'",
        (status.value, run_id),
    )
    if cursor.rowcount == 0:
        return False
    await log_phase(
        db, run_id=run_id, phase=phase, run_counts=await groups.run_counts(db, run_id), ctx=ctx
    )
    return True


async def refresh_lease(
    db: aiosqlite.Connection, *, run_id: str, at: str, lease_seconds: int
) -> None:
    """Push one `active` run's `expires_at` out to `at` plus the lease.

    Guarded on `status='active'`, so a run closed under the caller cannot be revived by a
    refresh. Called only on a path that made progress — a serve that delivered a group, or a write
    verb that dispositioned a member — never on a rejection and never on a `{conflict: true}`
    response, which mutates nothing and so must not buy the lease more time.
    """
    await db.execute(
        "UPDATE consolidation_run SET expires_at = ? WHERE run_id = ? AND status = 'active'",
        (lease_expiry(at, seconds=lease_seconds), run_id),
    )


def now() -> str:
    """The current instant in the store's own timestamp format.

    Re-exported from the shared clock so every module in this package reads one clock, and reads it
    by a name that does not invite a second implementation. One call per transaction is the intent:
    a serve's `served_at`, its members' `disposed_at` and its lease refresh should all name the same
    instant, because they describe one event.
    """
    return timestamp()


async def close_if_finished(db: aiosqlite.Connection, *, run_id: str, ctx: CallParams) -> bool:
    """Close one run `complete` if no group of it is `pending` or `served` any more.

    Invariant 17 gives the run's `active → complete` transition exactly one condition and several
    transactions that can observe it: the write verb that dispositions the last member of the last
    open group, and the serve transaction, either when re-validation vacates a group empty or when
    the loop finds nothing servable left. So this is a question every one of them asks, and asking
    it through one function is what keeps them from disagreeing about whether `deferred` counts as
    open — it does not, because a deferred group is terminal for the run and its members simply
    return to the next plan.

    Returns:
        Whether this call performed the transition. `close`'s guarded update is what makes the
        answer trustworthy when two of those observers land in one transaction.
    """
    if await groups.has_open_groups(db, run_id):
        return False
    return await close(db, run_id=run_id, status=RunStatus.COMPLETE, ctx=ctx)
