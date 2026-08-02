"""The consolidator validation ladder: authorization first, then existence, version, receipt, state.

`architecture.md` §"Validation precedence" is normative, and the order is part of the contract
because different orders return different errors — and, for the consolidator, **leak different
amounts of the store**.

**Why authorization must precede version, and why this is not a preference.** A `version_conflict`
payload returns the row's full current record and mints a receipt for it. If version were checked
first, a consolidator could name any uuid in the store with a deliberately wrong version and be
handed that record's gist, content and a licence to write it — reconstructing, one deliberate
conflict at a time, exactly the `fetch` D32 withholds, and leaving D7's claim that *code* selects
the candidates enforced by nothing. So rungs 2 and 3 answer only "is this uuid one of the ones I
handed you", and their payloads carry **uuids and nothing else**: no version, no state, no prose,
and `bad_merge_target`'s `reason` does not distinguish "does not exist" from "not authorized", so
the error cannot be used as an existence oracle either.

**Within the authorized set, version still precedes receipt.** A version bump deletes the row's
other receipts, so checking receipts first would report `no_read_receipt` for every ordinary
lost-update race — the consolidator *did* read, it read the version the serve delivered while the
row moved — and the one-round-trip retry that same invariant promises would become two.

**Every per-row rung is evaluated across all named rows before any is rejected**, so one call
reports every offending uuid rather than the first.

**A version conflict is returned, not raised.** For the consolidator verbs the design states
`{conflict: true, current: [...], remaining_uuids: [...]}` as a *response shape*, and it carries a
member list that only a read inside this transaction can produce. Returning it keeps that read where
it belongs and makes the committed audit trail ordinary rather than a carve-out. `no_read_receipt`
*is* raised, because the design gives it no second response shape — its events survive through
invariant 10's carve-out, which the transaction owner applies by inspecting the raised code.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import aiosqlite

from zikaron.core.consolidation import groups, rowstate, runs
from zikaron.core.consolidation.context import ConsolidationCall
from zikaron.core.consolidation.groups import Group, GroupStatus
from zikaron.core.consolidation.payload import GroupConflict, NamedRow, NamedRows
from zikaron.core.consolidation.runs import Run
from zikaron.core.errors import BadMergeTargetReason, ErrorCode, ZikaronError
from zikaron.core.records import memory as records
from zikaron.core.records import receipts
from zikaron.core.records.memory import ConflictRecord, Memory
from zikaron.core.records.receipts import ReceiptKey


@dataclass(frozen=True, slots=True)
class Authorized:
    """Everything a verb needs once every rung has passed, and nothing it would have to re-read.

    The rows are the `Memory` values the ladder already loaded and version-checked, so a verb
    neither re-reads them nor risks acting on a different snapshot than the one it was authorized
    against.
    """

    run: Run
    group: Group
    target: Memory | None
    absorbed: tuple[Memory, ...]

    @property
    def absorbed_uuids(self) -> tuple[str, ...]:
        """The absorbed rows' uuids, in the order the call named them."""
        return tuple(row.uuid for row in self.absorbed)


def _reject_expired(group: Group, run: Run, *, at: str) -> ZikaronError:
    """`group_expired`, reporting the **stored** status and the **effective** one side by side.

    Both, because they differ in the case that matters: a stored `'active'` row whose lease has
    passed is effectively expired to every reader, and only `plan_groups` ever writes the terminal
    status. A caller told only one of the two could not tell a lease that ran out from a run
    somebody replanned.
    """
    return ZikaronError(
        ErrorCode.GROUP_EXPIRED,
        group_id=group.group_id,
        run_status=run.status.value,
        expires_at=run.expires_at,
        effective_status=run.effective_status(at=at).value,
    )


def _require_authorized_run(group: Group, run: Run, *, call: ConsolidationCall, at: str) -> None:
    """The run half of rung 2: effectively active, and owned by this caller's `(session_id, pid)`.

    The **pair**, never the session alone, because every client of one kiro session shares a
    `session_id` *and* two consolidators of that session also share `client_kind='consolidator'` —
    so a session-only test would let a second worker mutate a group the first still holds and would
    defeat the one-worker guarantee `next_group` establishes.

    Both failures answer `group_expired` rather than distinguishing "not yours" from "lapsed", which
    is the design's own choice: the payload names the group the caller already holds and the
    recovery is the same call either way.
    """
    if run.owner != call.owner or not run.is_effectively_active(at=at):
        raise _reject_expired(group, run, at=at)


