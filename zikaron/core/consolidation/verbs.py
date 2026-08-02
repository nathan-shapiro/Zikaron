"""`merge`, `promote` and `discard`: the three consolidator write verbs, each one transaction.

`architecture.md` §"Consolidator tool surface" and §"Row-level completion" are normative. Each verb
runs the ladder in `authorization`, then mutates, then dispositions the members it touched and
closes whatever that closure reaches. Nothing here re-implements a row rule: `records.memory`'s
`apply_*` mutators own the column writes, version bumps and receipts, and `indexing.writes` owns
the index.

**Completion is tracked per journal row, never per group.** A group with a mixed disposition —
merge A, promote B, discard C — takes three calls, and the group closes only when its last member is
dispositioned. That is what makes the never-lose guard structural rather than a protocol: a model
that returns nothing, stops halfway, crashes or lets its lease expire loses **no** rows, because the
undispositioned ones are still `tier='journal' AND active=1` and the next run plans them again. No
cooperation from the model is required for the guard to hold.

**Every response carries `remaining_uuids`**, in the success shape *and* in the conflict shape, so a
caller learns the same remaining state whether its call landed or raced. It is recomputed from the
member table at response time rather than tracked, which is what makes it shrink within one call.

**The chunking preflight runs before the transaction, and `promote` pays for one it may discard.**
The preflight is where `gist_max_tokens` is enforced — rung 1, before the store is touched — and
where the embedding happens, and holding SQLite's write lock across a model load is what the whole
outside-the-transaction rule exists to avoid. `promote`'s form, though, can only be decided from
authorized state *inside* the transaction, since it turns on whether the sole absorbed row's stored
prose is byte-identical to the arguments. So an in-place promotion embeds a vector it then does not
use: a few milliseconds on a manually-invoked, rare, unwaited call, in exchange for the form being
decided once, from state that has been version-checked. Deciding it from a pre-transaction read
would have been sound — a matching version implies unchanged prose — but it buys nothing and adds a
disagreement between two reads that would have to be handled somewhere.
"""

from collections.abc import Sequence

import aiosqlite

from zikaron.core.consolidation import authorization, groups, runs
from zikaron.core.consolidation.authorization import Authorized
from zikaron.core.consolidation.context import ConsolidationCall
from zikaron.core.consolidation.groups import Disposition, GroupStatus
from zikaron.core.consolidation.payload import (
    Discarded,
    DiscardOutcome,
    GroupConflict,
    Merged,
    MergeOutcome,
    MergeTarget,
    NamedRow,
    NamedRows,
    Promoted,
    PromoteOutcome,
)
from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.events import (
    AuthoredSize,
    DiscardDetail,
    GroupRef,
    MergeDetail,
    MergeRole,
    PromoteDetail,
    PromoteForm,
    PromoteRole,
)
from zikaron.core.indexing import vectors, writes
from zikaron.core.indexing.chunking import ChunkPlan
from zikaron.core.indexing.writes import PreparedIndex
from zikaron.core.records import memory as records
from zikaron.core.records.memory import Memory, Rewrite, Tier, log_event
from zikaron.core.store import transactions


def _authored(plan: ChunkPlan) -> AuthoredSize:
    """The four size fields, from the preflight that actually cut the chunks being written."""
    return AuthoredSize(
        token_count=plan.content_tokens,
        gist_tokens=plan.gist_tokens,
        n_chunks=plan.n_chunks,
        truncated=plan.truncated,
    )


async def _stored_size(
    db: aiosqlite.Connection, *, row: Memory, call: ConsolidationCall
) -> AuthoredSize:
    """The four size fields read off what the store already holds, for a call that authored nothing
    new.

    `promote`'s in-place form only: it changes no prose, so it rebuilds no index, and a preflight
    run under a `chunk_max_tokens` that has moved since the row was written would report an
    `n_chunks` the store does not contain. `token_count` is the row's own column, `n_chunks` and
    `truncated` come from its chunk rows, and `gist_tokens` is counted over the stored gist with
    the deployed tokenizer — which is a fresh measurement of stored prose rather than a number
    carried from elsewhere, because no column records it.
    """
    stored = await vectors.stored_chunks(db, memory_uuid=row.uuid)
    return AuthoredSize(
        token_count=row.token_count,
        gist_tokens=call.index.encoder.count_tokens(row.gist),
        n_chunks=stored.n_chunks,
        truncated=stored.truncated,
    )


