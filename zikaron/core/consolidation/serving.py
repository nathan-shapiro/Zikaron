"""`next_group`: one transaction that re-validates, closes, defers or delivers — and iterates.

`architecture.md` §"Consolidation lifecycle" §Serving is normative, and the ordering inside is part
of the contract because it is observable in which status a group lands in:

1. **Re-validate the members.** A member no longer `tier='journal' AND active=1` is marked `vacated`
   and not delivered; a planned anchor no longer `tier='long_term' AND active=1` is dropped. This
   runs first because everything after it depends on how many members are left.
2. **Zero undispositioned members left → close the group `complete`** and continue the loop. Nothing
   was delivered, so `serve_count` does not move and no `group_served` event is emitted.
3. **Otherwise, at `max_group_serves` already → mark the group `deferred`** and continue. Completion
   is tested *first* on purpose: a group whose last member vacated is finished, and deferring it
   instead would leave a group with nothing left to decide looking abandoned for the rest of the run
   and inflating `n_deferred`.
4. **Otherwise serve it.**

**Why the loop exists rather than returning the emptied group:** serve-time vacating can
disposition a group's *last* open member, which leaves zero undispositioned rows with no write verb
having run — so nothing transitioned the group, it was handed back empty, and it was re-served
until the budget ran out and it went `deferred`. That contradicted invariant 16's own completion
condition, spent the re-serve budget on a group with nothing in it, and delayed `{done: true}`
behind groups that were already finished.

**The served set is named once and is the only member-shaped thing in the payload:** the group's
members with `disposition IS NULL` at the end of step 1. `journal_entries` carries it in group
order; the candidate query concatenates *its* gists, so `n_gists_used` counts from it; one
`group_served` event with `role:'member'` is emitted per element; receipts are minted for its rows
only. Two implementations reading "the group members" differently would authorize different
`absorb` sets on the same store, which is why it is one set with one name.

**The embedding happens inside the transaction, and that is forced rather than chosen.** The
candidate query's text is the served set's gists, and the served set is not known until step 1 has
run and written its vacatings — so there is no text to embed before the transaction opens, the way
the read path and the write path both manage. Splitting the call in two was the alternative and it
is worse: the served set would be free to move between the decision and the delivery, which is
exactly what "runs in one transaction" exists to prevent. The cost is that SQLite's write lock is
held across one embedding call; consolidation is manually invoked, rare, and off every
latency-critical path, and the call runs through `asyncio.to_thread` so at least the event loop is
not also blocked.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import aiosqlite

from zikaron.core.consolidation import candidates, groups, planning, rowstate, runs
from zikaron.core.consolidation.context import ConsolidationCall
from zikaron.core.consolidation.groups import (
    AuthorizedRecord,
    CandidateRole,
    Disposition,
    Group,
    GroupStatus,
)
from zikaron.core.consolidation.payload import (
    Busy,
    GroupRecord,
    NextGroupOutcome,
    RankedRecord,
    RunDone,
    ServedGroup,
)
from zikaron.core.consolidation.runs import Run, RunStatus
from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.events import GroupRef, GroupServedDetail, ServeRole
from zikaron.core.records import memory as records
from zikaron.core.records import receipts
from zikaron.core.records.memory import log_event
from zikaron.core.records.receipts import ReceiptKey, ReceiptSource
from zikaron.core.store import transactions

#: The anchor's `rank` in the persisted authorization set. 0 rather than 1 so the anchor is
#: distinguishable from the first candidate by rank alone, which is what the schema's own column
#: comment states ("0 for the anchor; 1..N for candidates").
_ANCHOR_RANK: Final = 0


@dataclass(frozen=True, slots=True)
class _Revalidated:
    """Step 1's output: what this serve would deliver, and what the anchor turned out to be.

    `all_member_uuids` is the frozen plan-time universe, carried out of step 1 because step 4 needs
    it to exclude every member from the candidate results and re-reading the member table for it
    would be a second read of a set this pass has already loaded.
    """

    served: tuple[GroupRecord, ...]
    anchor: GroupRecord | None
    anchor_vacated: bool
    all_member_uuids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _Serve:
    """What one delivery is about: the run, the group, and the single instant it happened at.

    One value rather than three parameters threaded through five functions, and the instant belongs
    with them rather than beside them: a serve's `served_at`, its members' `disposed_at` and its
    lease refresh all describe one event, so reading the clock once and passing it as part of the
    subject is what keeps them from drifting apart by a microsecond nobody would notice.
    """

    run: Run
    group: Group
    at: str

    @property
    def reference(self) -> GroupRef:
        """This delivery's `(group_id, run_id)` pair, as every event of it carries them."""
        return GroupRef(group_id=self.group.group_id, run_id=self.run.run_id)

    @property
    def serve_count(self) -> int:
        """This delivery's own count, **including** itself.

        A `pending` group's first delivery is therefore 1, and at the default `max_group_serves =
        3` a group is delivered at most three times per run. The other reading — first delivery
        leaves the counter at 0 — would permit four from the same configuration.
        """
        return self.group.serve_count + 1