def _require_servable(group: Group, *, absorb: Sequence[NamedRow]) -> None:
    """The group half of rung 2: `served`, and none of the three states that are not.

    `pending` is the case the design's own list omitted, and it answers `not_in_group`: a group
    never delivered handed out no version, so no row of it is *actionable*, which is exactly what
    that code means. A conforming consolidator cannot reach it — it learns a `group_id` only from a
    serve — and it is checked rather than argued away because the alternative argument is three
    steps long.
    """
    if group.status is GroupStatus.COMPLETE:
        raise ZikaronError(ErrorCode.GROUP_COMPLETE, group_id=group.group_id)
    if group.status is GroupStatus.DEFERRED:
        raise ZikaronError(
            ErrorCode.GROUP_DEFERRED, group_id=group.group_id, serve_count=group.serve_count
        )
    if group.status is not GroupStatus.SERVED:
        raise ZikaronError(
            ErrorCode.NOT_IN_GROUP,
            group_id=group.group_id,
            uuids=[row.uuid for row in absorb],
        )


def _require_actionable_members(
    group: Group, *, absorb: Sequence[NamedRow], actionable: frozenset[str]
) -> None:
    """The member half of rung 2: a non-empty list, every element an undispositioned member.

    An empty list is `not_in_group` too, which the error table states directly: silence must not be
    able to complete a group, and an empty `absorb` is the closest thing to silence a call can be.
    """
    offending = [row.uuid for row in absorb if row.uuid not in actionable]
    if not absorb or offending:
        raise ZikaronError(ErrorCode.NOT_IN_GROUP, group_id=group.group_id, uuids=offending)


async def _require_authorized_target(
    db: aiosqlite.Connection, group: Group, *, target: NamedRow | None
) -> None:
    """The target half of rung 2: a `merge` target must be in this group's persisted authorization
    set.

    That table — not the `group_served` events, which are instrumentation — is the authority, and
    it is rewritten on every serve, so a record a *previous* serve showed is no longer authorized.
    The reason reported is `not_authorized` whether or not the uuid exists, deliberately, so the
    two cases are indistinguishable to the caller.
    """
    if target is None:
        return
    if target.uuid not in await groups.authorized_uuids(db, group.group_id):
        raise ZikaronError(
            ErrorCode.BAD_MERGE_TARGET,
            group_id=group.group_id,
            uuid=target.uuid,
            reason=BadMergeTargetReason.NOT_AUTHORIZED,
        )


async def _version_conflicts(
    db: aiosqlite.Connection,
    *,
    rows: dict[str, Memory],
    named: NamedRows,
    call: ConsolidationCall,
    verb: str,
) -> tuple[ConflictRecord, ...]:
    """Rung 4 across every named row: the current record for each whose version has moved.

    Empty when every version matches, which is the pass condition. Each conflicting row gets its own
    `conflict` receipt at the current version and its own `version_conflict` event before this
    returns — the audit trail invariant 10's carve-out is about — and the receipt is what makes
    D26's "re-decide in one round trip" true, since the consolidator has no `fetch` to earn one
    with.
    """
    conflicting = [row for row in named.every if rows[row.uuid].version != row.expected_version]
    return tuple(
        [
            await records.record_version_conflict(
                db,
                current=rows[row.uuid],
                ctx=call.ctx,
                verb=verb,
                presented_version=row.expected_version,
            )
            for row in conflicting
        ]
    )


async def _require_receipts(
    db: aiosqlite.Connection, *, named: NamedRows, call: ConsolidationCall, verb: str
) -> None:
    """Rung 5 across every named row: a receipt for each, at the version it presented.

    Raises once naming every uuid that lacks one, after logging a `no_receipt` event for each — the
    events are what D30's version-conflict signal counts, so they have to be durable even though the
    call changed nothing.
    """
    missing = [
        row
        for row in named.every
        if not await receipts.spend(
            db,
            key=ReceiptKey(
                session_id=call.ctx.session_id,
                client_kind=call.ctx.client_kind,
                memory_uuid=row.uuid,
                version=row.expected_version,
            ),
        )
    ]
    if not missing:
        return
    for row in missing:
        await records.record_no_receipt(
            db, uuid=row.uuid, ctx=call.ctx, verb=verb, presented_version=row.expected_version
        )
    raise ZikaronError(
        ErrorCode.NO_READ_RECEIPT, uuids=[row.uuid for row in missing], hint="fetch it first"
    )


