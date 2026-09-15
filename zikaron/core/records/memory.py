"""`memory` row mechanics: create, amend, retire, fetch — the primitives every write path composes.

Normative: `design/schema.md` §Tables and invariants 4-10; `design/architecture.md`
§"Validation precedence" (primary-agent ladder). This module's own package docstring
(`zikaron/core/records/__init__.py`) states why `create`/`amend` do not emit `remember`/`amend`
events and why `retire`/`fetch` do emit theirs.

`memory_fts`, `memory_chunk` and `memory_vec` are untouched by every function here, per this
layer's own scope — an external-content FTS5 table is never auto-synced by SQLite itself, so
writing `memory` without also writing `memory_fts` produces no SQLite-level error, only a stale
index. Keeping both writes inside one transaction is the indexing layer's job, and nothing here
queries either index, so no function in this module can observe the staleness it leaves behind.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast
from uuid import uuid4

import aiosqlite

from zikaron.core.clock import timestamp
from zikaron.core.errors import ErrorCode, RowState, ZikaronError
from zikaron.core.events import (
    EVENT_SPECS,
    EventDetail,
    FetchDetail,
    NoReceiptDetail,
    RetireDetail,
    VersionConflictDetail,
)
from zikaron.core.records import receipts, supersession
from zikaron.core.records.receipts import ReceiptKey, ReceiptSource
from zikaron.core.records.supersession import ResolvedHead, RootState
from zikaron.core.store import transactions


class Tier(StrEnum):
    """`memory.tier`'s two legal values, exactly as `schema.md`'s `CHECK` states them."""

    JOURNAL = "journal"
    LONG_TERM = "long_term"


@dataclass(frozen=True, slots=True)
class CallParams:
    """Everything one mutating call holds constant across every rung it passes.

    `session_id` and `client_kind` are the receipt scope (invariant 9); `op_id` correlates every
    `event` row one RPC call emits (`schema.md`: "one RPC = one `op_id`"). `max_depth` is
    `supersession_max_depth`, the cycle-walk cap every supersession-graph read or write in this
    module needs. The four are not all *identity* fields — `max_depth` is a policy value, not a
    fact about who is calling — but every mutating entry point genuinely needs all four together
    and none of them changes partway through one call, so bundling them is the correct fix for
    the `PLR0913` violation several functions here hit before this type existed, not a
    suppression dressed up as a domain type.
    """

    session_id: str
    client_kind: str
    op_id: str
    max_depth: int


@dataclass(frozen=True, slots=True)
class Memory:
    """One `memory` row, exactly as stored — no derived fields.

    `state` is deliberately absent here: it is a *display* concept derived from `active` and
    `superseded_by` (`RowState`, `architecture.md` §"MCP tool surface"), and a stored dataclass
    that also carried a value computable from its own other fields would let the two disagree.
    `resolved_state` computes it on demand instead.
    """

    uuid: str
    tier: Tier
    gist: str
    content: str
    active: bool
    superseded_by: str | None
    version: int
    created_at: str
    updated_at: str
    session_id: str | None
    token_count: int

    @property
    def resolved_state(self) -> RowState:
        """This row's display state, per `schema.md` §"Retrieval eligibility"'s three-state
        table: `live` iff `active`, else `superseded` iff `superseded_by` is set, else `retired`.
        """
        if self.active:
            return RowState.LIVE
        if self.superseded_by is not None:
            return RowState.SUPERSEDED
        return RowState.RETIRED


@dataclass(frozen=True, slots=True)
class ConflictRecord:
    """`architecture.md`'s `CONFLICT_RECORD`: `fetch`'s record minus `active` and the timestamps.

    Returned by a version conflict and named in `read_receipt.source='conflict'` — this is what
    D26's "re-decide in one round trip" promise actually hands back, and `superseded_by_latest`/
    `superseded_by_latest_state` are populated the same way `fetch`'s are, for the same reason: a
    conflict is often how an agent learns a row was superseded, and pointing it at a replacement
    that is itself dead would restart the loop it is trying to leave.
    """

    uuid: str
    gist: str
    content: str
    version: int
    tier: Tier
    state: RowState
    superseded_by: str | None
    superseded_by_latest: str | None
    superseded_by_latest_state: RowState | None


@dataclass(frozen=True, slots=True)
class FetchedMemory:
    """`fetch`'s per-record shape: `ConflictRecord`'s fields plus `active` and both timestamps."""

    uuid: str
    gist: str
    content: str
    version: int
    tier: Tier
    active: bool
    state: RowState
    superseded_by: str | None
    superseded_by_latest: str | None
    superseded_by_latest_state: RowState | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Rewrite:
    """The two fields a full rewrite supplies together — `create`'s and `amend`'s `gist`/
    `content`, and the identically-named parameters of the `zikaron_remember` and `zikaron_amend`
    tools.
    """

    gist: str
    content: str


#: `memory`'s columns in the fixed order `_row_to_memory` unpacks them — a module-level constant
#: rather than a literal repeated at each `SELECT`, so every reader of this row shape agrees with
#: the one place that turns it into a `Memory`. `S608` (string-built SQL) does not apply: nothing
#: here is assembled from a request-time value, only from this fixed, source-level string.
_MEMORY_COLUMNS: Final = (
    "uuid, tier, gist, content, active, superseded_by, version, created_at, updated_at, "
    "session_id, token_count"
)
_SELECT_MEMORY_BY_UUID: Final = f"SELECT {_MEMORY_COLUMNS} FROM memory WHERE uuid = ?"  # noqa: S608


def _row_to_memory(row: tuple[object, ...]) -> Memory:
    (
        uuid,
        tier,
        gist,
        content,
        active,
        superseded_by,
        version,
        created_at,
        updated_at,
        session_id,
        token_count,
    ) = row
    return Memory(
        uuid=str(uuid),
        tier=Tier(str(tier)),
        gist=str(gist),
        content=str(content),
        active=bool(active),
        superseded_by=None if superseded_by is None else str(superseded_by),
        version=cast(int, version),
        created_at=str(created_at),
        updated_at=str(updated_at),
        session_id=None if session_id is None else str(session_id),
        token_count=cast(int, token_count),
    )


async def load(db: aiosqlite.Connection, uuid: str) -> Memory | None:
    """One `memory` row by uuid, exactly as stored, or `None` if there is no such row.

    Public because a uuid is a handle and resolving one is not a predicate path: any state resolves,
    which is why `fetch` is absent from `eligibility.Consumer` too. Callers that need a *verb* — a
    receipt minted, an event logged — use `fetch`; callers that need the row's current facts inside
    a transaction they already hold, as serve-time re-validation and the consolidator ladder both
    do, use this. Assumes the caller's own transaction, and mints and logs nothing.
    """
    rows = await db.execute_fetchall(_SELECT_MEMORY_BY_UUID, (uuid,))
    found = list(rows)
    if not found:
        return None
    return _row_to_memory(tuple(found[0]))


async def require_existing(db: aiosqlite.Connection, uuid: str) -> Memory:
    """`load`, but `not_found` rather than `None` — the existence rung of both ladders.

    Public for the same reason as `load`, and separate from it because the two answer different
    questions: whether a row exists is sometimes the caller's own business (serve-time re-validation
    treats a missing row as a vacated member) and sometimes a rejection.
    """
    found = await load(db, uuid)
    if found is None:
        raise ZikaronError(ErrorCode.NOT_FOUND, uuid=uuid)
    return found


async def log_event(
    db: aiosqlite.Connection,
    *,
    ctx: CallParams,
    detail: EventDetail,
    memory_uuid: str | None,
) -> None:
    """Insert one `event` row. Never committed here — invariant 10 requires it share the
    caller's own transaction, so the caller's own `COMMIT` is what makes this durable.

    The kind comes from `detail`, not from a separate argument, so a payload cannot be filed under
    the wrong kind. `detail`'s own type fixes its field names and their types at type-check time,
    and `EVENT_SPECS[kind].validate` then re-checks the shape that reaches the log — the field
    order, and any closed set's membership — as defence in depth against a value type Python does
    not enforce. `memory_uuid` is checked against whether the kind names a memory at all, since a
    per-call kind naming one, or a per-memory kind naming none, would leave the signals joining on a
    column whose meaning changed with the writer.

    Public because every write path emits into the same log and there is exactly one `INSERT`
    statement for it: the indexed write verbs compose their own transactions out of this module's
    neutral cores and must not carry a second copy of this statement, since a schema change would
    then have two places to reach.

    Raises:
        ValueError: the payload's fields are not this kind's declared fields in order; a closed-set
            field holds a value outside its set; or `memory_uuid` disagrees with whether this kind
            names one.
    """
    spec = EVENT_SPECS[detail.kind]
    payload = detail.as_detail()
    spec.validate(payload)
    if spec.names_memory != (memory_uuid is not None):
        raise ValueError(
            f"{detail.kind}: names_memory={spec.names_memory} but memory_uuid={memory_uuid!r}"
        )
    await db.execute(
        "INSERT INTO event (at, session_id, client_kind, op_id, kind, memory_uuid, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            timestamp(),
            ctx.session_id,
            ctx.client_kind,
            ctx.op_id,
            detail.kind.value,
            memory_uuid,
            json.dumps(payload),
        ),
    )


async def _resolve_head(
    db: aiosqlite.Connection, memory: Memory, *, max_depth: int
) -> ResolvedHead | None:
    if memory.superseded_by is None:
        return None
    return await supersession.resolve_latest(db, start_uuid=memory.uuid, max_depth=max_depth)


def _root_state_to_row_state(state: RootState) -> RowState:
    return RowState.LIVE if state is RootState.LIVE else RowState.RETIRED


async def _to_fetched(db: aiosqlite.Connection, memory: Memory, *, max_depth: int) -> FetchedMemory:
    head = await _resolve_head(db, memory, max_depth=max_depth)
    return FetchedMemory(
        uuid=memory.uuid,
        gist=memory.gist,
        content=memory.content,
        version=memory.version,
        tier=memory.tier,
        active=memory.active,
        state=memory.resolved_state,
        superseded_by=memory.superseded_by,
        superseded_by_latest=None if head is None else head.uuid,
        superseded_by_latest_state=None if head is None else _root_state_to_row_state(head.state),
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


async def conflict_record(
    db: aiosqlite.Connection, memory: Memory, *, max_depth: int
) -> ConflictRecord:
    """`architecture.md`'s `CONFLICT_RECORD` for one row, with its supersession head resolved.

    Public because two ladders build it — this module's primary-agent one and the consolidation
    layer's, which can name several rows in one call and so returns a list of these where the
    primary verbs return one object. Both must produce the identical shape from the identical
    fields, which is what having one constructor buys.
    """
    head = await _resolve_head(db, memory, max_depth=max_depth)
    return ConflictRecord(
        uuid=memory.uuid,
        gist=memory.gist,
        content=memory.content,
        version=memory.version,
        tier=memory.tier,
        state=memory.resolved_state,
        superseded_by=memory.superseded_by,
        superseded_by_latest=None if head is None else head.uuid,
        superseded_by_latest_state=None if head is None else _root_state_to_row_state(head.state),
    )


async def create_within_transaction(
    db: aiosqlite.Connection,
    *,
    gist: str,
    content: str,
    session_id: str,
    tier: Tier = Tier.JOURNAL,
) -> Memory:
    """`create`'s work, assuming the caller already holds an open transaction.

    Neither commits nor rolls back — a caller composing this into a wider transaction (the
    indexing layer, which writes the chunks in the same transaction as the row) owns both, and
    `create` itself is the thin standalone wrapper below for a caller that wants this alone.

    `tier` defaults to `journal` because that is what D3 makes a *new* observation: every agent
    write lands unconsolidated. It is a parameter rather than a constant because `promote`'s
    new-row form authors a record that is long-term from its first version — writing it as journal
    and flipping it would spend a version on a row no reader ever saw, and invariant 8 makes a tier
    flip a real mutation rather than a fix-up.
    """
    new_uuid = str(uuid4())
    now = timestamp()
    await db.execute(
        "INSERT INTO memory "
        "(uuid, tier, gist, content, active, superseded_by, version, created_at, "
        " updated_at, session_id, token_count) "
        "VALUES (?, ?, ?, ?, 1, NULL, 1, ?, ?, ?, 0)",
        (new_uuid, tier.value, gist, content, now, now, session_id),
    )
    return await require_existing(db, new_uuid)


#: The two codes invariant 10's rejection carve-out applies to are `store.transactions`'s to name,
#: because the same rule governs every layer that owns a transaction. Every `ZikaronError` this
#: module raises outside that pair (`NOT_FOUND`, `INACTIVE_ROW`, `BAD_SUPERSESSION`) has written
#: nothing at the point it raises, so it rolls back the ordinary way.


async def commit_or_roll_back(db: aiosqlite.Connection, error: BaseException | None) -> None:
    """Commit on success or on a carve-out rejection; roll back on anything else.

    Re-exported from `store.transactions`, which owns the rule, so that this module's own wrappers
    and the composing callers reading them see one name. See that function for why only a
    transaction-*owning* caller may call it, and why the neutral `_<verb>_within_transaction` cores
    below — including their rejection helpers — never touch the transaction on any path.
    """
    await transactions.commit_or_roll_back(db, error)


async def create(db: aiosqlite.Connection, *, gist: str, content: str, session_id: str) -> Memory:
    """Insert a new `memory` row at `version=1`, `tier='journal'`, `active=1`.

    This is the row primitive `zikaron_remember` writes through, after the chunking preflight's
    `gist_max_tokens` bound and its own dedup search have already run — this function enforces
    neither, since both need the tokenizer or the indexes this layer does not touch. `content`
    and `gist` non-emptiness is enforced by the table's own `CHECK` constraints, which SQLite
    raises as `sqlite3.IntegrityError` rather than a `ZikaronError` — a boundary this layer leaves
    to its caller, since the chunking preflight refuses empty prose as `bounds` before any SQL runs
    and is where an agent-supplied value is checked.

    Does not emit a `remember` event: see this package's own docstring for why. Mints no receipt
    either — invariant 9's `own_write` source is for a row the caller can *already* write, and a
    row that did not exist a moment ago needs no licence to create. Takes no `CallParams`,
    unlike every other verb here, precisely because it authorizes nothing and logs nothing.

    Opens and commits its own transaction — invariant 2's "exactly one SQLite transaction" for a
    mutation with no rejection path to also commit. Call `create_within_transaction` directly
    instead if composing this into a wider transaction a caller already owns; calling this function
    from inside one would raise `OperationalError`, since SQLite refuses a nested `BEGIN`.
    """
    await db.execute("BEGIN")
    error: BaseException | None = None
    try:
        created = await create_within_transaction(
            db, gist=gist, content=content, session_id=session_id
        )
    except BaseException as caught:
        error = caught
        raise
    finally:
        await commit_or_roll_back(db, error)
    return created


async def fetch_within_transaction(
    db: aiosqlite.Connection, *, uuids: list[str], ctx: CallParams
) -> tuple[list[FetchedMemory], list[str]]:
    """`fetch`'s work, assuming the caller already holds an open transaction.

    Neither commits nor rolls back — see `create_within_transaction`'s docstring for why this
    split exists.
    """
    seen: set[str] = set()
    ordered_distinct: list[str] = []
    for uuid in uuids:
        if uuid not in seen:
            seen.add(uuid)
            ordered_distinct.append(uuid)

    records: list[FetchedMemory] = []
    missing: list[str] = []
    for uuid in ordered_distinct:
        memory = await load(db, uuid)
        found = memory is not None
        if memory is not None:
            fetched = await _to_fetched(db, memory, max_depth=ctx.max_depth)
            records.append(fetched)
            await receipts.mint(
                db,
                key=ReceiptKey(
                    session_id=ctx.session_id,
                    client_kind=ctx.client_kind,
                    memory_uuid=uuid,
                    version=memory.version,
                ),
                at=timestamp(),
                source=ReceiptSource.FETCH,
            )
        else:
            missing.append(uuid)
        await log_event(
            db,
            ctx=ctx,
            detail=FetchDetail(version=memory.version if memory is not None else None, found=found),
            memory_uuid=uuid,
        )
    return records, missing


async def fetch(
    db: aiosqlite.Connection, *, uuids: list[str], ctx: CallParams
) -> tuple[list[FetchedMemory], list[str]]:
    """Resolve every uuid in `uuids`, minting a `fetch` receipt for each one found.

    Duplicate uuids are collapsed to one record, in first-occurrence order, per
    `architecture.md`'s `zikaron_fetch` contract. An unknown uuid is reported in the returned
    `missing` list rather than failing the whole call — `schema.md` §Bounds: "a dead handle is
    something the agent needs told rather than a reason to fail the batch."

    Emits one `fetch` event per **distinct** uuid requested — found or not, since `found` is
    itself part of what the event records — inside the same transaction as the receipts it
    mints and commits, per invariant 10.

    Opens and commits its own transaction. Call `fetch_within_transaction` directly instead if
    composing this into a wider transaction a caller already owns — see `create`'s docstring for
    why calling this function itself from inside one would fail.

    Returns:
        `(records, missing)` — `records` in the order `uuids` first named each distinct uuid,
        and `missing` the subset of distinct uuids that named no row.
    """
    await db.execute("BEGIN")
    error: BaseException | None = None
    try:
        result = await fetch_within_transaction(db, uuids=uuids, ctx=ctx)
    except BaseException as caught:
        # Every statement inside `fetch_within_transaction` is a SELECT/upsert/insert with no
        # CHECK constraint a well-formed call can trip — this guards against a driver-level
        # failure (disk I/O, a killed connection) rather than a business-logic rejection, so no
        # fixture in this test module can trigger it without faking the connection itself.
        error = caught
        raise
    finally:
        await commit_or_roll_back(db, error)
    return result


async def record_version_conflict(
    db: aiosqlite.Connection,
    *,
    current: Memory,
    ctx: CallParams,
    verb: str,
    presented_version: int,
) -> ConflictRecord:
    """Mint the `conflict` receipt, log the `version_conflict` event, and build the record.

    Everything invariant 10's carve-out requires a version conflict to leave behind, and **no
    raise** — because the two ladders differ in exactly that: a primary-agent verb names one row and
    raises on it, while a consolidator verb names several, has to evaluate all of them, and raises
    once carrying every conflicting record. Both need the identical per-row work, so it lives here
    and neither ladder writes its own.

    The receipt is what makes D26's "re-decide in one round trip" true: the payload hands back the
    current full record, so the caller's retry has a licence for it without a `fetch` it may not
    even have (the consolidator has no `fetch` at all).

    Does **not** commit. Whether the audit trail this writes survives is the transaction-owning
    caller's decision, through `commit_or_roll_back`, which inspects the raised error's code — see
    that function for why a neutral core may never make it.
    """
    await receipts.mint(
        db,
        key=ReceiptKey(
            session_id=ctx.session_id,
            client_kind=ctx.client_kind,
            memory_uuid=current.uuid,
            version=current.version,
        ),
        at=timestamp(),
        source=ReceiptSource.CONFLICT,
    )
    await log_event(
        db,
        ctx=ctx,
        detail=VersionConflictDetail(
            verb=verb,
            expected_version=presented_version,
            actual_version=current.version,
        ),
        memory_uuid=current.uuid,
    )
    return await conflict_record(db, current, max_depth=ctx.max_depth)


async def record_no_receipt(
    db: aiosqlite.Connection, *, uuid: str, ctx: CallParams, verb: str, presented_version: int
) -> None:
    """Log the `no_receipt` event for one uuid, and mint nothing.

    No receipt is minted, unlike a version conflict: a missing receipt hands back nothing to
    re-decide from, since the caller already named the current version correctly — the record it
    holds is not stale, it is simply unlicensed. Split from the raise for the same reason
    `record_version_conflict` is: the consolidator ladder logs one of these per offending uuid and
    then raises once naming all of them.
    """
    await log_event(
        db,
        ctx=ctx,
        detail=NoReceiptDetail(verb=verb, version_presented=presented_version),
        memory_uuid=uuid,
    )


async def _reject_version_conflict(
    db: aiosqlite.Connection,
    *,
    current: Memory,
    ctx: CallParams,
    verb: str,
    presented_version: int,
) -> None:
    """Mint a `conflict` receipt at the current version, log `version_conflict`, then raise.

    `schema.md` invariant 10: "A rejected call commits no domain mutation but does commit its
    audit events and, for a version conflict, the receipt for the record it returned." Making
    that true is the transaction-*owning* wrapper's job, not this function's — see the "Does
    **not** commit" note below for why the two are split.

    Raises `current` as a bare `ConflictRecord`, not a list: this function backs only
    `_authorize_mutation`, which every primary-agent verb (`amend`, `retire`) calls for exactly
    one named row, and `architecture.md`'s tool surface states `zikaron_amend`/`zikaron_retire`'s
    conflict shape as `{conflict: true, current: CONFLICT_RECORD}` — one object, never a list.
    The list form (`current: [CONFLICT_RECORD, ...]`) belongs to the four consolidator verbs,
    which can name several rows in one call and whose own ladder therefore composes
    `record_version_conflict` directly rather than calling this.

    Does **not** commit. A composing caller could stage its own write before ever calling into the
    authorization ladder, and this function has no way to see that from where it sits —
    so it never commits, unconditionally, rather than trying to reason about what came before it.
    The transaction-*owning* wrapper (`create`/`fetch`/`amend`/`retire`) is the only place that
    decides commit-vs-rollback at all, via `commit_or_roll_back`, which inspects the caught
    error's *code* (this rejection's `VERSION_CONFLICT`, or `NO_READ_RECEIPT` from
    `_reject_no_receipt`) and commits only for those two — see `commit_or_roll_back`'s own
    docstring.
    """
    record = await record_version_conflict(
        db, current=current, ctx=ctx, verb=verb, presented_version=presented_version
    )
    raise ZikaronError(ErrorCode.VERSION_CONFLICT, current=record)


async def _reject_no_receipt(
    db: aiosqlite.Connection, *, uuid: str, ctx: CallParams, verb: str, presented_version: int
) -> None:
    """Log `no_receipt`, then raise — no receipt is minted for this rejection.

    Unlike a version conflict, a missing receipt hands back nothing to re-decide from: the
    caller already named the current version correctly, so the record it holds is not stale —
    it is simply unlicensed. `schema.md` names the recovery as `fetch it first`, which is exactly
    what `ERROR_SPECS[NO_READ_RECEIPT]`'s fixed `hint` field states.

    Does **not** commit, for the same reason `_reject_version_conflict` does not — see its
    docstring.
    """
    await record_no_receipt(db, uuid=uuid, ctx=ctx, verb=verb, presented_version=presented_version)
    raise ZikaronError(ErrorCode.NO_READ_RECEIPT, uuids=[uuid], hint="fetch it first")


async def _authorize_mutation(
    db: aiosqlite.Connection,
    *,
    named_uuids: tuple[str, ...],
    version: int,
    ctx: CallParams,
    verb: str,
) -> Memory:
    """Rungs 2-4 of the primary-agent ladder: existence, version, receipt — in that order.

    `architecture.md`'s primary-agent ladder runs bounds, then existence, then version, then
    receipt, then state legality, then the mutation itself. Bounds is this function's caller's
    job (an agent-facing bound like `gist_max_tokens` needs a tokenizer this layer has none of);
    state
    legality is the mutation-specific check `amend`/`retire` each run for themselves, since what
    counts as illegal state differs between them. This function is exactly the three rungs every
    mutating verb shares.

    Args:
        named_uuids: every uuid this call names, in order, **with the first element being the
            row version/receipt is actually checked against** — `amend`'s `uuid`, or `retire`'s
            `uuid` followed by `superseded_by` when given. Existence of *every* named uuid is
            one rung (`architecture.md`: "existence of every named uuid"), so every element is
            checked here, before the first element's own version and receipt, rather than left
            to a later caller whose own check would run only after the first element had already
            cleared version and receipt — which is exactly the ordering bug this parameter
            exists to close. Must be non-empty.
    """
    uuid, *other_named = named_uuids
    current = await require_existing(db, uuid)
    for other in other_named:
        await require_existing(db, other)
    if current.version != version:
        await _reject_version_conflict(
            db, current=current, ctx=ctx, verb=verb, presented_version=version
        )
    held = await receipts.spend(
        db,
        key=ReceiptKey(
            session_id=ctx.session_id,
            client_kind=ctx.client_kind,
            memory_uuid=uuid,
            version=version,
        ),
    )
    if not held:
        await _reject_no_receipt(db, uuid=uuid, ctx=ctx, verb=verb, presented_version=version)
    return current


async def mint_own_write_receipt(
    db: aiosqlite.Connection, *, uuid: str, version: int, ctx: CallParams
) -> None:
    """Mint the writer's `own_write` receipt for `uuid` at `version`.

    Invariant 9's `own_write` source: the caller authored this exact prose, so it may write it
    again without fetching it back. Split out from the version-bump path because a *newly created*
    row has nothing to revoke — every receipt for a uuid that did not exist a moment ago is the one
    just minted — while an amended row must also revoke the receipts the bump invalidated.
    """
    await receipts.mint(
        db,
        key=ReceiptKey(
            session_id=ctx.session_id,
            client_kind=ctx.client_kind,
            memory_uuid=uuid,
            version=version,
        ),
        at=timestamp(),
        source=ReceiptSource.OWN_WRITE,
    )


async def _bump_version_and_mint_own_write(
    db: aiosqlite.Connection, *, uuid: str, new_version: int, ctx: CallParams
) -> None:
    """Mint the writer's own-write receipt at `new_version`, then revoke every other receipt for
    `uuid`. Order matters: minting first is what keeps the row from being, for even one
    statement's duration, a written row with no receipt for it at all."""
    await mint_own_write_receipt(db, uuid=uuid, version=new_version, ctx=ctx)
    await receipts.revoke_on_version_bump(
        db,
        keep=ReceiptKey(
            session_id=ctx.session_id,
            client_kind=ctx.client_kind,
            memory_uuid=uuid,
            version=new_version,
        ),
    )


