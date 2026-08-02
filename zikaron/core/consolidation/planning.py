"""`plan_groups`: write one run's whole partition, and close whatever run preceded it.

`architecture.md` §"Consolidation lifecycle" §Planning is normative. Four things happen here, in
this order, and the order is what enforces invariant 15:

1. **Close any pre-existing `active` run**, with the status two tests imply — `expired` if the lease
   has passed, else `abandoned` for its own owner and `taken_over` for anybody else. This function
   is the only producer of all three, which is what makes them one decision rather than several
   rules whose conditions could all be true of one run. **An explicit call takes the run over**: no
   evidence inside the store separates a dead consolidator from a slow one, so a human invoking the
   skill again is the evidence, and `next_group` — the path a *model* uses — still refuses a
   stranger.
2. **Create the new run**, owned by `(session_id, pid)` with a fresh lease. It is only after step 1
   that this can be done without there being two effectively-active runs for an instant.
3. **Plan and persist the groups.** Membership is frozen here. Planning is a pure function of the
   store plus the effective config, so a run is reproducible from its inputs.
4. **Emit `planned`**, and — when the journal was empty — close the run `complete` immediately,
since
   a run with no groups has nothing left to serve.

**Replanning is never incremental.** A new run always plans from scratch, which is safe precisely
because undispositioned members stay `tier='journal' AND active=1`: nothing was lost by the run
being abandoned, so nothing needs carrying forward. That is D29's never-lose guard doing its work —
the store's own state is the record of what happened, and no cooperation from the model is required.
"""

import aiosqlite

from zikaron.core.consolidation import grouping, groups, runs
from zikaron.core.consolidation.context import ConsolidationCall
from zikaron.core.consolidation.groups import Group, GroupStatus
from zikaron.core.consolidation.runs import Run, RunStatus
from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.events import RunPhase
from zikaron.core.store import transactions


def _closing_status(previous: Run, *, call: ConsolidationCall, at: str) -> RunStatus:
    """Which terminal status a pre-existing `active` run gets: two tests, three answers.

    A lapsed lease is `expired`, whoever asks. An unexpired one is `abandoned` when the caller
    **is** its owner — a worker deliberately restarting its own run — and `taken_over` when it is
    not. The third value exists so those last two stay distinguishable: they have different costs,
    and in the likeliest case nothing else on the row separates them, since a user retrying the
    skill in one kiro session presents the same `session_id` and only a different pid.
    """
    if previous.has_lapsed(at=at):
        return RunStatus.EXPIRED
    return RunStatus.ABANDONED if previous.owner == call.owner else RunStatus.TAKEN_OVER


async def _close_previous(
    db: aiosqlite.Connection, *, call: ConsolidationCall, at: str
) -> Run | None:
    """Close the store's one `active` run, if it has one, with the status the two tests above imply.

    Returns the run that was closed, so a caller can tell "there was nothing to close" from "there
    was, and it is closed now" — which is the difference between a first run and a takeover.
    """
    previous = await runs.stored_active(db)
    if previous is None:
        return None
    status = _closing_status(previous, call=call, at=at)
    await runs.close(db, run_id=previous.run_id, status=status, ctx=call.ctx)
    return previous


async def plan_within_transaction(
    db: aiosqlite.Connection, *, call: ConsolidationCall, at: str
) -> Run:
    """`plan_groups`' work, assuming the caller already holds an open transaction.

    Neither commits nor rolls back, so `next_group` can call this inside its own serve transaction —
    which it must, because an implicit replan and the serve that follows it have to be one atomic
    step or a second caller could serve from a run this one is still writing.

    Args:
        at: the single instant this transaction is about — the closing lease comparison, the new
            run's `started_at`, and the lease derived from it. Passed in rather than read here so a
            serve that replans implicitly stamps the replan and the delivery identically.

    Returns:
        The new run, `active` unless the journal was empty, in which case it is already `complete`
        in the store and this value's own `status` is the pre-close one. Callers that need the
        current status re-read it; the serve loop instead asks the group table what is servable,
        which is the same question asked of the authoritative side.
    """
    await _close_previous(db, call=call, at=at)
    run = await runs.create(
        db,
        owner=call.owner,
        started_at=at,
        lease_seconds=call.settings.run_lease_seconds,
    )
    planned = await grouping.plan(db, call=call)
    for group in planned:
        group_id = groups.new_group_id()
        await groups.insert(
            db,
            Group(
                group_id=group_id,
                run_id=run.run_id,
                anchor_uuid=group.anchor_uuid,
                order_key=group.order_key,
                shard=group.shard,
                status=GroupStatus.PENDING,
                serve_count=0,
                served_at=None,
            ),
        )
        for member in group.members:
            await groups.insert_member(
                db,
                group_id=group_id,
                memory_uuid=member.uuid,
                version_seen=member.version,
            )
    await runs.log_phase(
        db,
        run_id=run.run_id,
        phase=RunPhase.PLANNED,
        run_counts=await groups.run_counts(db, run.run_id),
        ctx=call.ctx,
    )
    if not planned:
        # A run with zero groups has nothing to serve, so it is complete the moment it is planned.
        # Invariant 17's `active → complete` cause is "whichever transaction first observes that no
        # group of the run is pending or served", and this transaction is the first to observe it.
        await runs.close(db, run_id=run.run_id, status=RunStatus.COMPLETE, ctx=call.ctx)
    return run