async def _require_legal_state(db: aiosqlite.Connection, group: Group, *, named: NamedRows) -> None:
    """Rung 6: the target still targetable, every absorbed row still an actionable member.

    The absorbed half has exactly one producer and it is reachable: a primary agent `retire`s a
    served member, which bumps its version and revokes the serve-minted receipt, so the
    consolidator's call returns `version_conflict` with a fresh receipt — and the **retry**, now
    correct at every earlier rung, arrives here holding a row that is `active=0`. Such a row is
    *vacated in fact and not yet recorded*, failing the identical predicate the serve applies, so
    the answer is `not_in_group` rather than a new code: one meaning, one payload, one recovery. It
    leaks nothing, because a caller that reached this rung already passed the receipt check.

    The disposition itself is deliberately **not** written here. A rejected call must write no
    `consolidation_group*` disposition; the next serve records it, which is also what may legally
    close the group.
    """
    target = named.target
    if target is not None and not await rowstate.is_targetable(db, target.uuid):
        raise ZikaronError(
            ErrorCode.BAD_MERGE_TARGET,
            group_id=group.group_id,
            uuid=target.uuid,
            reason=BadMergeTargetReason.NOT_TARGETABLE,
        )
    left = [
        row.uuid for row in named.absorb if not await rowstate.is_deliverable_member(db, row.uuid)
    ]
    if left:
        raise ZikaronError(ErrorCode.NOT_IN_GROUP, group_id=group.group_id, uuids=left)


async def authorize(
    db: aiosqlite.Connection,
    *,
    group_id: str,
    named: NamedRows,
    call: ConsolidationCall,
    verb: str,
) -> Authorized | GroupConflict:
    """Run rungs 2-6 of the consolidator ladder, in the order the contract fixes.

    Rung 1 — bounds — has already run: `NamedRows` refuses a repeated `absorb` uuid at construction,
    and the `gist_max_tokens` bound belongs to the chunking preflight the two prose-authoring verbs
    run before their transaction opens.

    Assumes the caller's own open transaction, and stages no mutation of its own beyond the audit
    trail a version conflict is defined to leave: a rejection from any rung leaves every `memory`
    row, every version and every `consolidation_group*` status and disposition exactly as it found
    them.

    Returns:
        `Authorized` with the rows already loaded and checked, or `GroupConflict` when at least one
        named row's version has moved — a response shape rather than an error, carrying the current
        record for **every** conflicting uuid so the model can re-decide in one round trip.

    Raises:
        ZikaronError: `GROUP_UNKNOWN`, `GROUP_EXPIRED`, `GROUP_COMPLETE`, `GROUP_DEFERRED`,
            `NOT_IN_GROUP`, `BAD_MERGE_TARGET`, `NOT_FOUND` or `NO_READ_RECEIPT` — each from the
            rung the design assigns it to, and each having changed nothing but its own audit events.
    """
    at = runs.now()
    group = await groups.load(db, group_id)
    if group is None:
        raise ZikaronError(ErrorCode.GROUP_UNKNOWN, group_id=group_id)
    run = await runs.load(db, group.run_id)
    if run is None:
        # `consolidation_group.run_id`'s foreign key makes this unreachable without disabling FK
        # enforcement, and it is refused rather than treated as "no run" because a group whose run
        # cannot be found is not a group whose lease has lapsed — the two have opposite recoveries.
        raise ZikaronError(ErrorCode.GROUP_UNKNOWN, group_id=group_id)
    _require_authorized_run(group, run, call=call, at=at)
    _require_servable(group, absorb=named.absorb)
    actionable = frozenset(await groups.open_member_uuids(db, group_id))
    _require_actionable_members(group, absorb=named.absorb, actionable=actionable)
    await _require_authorized_target(db, group, target=named.target)

    rows = {row.uuid: await records.require_existing(db, row.uuid) for row in named.every}
    conflicts = await _version_conflicts(db, rows=rows, named=named, call=call, verb=verb)
    if conflicts:
        return GroupConflict(
            current=conflicts,
            remaining_uuids=await groups.open_member_uuids(db, group_id),
        )
    await _require_receipts(db, named=named, call=call, verb=verb)
    await _require_legal_state(db, group, named=named)
    return Authorized(
        run=run,
        group=group,
        target=None if named.target is None else rows[named.target.uuid],
        absorbed=tuple(rows[row.uuid] for row in named.absorb),
    )