def _require_active(memory: Memory) -> None:
    """The shared half of `amend`/`retire`'s state-legality rung: refuse a row already `active=0`.

    Extracted so the raise site is a function whose only job is raising, per `TRY301`'s "abstract
    the raise" guidance — the two callers otherwise duplicated the same check, and duplicating a
    validation rule is exactly the drift class `coding-standards.md` warns about for anything the
    design states as a single rule.

    Raises:
        ZikaronError: `INACTIVE_ROW`, naming the row's current `state` — never `LIVE`, since
            this function's own name is the guarantee that it is called only when `active` is
            about to matter.
    """
    if not memory.active:
        raise ZikaronError(ErrorCode.INACTIVE_ROW, uuid=memory.uuid, state=memory.resolved_state)


async def apply_rewrite(
    db: aiosqlite.Connection, *, current: Memory, rewrite: Rewrite, ctx: CallParams
) -> Memory:
    """Write new prose over `current` and bump its `version`. Authorizes nothing, logs nothing.

    The three `apply_*` functions here are the **column-level** mutators every write verb in the
    system ends at, split out from the verbs so that a second verb writing the same columns cannot
    write them a second, slightly different way. Each one bumps `version` (invariant 8), refreshes
    `updated_at`, mints the writer's `own_write` receipt at the new version and revokes every other
    receipt for the row (invariant 9) — and does **not** decide who may call it, which state is
    legal, or what event describes it. Those three differ per verb: `amend` and `retire` run the
    primary-agent ladder and emit their own kinds, while `merge`, `promote` and `discard` run the
    consolidator ladder and emit theirs, and both classes of caller need the identical column write
    underneath.

    Args:
        current: the row as authorization found it, at the version being replaced. Passed in rather
            than re-read, because the caller's ladder has already read it and a second read inside
            one transaction would only be another chance for the two to disagree about what is
            being overwritten.

    Returns:
        The row as this call left it, re-read so the caller sees stored values rather than the ones
        it hoped it wrote.
    """
    new_version = current.version + 1
    await db.execute(
        "UPDATE memory SET gist = ?, content = ?, version = ?, updated_at = ? WHERE uuid = ?",
        (rewrite.gist, rewrite.content, new_version, timestamp(), current.uuid),
    )
    await _bump_version_and_mint_own_write(db, uuid=current.uuid, new_version=new_version, ctx=ctx)
    return await require_existing(db, current.uuid)