@dataclass(frozen=True, slots=True)
class _Delivered:
    """The rows one serve delivers, in payload order: the anchor, the members, the candidates.

    Exists so that "what was delivered" is computed once and then used by all four things that need
    the same answer — the receipts, the events, the authorization set and the payload. Three of
    those four had a different reason to build the list, which is three chances for one of them to
    include a row the others did not.
    """

    revalidated: _Revalidated
    candidates: tuple[RankedRecord, ...]

    @property
    def roles(self) -> tuple[tuple[ServeRole, GroupRecord], ...]:
        """Every delivered row with the role it played, in payload order."""
        anchor = self.revalidated.anchor
        return (
            *(() if anchor is None else ((ServeRole.ANCHOR, anchor),)),
            *((ServeRole.MEMBER, record) for record in self.revalidated.served),
            *((ServeRole.CANDIDATE, ranked.record) for ranked in self.candidates),
        )

    @property
    def records(self) -> tuple[GroupRecord, ...]:
        """Every delivered row, in payload order, without its role."""
        return tuple(record for _, record in self.roles)


async def _revalidate(db: aiosqlite.Connection, *, group: Group, at: str) -> _Revalidated:
    """Re-read every open member and the anchor, marking whatever has left as vacated or dropped.

    Writes the `vacated` dispositions, because that is where vacating is recorded: durably, in
    `consolidation_group_member`, and deliberately **not** in the event log — a vacated member
    emits no `group_served`, which is precisely what lets that event's `version_served` be non-null
    and mean what it says.

    The anchor is dropped from the payload but its `anchor_uuid` is left alone: that column is the
    plan's own record, `anchor_vacated` is a fact about *this* serve, and the authorization set is
    rewritten every serve anyway, so a dropped anchor simply stops being authorized.
    """
    vacated: list[str] = []
    served: list[GroupRecord] = []
    all_members = await groups.members(db, group.group_id)
    for member in all_members:
        if member.disposition is not None:
            continue
        row = await records.load(db, member.memory_uuid)
        if row is None or not await rowstate.is_deliverable_member(db, member.memory_uuid):
            vacated.append(member.memory_uuid)
            continue
        served.append(GroupRecord.of(row))
    await groups.disposition_members(
        db,
        group_id=group.group_id,
        memory_uuids=vacated,
        disposition=Disposition.VACATED,
        at=at,
    )
    return _Revalidated(
        served=tuple(served),
        anchor=await _anchor_record(db, anchor_uuid=group.anchor_uuid),
        anchor_vacated=await _anchor_vacated(db, anchor_uuid=group.anchor_uuid),
        all_member_uuids=frozenset(member.memory_uuid for member in all_members),
    )


async def _anchor_record(
    db: aiosqlite.Connection, *, anchor_uuid: str | None
) -> GroupRecord | None:
    """The planned anchor as the payload carries it, or `None` if there is none to deliver.

    `None` covers two situations the payload distinguishes by `anchor_vacated`: an orphan group,
    which never had an anchor, and a planned anchor that stopped being targetable before this serve.
    """
    if anchor_uuid is None or not await rowstate.is_targetable(db, anchor_uuid):
        return None
    row = await records.load(db, anchor_uuid)
    return None if row is None else GroupRecord.of(row)


async def _anchor_vacated(db: aiosqlite.Connection, *, anchor_uuid: str | None) -> bool:
    """Whether a group that *was* planned with an anchor is being served without it."""
    return anchor_uuid is not None and not await rowstate.is_targetable(db, anchor_uuid)