async def _disposition_and_close(
    db: aiosqlite.Connection,
    *,
    authorized: Authorized,
    disposition: Disposition,
    call: ConsolidationCall,
    at: str,
) -> tuple[tuple[str, ...], bool, int]:
    """Disposition the absorbed members, close what that closes, and refresh the lease.

    The whole tail every verb shares, and it is shared rather than repeated because invariant 16's
    closure property is stated over *committed* state: a group whose members are all dispositioned
    is never left open, so the disposition and the group's transition — and, if that was the run's
    last open group, the run's — must land in one transaction. Three copies of that sequence would
    be three chances for one verb to leave a group uncloseable.

    The lease is refreshed because this call made progress. A `{conflict: true}` response never
    reaches here, which is deliberate: it mutates nothing, so extending the lease would let a
    consolidator that is achieving nothing hold the store indefinitely.

    Returns:
        `(remaining_uuids, group_complete, dispositioned)` — the remaining set in group order,
        whether this call closed the group, and how many member rows actually moved, which is what
        `discard` reports as `retired` rather than the length of its own argument.
    """
    moved = await groups.disposition_members(
        db,
        group_id=authorized.group.group_id,
        memory_uuids=authorized.absorbed_uuids,
        disposition=disposition,
        at=at,
    )
    remaining = await groups.open_member_uuids(db, authorized.group.group_id)
    complete = not remaining
    if complete:
        await groups.set_status(
            db,
            group_id=authorized.group.group_id,
            status=GroupStatus.COMPLETE,
            expected=authorized.group.status,
        )
        await runs.close_if_finished(db, run_id=authorized.run.run_id, ctx=call.ctx)
    await runs.refresh_lease(
        db,
        run_id=authorized.run.run_id,
        at=at,
        lease_seconds=call.settings.run_lease_seconds,
    )
    return remaining, complete, moved


async def _retire_absorbed(
    db: aiosqlite.Connection, *, row: Memory, superseded_by: str | None, call: ConsolidationCall
) -> Memory:
    """Retire one absorbed member, pointing it at the survivor where there is one.

    `superseded_by` set writes D25's supersession edge, validated in this same transaction; `None`
    is `discard`'s outright retirement, which names no replacement because there is none — the row
    was judged not worth keeping, and D16 leaves its prose intact so that judgment is recoverable.
    """
    return await records.apply_retirement(
        db, current=row, superseded_by=superseded_by, ctx=call.ctx
    )


def _failure_map(verb: str) -> transactions.FailureMap:
    """Contention is `store_busy`, everything else `index_failed` — a consolidator verb is a write.

    Named per verb so `store_busy`'s payload says which call may be retried, and decided here rather
    than shared because `architecture.md` §Errors makes it a property of the *kind* of call: a write
    performs index maintenance and so has an `index_failed` to report, while a read does not.
    """
    return lambda error: (
        ZikaronError(ErrorCode.STORE_BUSY, verb=verb)
        if transactions.is_contention(error)
        else ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.INDEX_WRITE)
    )