async def apply_retirement(
    db: aiosqlite.Connection, *, current: Memory, superseded_by: str | None, ctx: CallParams
) -> Memory:
    """Soft-retire `current`, optionally writing its one supersession edge, and bump `version`.

    Validates the edge (invariant 6) immediately before writing it, in this same transaction, which
    is what keeps edge validation and edge writing from drifting apart across the several verbs that
    create edges — `retire` with a replacement, `merge` absorbing rows into its target, `promote`
    absorbing rows into a new record. `superseded_by=None` retires outright and validates nothing,
    because there is no claim about a replacement to be false.

    Authorizes nothing and logs nothing; see `apply_rewrite` for the reason that split exists.

    Raises:
        ZikaronError: `BAD_SUPERSESSION` if `superseded_by` names an illegal edge — a self-edge, a
            target already retired-outright at this instant, or one that would close a cycle; or
            `NOT_FOUND` if it names no row, which the caller's own existence rung should have caught
            first.
    """
    if superseded_by is not None:
        await supersession.validate_new_edge(
            db, from_uuid=current.uuid, to_uuid=superseded_by, max_depth=ctx.max_depth
        )
    new_version = current.version + 1
    await db.execute(
        "UPDATE memory SET active = 0, superseded_by = ?, version = ?, updated_at = ? "
        "WHERE uuid = ?",
        (superseded_by, new_version, timestamp(), current.uuid),
    )
    await _bump_version_and_mint_own_write(db, uuid=current.uuid, new_version=new_version, ctx=ctx)
    return await require_existing(db, current.uuid)