async def plan_groups(db: aiosqlite.Connection, *, call: ConsolidationCall) -> Run:
    """Plan a fresh consolidation run over the whole journal, in one transaction — taking over if
    held.

    The service RPC, and it is the **one** entry point that may displace a live worker. Whoever
    calls it wins: an unexpired run of another owner is closed `taken_over`, its own unexpired run
    is closed `abandoned`, and a lapsed one is closed `expired`. `next_group` answers `{busy: true}`
    to a stranger instead, and that asymmetry is what D32 buys: a model confined to a configured
    tool surface cannot *request* a takeover, because this RPC is in neither tool set. It is not a
    claim that nothing calls it — the consolidator's own MCP client does, immediately before the
    first `next_group` it forwards and at most once *successfully* per process — nor a capability
    boundary, since the socket is unauthenticated to any same-uid process.

    **Why takeover rather than refusal, since the refusal is the safer-looking choice.** Nothing
    reachable from inside the store distinguishes a dead consolidator from one that is merely slow.
    A lease is a timer, so it cannot. A pid-liveness check is not useless — the holder's `pid` names
    an MCP client process that normally exits with its own agent — but it cannot carry the decision:
    it answers *is this process alive*, never *will this worker make progress*, pid reuse can return
    a false alive and prolong the very lockout being diagnosed, and the service and the client are
    not guaranteed a shared pid namespace. The evidence that settles it is outside the store
    altogether: a human invoking the consolidation skill a second time. Refusing would pin the store
    for up to `run_lease` on a worker that has stopped.

    **Nothing the displaced worker does can land, and that is the ladder's property rather than a
    hope.** Rung 2 requires a group's run to be owned by the caller *and* effectively active, so the
    displaced worker's next `merge`/`promote`/`discard` is refused `group_expired` before touching a
    row, and its next `next_group` finds the new run foreign and stops. It loses its reasoning in
    progress — what the human chose to discard — and no journal row, since undispositioned members
    stay `tier='journal' AND active=1` and are replanned.

    `next_group` does not come through here: it calls `plan_within_transaction` inside its own serve
    transaction, having already established that no effectively-active run exists.

    Returns:
        The new run, `active` unless the journal was empty.

    Raises:
        ZikaronError: `STORE_BUSY` if the store was locked, which the caller may retry, or
            `INDEX_FAILED` at the `index_write` stage for any other driver failure — the plan is a
            write, so `architecture.md` §Errors gives it a write's two codes and nothing is left
            behind in either case.
    """

    async def work(connection: aiosqlite.Connection) -> Run:
        return await plan_within_transaction(connection, call=call, at=runs.now())

    return await transactions.in_one_transaction(db, work, failure=_failure_map("plan_groups"))


def _failure_map(verb: str) -> transactions.FailureMap:
    """Name contention `store_busy` and everything else `index_failed`, per `architecture.md`.

    This layer's own decision for its own transactions, deliberately not a shared utility: what
    varies between callers is exactly how a driver failure is named, and a consolidation transaction
    writes rows, chunks and vectors, so it is a write by that section's own test.
    """
    return lambda error: (
        ZikaronError(ErrorCode.STORE_BUSY, verb=verb)
        if transactions.is_contention(error)
        else ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.INDEX_WRITE)
    )