async def merge(
    db: aiosqlite.Connection,
    *,
    group_id: str,
    target: MergeTarget,
    absorb: Sequence[NamedRow],
    call: ConsolidationCall,
) -> MergeOutcome:
    """Rewrite an existing long-term record to absorb part or all of a group.

    The target must be in this group's persisted authorization set — its anchor or one of its
    candidates — and must still be an active long-term record at mutation time. Absorbed rows are
    retired with `superseded_by = target.uuid`, which demotes rather than hides them (D25), so
    historical-intent queries still reach them and their original `session_id` still records who
    learned the lesson.

    Emits one `merge` event per row it mutated: the target, carrying the preflight's size fields,
    then one per absorbed row with those four fields null, because only the target authored prose.

    Returns:
        `Merged` with the target's new version, or `GroupConflict` when a named row's version has
        moved — carrying the current record for every conflicting uuid and the remaining member set.

    Raises:
        ZikaronError: `BOUNDS` if the gist is empty or over `gist_max_tokens`, or a uuid repeats in
            `absorb`; then the ladder's own rejections — `GROUP_UNKNOWN`, `GROUP_EXPIRED`,
            `GROUP_COMPLETE`, `GROUP_DEFERRED`, `NOT_IN_GROUP`, `BAD_MERGE_TARGET`,
            `NO_READ_RECEIPT`; or `INDEX_FAILED` / `STORE_BUSY`, either of which leaves every row
            as it was.
    """
    named = NamedRows(absorb=tuple(absorb), target=target.row)
    prepared = await writes.prepare(target.rewrite, index=call.index)

    async def work(connection: aiosqlite.Connection) -> MergeOutcome:
        authorized = await authorization.authorize(
            connection, group_id=group_id, named=named, call=call, verb="merge"
        )
        if isinstance(authorized, GroupConflict):
            return authorized
        return await _apply_merge(connection, authorized=authorized, prepared=prepared, call=call)

    return await transactions.in_one_transaction(db, work, failure=_failure_map("merge"))


async def _apply_merge(
    db: aiosqlite.Connection,
    *,
    authorized: Authorized,
    prepared: PreparedIndex,
    call: ConsolidationCall,
) -> Merged:
    """Rung 7 for `merge`: rewrite the target, retire the absorbed rows, log, disposition, close."""
    at = runs.now()
    before = authorized.target
    if before is None:
        # `Authorized.target` is optional because `promote` and `discard` name none; `merge` always
        # does, and rung 2 refused the call if it was not authorized. A real `raise` rather than a
        # bare `assert`, for the reason `write.tools` gives at the same kind of site: an assertion
        # can
        # be compiled away, and this exists to catch the ladder changing what it returns.
        raise ValueError("merge reached rung 7 with no authorized target")
    after = await records.apply_rewrite(db, current=before, rewrite=prepared.rewrite, ctx=call.ctx)
    await writes.reindex_rewrite(
        db, before=before, after=after, prepared=prepared, index=call.index
    )
    reference = GroupRef(group_id=authorized.group.group_id, run_id=authorized.run.run_id)
    n_absorbed = len(authorized.absorbed)
    await log_event(
        db,
        ctx=call.ctx,
        detail=MergeDetail(
            group=reference,
            role=MergeRole.TARGET,
            from_version=before.version,
            to_version=after.version,
            n_absorbed=n_absorbed,
            size=_authored(prepared.plan),
        ),
        memory_uuid=after.uuid,
    )
    for row in authorized.absorbed:
        retired = await _retire_absorbed(db, row=row, superseded_by=after.uuid, call=call)
        await log_event(
            db,
            ctx=call.ctx,
            detail=MergeDetail(
                group=reference,
                role=MergeRole.ABSORBED,
                from_version=row.version,
                to_version=retired.version,
                n_absorbed=n_absorbed,
                size=AuthoredSize.none_authored(),
            ),
            memory_uuid=row.uuid,
        )
    remaining, complete, _ = await _disposition_and_close(
        db, authorized=authorized, disposition=Disposition.MERGED, call=call, at=at
    )
    return Merged(
        uuid=after.uuid,
        version=after.version,
        remaining_uuids=remaining,
        group_complete=complete,
    )