async def _mint_receipts(
    db: aiosqlite.Connection, *, delivered: _Delivered, call: ConsolidationCall, at: str
) -> None:
    """Mint one `group` receipt per delivered row, at the version whose prose was delivered.

    This is how the consolidator satisfies D26 without being given `fetch`: the payload delivers
    full content, so the payload is what mints the licence to write it. Minting is an idempotent
    upsert, which is required rather than cosmetic — a re-served group delivers the same rows at
    the same versions to the same session, and a plain insert would violate the primary key.
    """
    for record in delivered.records:
        await receipts.mint(
            db,
            key=ReceiptKey(
                session_id=call.ctx.session_id,
                client_kind=call.ctx.client_kind,
                memory_uuid=record.uuid,
                version=record.expected_version,
            ),
            at=at,
            source=ReceiptSource.GROUP,
        )


async def _log_delivery(
    db: aiosqlite.Connection, *, serve: _Serve, delivered: _Delivered, call: ConsolidationCall
) -> None:
    """One `group_served` event per row whose prose this serve actually delivered.

    In payload order — anchor, then members, then candidates — so the log reads in the same order
    the consolidator saw. A serve-time-vacated member emits none, and a vacated anchor emits none,
    because neither had any prose delivered; that is what keeps `version_served` non-null on every
    row of this kind.
    """
    for role, record in delivered.roles:
        await log_event(
            db,
            ctx=call.ctx,
            detail=GroupServedDetail(
                group=serve.reference,
                role=role,
                version_served=record.expected_version,
                serve_count=serve.serve_count,
            ),
            memory_uuid=record.uuid,
        )


def _authorization(delivered: _Delivered) -> tuple[AuthorizedRecord, ...]:
    """The exact set a later `merge` may target, as rows for `consolidation_group_candidate`."""
    anchor = delivered.revalidated.anchor
    return (
        *(
            ()
            if anchor is None
            else (
                AuthorizedRecord(
                    memory_uuid=anchor.uuid,
                    role=CandidateRole.ANCHOR,
                    version_served=anchor.expected_version,
                    rank=_ANCHOR_RANK,
                ),
            )
        ),
        *(
            AuthorizedRecord(
                memory_uuid=ranked.record.uuid,
                role=CandidateRole.CANDIDATE,
                version_served=ranked.record.expected_version,
                rank=ranked.rank,
            )
            for ranked in delivered.candidates
        ),
    )


def _versions_served(delivered: Sequence[GroupRecord]) -> Mapping[str, int]:
    return {record.uuid: record.expected_version for record in delivered}


async def _serve(
    db: aiosqlite.Connection,
    *,
    serve: _Serve,
    revalidated: _Revalidated,
    call: ConsolidationCall,
) -> ServedGroup:
    """Deliver one group: recompute candidates, persist authorization, mint receipts, log, count.

    The lease is refreshed here because a delivery is progress. It is deliberately not refreshed on
    the vacating or the deferral path, since neither delivers anything.
    """
    group_query = await candidates.build_group_query(revalidated.served, call=call)
    anchor = revalidated.anchor
    excluded = revalidated.all_member_uuids | (
        frozenset() if anchor is None else frozenset({anchor.uuid})
    )
    delivered = _Delivered(
        revalidated=revalidated,
        candidates=await candidates.select(
            db, group_query=group_query, excluded=excluded, call=call
        ),
    )

    await groups.record_delivery(
        db, group_id=serve.group.group_id, serve_count=serve.serve_count, served_at=serve.at
    )
    await groups.record_versions_served(
        db, group_id=serve.group.group_id, versions=_versions_served(revalidated.served)
    )
    await groups.replace_authorization(
        db, group_id=serve.group.group_id, records=_authorization(delivered)
    )
    await _mint_receipts(db, delivered=delivered, call=call, at=serve.at)
    await _log_delivery(db, serve=serve, delivered=delivered, call=call)
    await runs.refresh_lease(
        db, run_id=serve.run.run_id, at=serve.at, lease_seconds=call.settings.run_lease_seconds
    )
    return ServedGroup(
        group_id=serve.group.group_id,
        run_id=serve.run.run_id,
        anchor=anchor,
        anchor_vacated=revalidated.anchor_vacated,
        journal_entries=revalidated.served,
        candidates=delivered.candidates,
        shard=serve.group.shard,
        serve_count=serve.serve_count,
        n_gists_used=group_query.n_gists_used,
        remaining_groups=await groups.open_group_count(
            db, serve.run.run_id, excluding=serve.group.group_id
        ),
    )