async def apply_tier(
    db: aiosqlite.Connection, *, current: Memory, tier: Tier, ctx: CallParams
) -> Memory:
    """Move `current` between tiers and bump its `version`. Authorizes nothing, logs nothing.

    A tier flip is a full mutation rather than a metadata touch, which is invariant 8's own list
    ("including a `tier` flip and a `superseded_by` write") and not a strict reading of it: a
    primary agent may be amending the row concurrently, and D3 makes the tier the difference between
    a journal line and a long-term record, so a flip that left `version` alone would be a change
    another actor's receipt still licensed it to overwrite.

    Touches no indexed column — `memory_fts` indexes `gist` and `content`, and `tier` appears in
    neither index — so a caller flipping a tier without changing prose has no index to rebuild.
    """
    new_version = current.version + 1
    await db.execute(
        "UPDATE memory SET tier = ?, version = ?, updated_at = ? WHERE uuid = ?",
        (tier.value, new_version, timestamp(), current.uuid),
    )
    await _bump_version_and_mint_own_write(db, uuid=current.uuid, new_version=new_version, ctx=ctx)
    return await require_existing(db, current.uuid)


async def amend_within_transaction(
    db: aiosqlite.Connection, *, uuid: str, version: int, rewrite: Rewrite, ctx: CallParams
) -> tuple[Memory, Memory]:
    """`amend`'s work, assuming the caller already holds an open transaction.

    Never commits or rolls back itself, on any path — see `create_within_transaction`'s
    docstring for the general reason, and `_reject_version_conflict`/`_reject_no_receipt`'s own
    docstrings for why even their rejection paths raise without touching the transaction.
    Invariant 10's rejection carve-out (the audit event, and for a conflict the receipt, survive
    even though the domain mutation does not) is honored by whichever wrapper calls this — via
    `commit_or_roll_back` — not by this function.

    Returns:
        `(before, after)` — the row as authorization found it and as this call left it. Both,
        rather than only the new row, because a composing caller needs the **pre-write** `gist`
        and `content` to remove the right postings from `memory_fts`: that index is
        external-content, so removing them by reading the content table would have to happen
        before this function's own `UPDATE`, which is to say before authorization finished. The
        `from_version` an `amend` event reports comes from the same place.
    """
    current = await _authorize_mutation(
        db, named_uuids=(uuid,), version=version, ctx=ctx, verb="amend"
    )
    _require_active(current)
    return current, await apply_rewrite(db, current=current, rewrite=rewrite, ctx=ctx)