async def promote(
    db: aiosqlite.Connection,
    *,
    group_id: str,
    rewrite: Rewrite,
    absorb: Sequence[NamedRow],
    call: ConsolidationCall,
) -> PromoteOutcome:
    """Create a long-term record from part or all of a group, or lift one member where it stands.

    **Which form runs is determined by the payload, not guessed**: exactly one `absorb` row whose
    stored gist and content are byte-identical to the arguments flips that row's tier in place, and
    anything else inserts a new long-term record and retires every absorbed row with `superseded_by`
    set to the new uuid. The version bumps in both forms — invariant 8 makes a tier flip a real
    mutation, because a primary agent may be amending the row concurrently.

    Event cardinality differs between the forms and is fixed rather than left to this
    implementation. `new_row` emits one `created` event plus one `absorbed` event per absorbed row.
    `in_place` emits **exactly one**, `flipped`, `n_absorbed: 1` — because the flipped row *is* the
    absorbed member and a singular role cannot say both. One mutated row, one event.

    Returns:
        `Promoted` with the long-term record's uuid and version, or `GroupConflict`.

    Raises:
        ZikaronError: as `merge`, minus `BAD_MERGE_TARGET` — this verb names no target.
    """
    named = NamedRows(absorb=tuple(absorb))
    prepared = await writes.prepare(rewrite, index=call.index)

    async def work(connection: aiosqlite.Connection) -> PromoteOutcome:
        authorized = await authorization.authorize(
            connection, group_id=group_id, named=named, call=call, verb="promote"
        )
        if isinstance(authorized, GroupConflict):
            return authorized
        if _is_in_place(authorized, rewrite=rewrite):
            return await _apply_in_place_promote(connection, authorized=authorized, call=call)
        return await _apply_new_row_promote(
            connection, authorized=authorized, prepared=prepared, call=call
        )

    return await transactions.in_one_transaction(db, work, failure=_failure_map("promote"))


def _is_in_place(authorized: Authorized, *, rewrite: Rewrite) -> bool:
    """Whether this promotion lifts its sole member in place rather than authoring a new record.

    Byte-identical prose is the whole test, and it is evaluated against the row the ladder loaded
    and version-checked — so "identical to what is stored" means identical to the version the caller
    presented, not to whatever the row held when the payload was assembled.
    """
    if len(authorized.absorbed) != 1:
        return False
    only = authorized.absorbed[0]
    return only.gist == rewrite.gist and only.content == rewrite.content


async def _apply_in_place_promote(
    db: aiosqlite.Connection, *, authorized: Authorized, call: ConsolidationCall
) -> Promoted:
    """Rung 7 for `promote`'s in-place form: flip the tier, log one event, close.

    No index work at all: the prose is byte-identical to what is stored, `memory_fts` indexes `gist`
    and `content` only, and `tier` appears in neither index — so there is nothing to rebuild, and
    rebuilding it anyway would rewrite chunks under a possibly-changed `chunk_max_tokens` for no
    gain.
    """
    at = runs.now()
    before = authorized.absorbed[0]
    after = await records.apply_tier(db, current=before, tier=Tier.LONG_TERM, ctx=call.ctx)
    await log_event(
        db,
        ctx=call.ctx,
        detail=PromoteDetail(
            group=GroupRef(group_id=authorized.group.group_id, run_id=authorized.run.run_id),
            role=PromoteRole.FLIPPED,
            form=PromoteForm.IN_PLACE,
            from_version=before.version,
            to_version=after.version,
            n_absorbed=1,
            size=await _stored_size(db, row=after, call=call),
        ),
        memory_uuid=after.uuid,
    )
    remaining, complete, _ = await _disposition_and_close(
        db, authorized=authorized, disposition=Disposition.PROMOTED, call=call, at=at
    )
    return Promoted(
        uuid=after.uuid,
        version=after.version,
        remaining_uuids=remaining,
        group_complete=complete,
    )