async def _run_for(db: aiosqlite.Connection, *, call: ConsolidationCall, at: str) -> Run | Busy:
    """The run this call will serve from — replanning, or refusing, exactly as the design requires.

    An **effectively-expired** run is treated as absent for every caller *including its owner*,
    which is the fix for a real dead end: `next_group` replans only when the caller has no active
    run — so without this rule an owner whose lease lapsed would find its own run, be served a group
    from it, and be rejected `group_expired` with no way out, since `plan_groups` is a service RPC
    and not one of the four consolidator tools. So crash takeover by a stranger and lease recovery
    by the owner are the same code path.

    Only an `active` **and unexpired** run belonging to a different `(session_id, pid)` owner yields
    `Busy`. The pair, never the session alone: two consolidators of one kiro session share a
    `session_id` and a `client_kind`, so a session-only test would let a second worker serve a group
    the first still holds.

    **This path never displaces a live worker, and that asymmetry with `plan_groups` is the point.**
    `next_group` is the verb a *model* drives, and a model must not be able to decide that another
    worker has stopped. An explicit `plan_groups` may take an unexpired run over, because the
    evidence for doing so is a human invoking the skill again and D32 keeps that RPC out of both
    tool sets.
    """
    existing = await runs.stored_active(db)
    if existing is None or existing.has_lapsed(at=at):
        return await planning.plan_within_transaction(db, call=call, at=at)
    if existing.owner != call.owner:
        return Busy(
            holder_session=existing.owner.session_id,
            holder_pid=existing.owner.pid,
            expires_at=existing.expires_at,
        )
    return existing


async def next_group_within_transaction(
    db: aiosqlite.Connection, *, call: ConsolidationCall
) -> NextGroupOutcome:
    """`next_group`'s work, assuming the caller already holds an open transaction.

    The loop is bounded by the run's own group count, which is fixed at plan time: every iteration
    either returns a served group or transitions its candidate out of `pending`/`served`, so after
    that many iterations there is nothing left to consider and falling through is the correct
    conclusion rather than a give-up.
    """
    at = runs.now()
    resolved = await _run_for(db, call=call, at=at)
    if isinstance(resolved, Busy):
        return resolved
    run = resolved
    for _ in range((await groups.run_counts(db, run.run_id)).n_groups):
        candidate = await groups.next_candidate(db, run.run_id)
        if candidate is None:
            break
        revalidated = await _revalidate(db, group=candidate, at=at)
        if not revalidated.served:
            await groups.set_status(
                db,
                group_id=candidate.group_id,
                status=GroupStatus.COMPLETE,
                expected=candidate.status,
            )
            await runs.close_if_finished(db, run_id=run.run_id, ctx=call.ctx)
            continue
        if candidate.serve_count >= call.settings.max_group_serves:
            await groups.set_status(
                db,
                group_id=candidate.group_id,
                status=GroupStatus.DEFERRED,
                expected=candidate.status,
            )
            continue
        return await _serve(
            db,
            serve=_Serve(run=run, group=candidate, at=at),
            revalidated=revalidated,
            call=call,
        )
    await runs.close(db, run_id=run.run_id, status=RunStatus.COMPLETE, ctx=call.ctx)
    return RunDone()


async def next_group(db: aiosqlite.Connection, *, call: ConsolidationCall) -> NextGroupOutcome:
    """Deliver the next consolidation group, planning a run implicitly if the store has none.

    One transaction covering re-validation, every status transition it causes, the candidate
    recomputation and its embedding, the authorization set, the receipts and the events. The
    instrumentation and the state it describes therefore commit together or not at all, which is
    invariant 10 for this verb.

    Returns:
        A `ServedGroup`, or `RunDone` when this run has nothing left to serve, or `Busy` when an
        effectively-active run belongs to a different worker. All three are answers; none is an
        error.

    Raises:
        ZikaronError: `STORE_BUSY` if the store was locked, which the caller may retry, or
            `INDEX_FAILED` for any other driver failure. Nothing is left behind in either case — a
            failed serve delivers no group and records no delivery, so the next call reconsiders the
            same group from the same state.
    """

    async def work(connection: aiosqlite.Connection) -> NextGroupOutcome:
        return await next_group_within_transaction(connection, call=call)

    return await transactions.in_one_transaction(db, work, failure=_failure_map("next_group"))


def _failure_map(verb: str) -> transactions.FailureMap:
    """Contention is `store_busy`, everything else `index_failed` — a serve is a write.

    It writes dispositions, statuses, an authorization set, receipts and events, and it fails the
    way a write fails, so `architecture.md` §Errors gives it a write's two codes rather than a
    read's one.
    """
    return lambda error: (
        ZikaronError(ErrorCode.STORE_BUSY, verb=verb)
        if transactions.is_contention(error)
        else ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.INDEX_WRITE)
    )