async def amend(
    db: aiosqlite.Connection, *, uuid: str, version: int, rewrite: Rewrite, ctx: CallParams
) -> Memory:
    """Full rewrite of `gist`/`content`, bumping `version` (D6, invariant 8).

    Runs the shared authorization rungs, then this verb's own state-legality rung — `amend`
    rejects a row already `active=0` as `inactive_row`, naming its current `state` — then
    mutates in one transaction with the version bump and the receipt revocation/mint.

    Does not emit an `amend` event: see this package's own docstring. The indexing layer wraps this
    function with the chunking preflight and emits the composed event, where the size fields it
    carries have real values.

    A `version_conflict` or `no_read_receipt` rejection commits its own receipt and event
    (invariant 10's carve-out for a rejected call) — see `_reject_version_conflict` and
    `_reject_no_receipt`, and `commit_or_roll_back`, which is what actually decides that here,
    in this wrapper rather than in the neutral core. A `not_found` or `inactive_row` rejection
    has written nothing yet at the point it raises, so it rolls back cleanly with nothing to
    preserve.

    Opens and commits its own transaction. Call `amend_within_transaction` directly instead if
    composing this into a wider transaction a caller already owns — see `create`'s docstring for
    why calling this function itself from inside one would fail.

    Raises:
        ZikaronError: `NOT_FOUND` if `uuid` names no row; `VERSION_CONFLICT` if `version` is
            not the row's current one (mints a `conflict` receipt and logs the event before
            raising); `NO_READ_RECEIPT` if the caller holds no matching receipt (logs the event
            before raising); `INACTIVE_ROW` if the row is already `active=0`.
    """
    await db.execute("BEGIN")
    error: BaseException | None = None
    try:
        _, amended = await amend_within_transaction(
            db, uuid=uuid, version=version, rewrite=rewrite, ctx=ctx
        )
    except BaseException as caught:
        error = caught
        raise
    finally:
        await commit_or_roll_back(db, error)
    return amended