async def _apply_new_row_promote(
    db: aiosqlite.Connection,
    *,
    authorized: Authorized,
    prepared: PreparedIndex,
    call: ConsolidationCall,
) -> Promoted:
    """Rung 7 for `promote`'s new-row form: insert the record long-term, retire what it absorbed."""
    at = runs.now()
    created = await writes.insert_row_and_indexes(
        db, prepared=prepared, call=call.indexed, tier=Tier.LONG_TERM
    )
    reference = GroupRef(group_id=authorized.group.group_id, run_id=authorized.run.run_id)
    n_absorbed = len(authorized.absorbed)
    await log_event(
        db,
        ctx=call.ctx,
        detail=PromoteDetail(
            group=reference,
            role=PromoteRole.CREATED,
            form=PromoteForm.NEW_ROW,
            from_version=created.version,
            to_version=created.version,
            n_absorbed=n_absorbed,
            size=_authored(prepared.plan),
        ),
        memory_uuid=created.uuid,
    )
    for row in authorized.absorbed:
        retired = await _retire_absorbed(db, row=row, superseded_by=created.uuid, call=call)
        await log_event(
            db,
            ctx=call.ctx,
            detail=PromoteDetail(
                group=reference,
                role=PromoteRole.ABSORBED,
                form=PromoteForm.NEW_ROW,
                from_version=row.version,
                to_version=retired.version,
                n_absorbed=n_absorbed,
                size=AuthoredSize.none_authored(),
            ),
            memory_uuid=row.uuid,
        )
    remaining, complete, _ = await _disposition_and_close(
        db, authorized=authorized, disposition=Disposition.PROMOTED, call=call, at=at
    )
    return Promoted(
        uuid=created.uuid,
        version=created.version,
        remaining_uuids=remaining,
        group_complete=complete,
    )


async def discard(
    db: aiosqlite.Connection,
    *,
    group_id: str,
    absorb: Sequence[NamedRow],
    reason: str,
    call: ConsolidationCall,
) -> DiscardOutcome:
    """Retire journal rows judged not worth keeping: `active=0`, `superseded_by NULL` (D16).

    `reason` is recorded in the **event log and nowhere else**, which is deliberate rather than an
    omission: D16 leaves the row's own prose untouched, so "we decided this was noise" stays
    recoverable if that judgment was wrong, without editing the row to say so.

    Runs no chunking preflight and touches no index: a discard writes `active`, `version` and
    `updated_at`, none of which is an indexed column, and D16 leaves the chunks exactly where they
    are so a discarded row stays recoverable.

    Returns:
        `Discarded` with how many member rows actually moved, or `GroupConflict`.

    Raises:
        ZikaronError: the ladder's own rejections, or `STORE_BUSY` / `INDEX_FAILED`. No `BOUNDS`
        from a
            gist, since this verb authors no prose — only from a repeated `absorb` uuid.
    """
    named = NamedRows(absorb=tuple(absorb))

    async def work(connection: aiosqlite.Connection) -> DiscardOutcome:
        authorized = await authorization.authorize(
            connection, group_id=group_id, named=named, call=call, verb="discard"
        )
        if isinstance(authorized, GroupConflict):
            return authorized
        return await _apply_discard(connection, authorized=authorized, reason=reason, call=call)

    return await transactions.in_one_transaction(db, work, failure=_failure_map("discard"))


async def _apply_discard(
    db: aiosqlite.Connection, *, authorized: Authorized, reason: str, call: ConsolidationCall
) -> Discarded:
    """Rung 7 for `discard`: retire each named member outright and record why."""
    at = runs.now()
    reference = GroupRef(group_id=authorized.group.group_id, run_id=authorized.run.run_id)
    n_absorbed = len(authorized.absorbed)
    for row in authorized.absorbed:
        retired = await _retire_absorbed(db, row=row, superseded_by=None, call=call)
        await log_event(
            db,
            ctx=call.ctx,
            detail=DiscardDetail(
                group=reference,
                reason=reason,
                from_version=row.version,
                to_version=retired.version,
                n_absorbed=n_absorbed,
            ),
            memory_uuid=row.uuid,
        )
    remaining, complete, moved = await _disposition_and_close(
        db, authorized=authorized, disposition=Disposition.DISCARDED, call=call, at=at
    )
    return Discarded(retired=moved, remaining_uuids=remaining, group_complete=complete)