async def retire_within_transaction(
    db: aiosqlite.Connection,
    *,
    uuid: str,
    version: int,
    superseded_by: str | None,
    ctx: CallParams,
) -> Memory:
    """`retire`'s work, assuming the caller already holds an open transaction.

    Never commits or rolls back itself, on any path — see `amend_within_transaction`'s
    docstring, which states the same contract for the same reason.
    """
    named_uuids = (uuid,) if superseded_by is None else (uuid, superseded_by)
    current = await _authorize_mutation(
        db, named_uuids=named_uuids, version=version, ctx=ctx, verb="retire"
    )
    _require_active(current)
    retired = await apply_retirement(db, current=current, superseded_by=superseded_by, ctx=ctx)
    await log_event(
        db,
        ctx=ctx,
        detail=RetireDetail(
            from_version=current.version,
            to_version=retired.version,
            superseded_by=superseded_by,
        ),
        memory_uuid=uuid,
    )
    return retired


async def retire(
    db: aiosqlite.Connection,
    *,
    uuid: str,
    version: int,
    superseded_by: str | None,
    ctx: CallParams,
) -> Memory:
    """Soft-retire a row (D16): `active=0`, optionally pointing `superseded_by` at a replacement.

    `superseded_by` set writes a supersession edge, validated by `supersession.validate_new_edge`
    (invariant 6) inside this same transaction — no self-edge, no cycle, and the target not
    already retired-outright at this instant. `superseded_by` omitted retires outright: the row
    becomes a terminal component if anything else already pointed at it, which is legal
    (invariant 6's "a root is live or terminal, and both are legal").

    Emits `retire`'s event — the one mutation kind this layer owns outright, since its `detail`
    names no
    chunking-derived field (`from_version`, `to_version`, `superseded_by`, none of which need a
    tokenizer or an index).

    Opens and commits its own transaction. Call `retire_within_transaction` directly instead if
    composing this into a wider transaction a caller already owns — see `create`'s docstring for
    why calling this function itself from inside one would fail.

    Raises:
        ZikaronError: as `amend`, for the shared rungs; `NOT_FOUND` if `uuid` **or**
            `superseded_by` (when given) names no row — `uuid` checked first, since it is the
            call's own subject, then `superseded_by`; both existence checks run before version or
            receipt is checked for `uuid`, per the ladder's existence rung preceding its version
            and receipt rungs; `INACTIVE_ROW` if the row is already `active=0`;
            `BAD_SUPERSESSION` (from `supersession.validate_new_edge`) if `superseded_by` names
            an illegal edge.
    """
    await db.execute("BEGIN")
    error: BaseException | None = None
    try:
        retired = await retire_within_transaction(
            db, uuid=uuid, version=version, superseded_by=superseded_by, ctx=ctx
        )
    except BaseException as caught:
        error = caught
        raise
    finally:
        await commit_or_roll_back(db, error)
    return retired
