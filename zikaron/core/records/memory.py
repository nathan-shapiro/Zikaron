"""`memory` row mechanics: create, amend, retire, fetch — the primitives M4 and M6 compose.

Normative: `design/schema.md` §Tables and invariants 4-10; `design/architecture.md`
§"Validation precedence" (primary-agent ladder). This module's own package docstring
(`zikaron/core/records/__init__.py`) states why `create`/`amend` do not emit `remember`/`amend`
events and why `retire`/`fetch` do emit theirs.

`memory_fts`, `memory_chunk` and `memory_vec` are untouched by every function here, per this
milestone's fence — an external-content FTS5 table is never auto-synced by SQLite itself, so
writing `memory` without also writing `memory_fts` produces no SQLite-level error, only a stale
index that M4 makes current. Nothing in M3 queries it, so nothing observes the staleness yet.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, cast
from uuid import uuid4

import aiosqlite

from zikaron.core.errors import ErrorCode, RowState, ZikaronError
from zikaron.core.events import EventKind
from zikaron.core.records import receipts, supersession
from zikaron.core.records.receipts import ReceiptKey, ReceiptSource
from zikaron.core.records.supersession import ResolvedHead, RootState


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
    `content`, and `zikaron_remember`'s and `zikaron_amend`'s (M6) own tool parameters of the
    same names.
    """

    gist: str
    content: str


def _now() -> str:
    """The current instant, ISO-8601 in UTC — `created_at`/`updated_at`/`event.at`'s own format."""
    return datetime.now(UTC).isoformat()


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


async def _load(db: aiosqlite.Connection, uuid: str) -> Memory | None:
    rows = await db.execute_fetchall(_SELECT_MEMORY_BY_UUID, (uuid,))
    found = list(rows)
    if not found:
        return None
    return _row_to_memory(tuple(found[0]))


async def _require_existing(db: aiosqlite.Connection, uuid: str) -> Memory:
    found = await _load(db, uuid)
    if found is None:
        raise ZikaronError(ErrorCode.NOT_FOUND, uuid=uuid)
    return found


async def _log_event(
    db: aiosqlite.Connection,
    *,
    ctx: CallParams,
    kind: EventKind,
    memory_uuid: str | None,
    detail: dict[str, object],
) -> None:
    """Insert one `event` row. Never committed here — invariant 10 requires it share the
    caller's own transaction, so the caller's own `COMMIT` is what makes this durable."""
    await db.execute(
        "INSERT INTO event (at, session_id, client_kind, op_id, kind, memory_uuid, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            _now(),
            ctx.session_id,
            ctx.client_kind,
            ctx.op_id,
            kind.value,
            memory_uuid,
            json.dumps(detail),
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


async def _to_conflict_record(
    db: aiosqlite.Connection, memory: Memory, *, max_depth: int
) -> ConflictRecord:
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


async def _create_within_transaction(
    db: aiosqlite.Connection, *, gist: str, content: str, session_id: str
) -> Memory:
    """`create`'s work, assuming the caller already holds an open transaction.

    Neither commits nor rolls back — a caller composing this into a wider transaction (M4's
    chunking preflight, in the same transaction as the row write) owns both, and `create` itself
    is the thin standalone wrapper below for a caller that just wants to run this alone.
    """
    new_uuid = str(uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO memory "
        "(uuid, tier, gist, content, active, superseded_by, version, created_at, "
        " updated_at, session_id, token_count) "
        "VALUES (?, 'journal', ?, ?, 1, NULL, 1, ?, ?, ?, 0)",
        (new_uuid, gist, content, now, now, session_id),
    )
    return await _require_existing(db, new_uuid)


#: The two codes invariant 10's rejection carve-out applies to: a rejected call that still
#: commits its audit event and, for a conflict, the receipt for the record it returned. Every
#: other `ZikaronError` this module raises (`NOT_FOUND`, `INACTIVE_ROW`, `BAD_SUPERSESSION`) has
#: written nothing at the point it raises, so it rolls back the ordinary way.
_CARVE_OUT_CODES: Final = (ErrorCode.VERSION_CONFLICT, ErrorCode.NO_READ_RECEIPT)


async def _commit_or_roll_back(db: aiosqlite.Connection, error: BaseException | None) -> None:
    """Commit on success or on a carve-out rejection; roll back on anything else.

    This is the one place that decides which of the two invariant-10 outcomes applies, and it
    lives in the transaction-*owning* wrapper (`amend`/`retire`/`create`/`fetch`), never in a
    `_<verb>_within_transaction` core: only the owner structurally knows that authorization ran
    with nothing else staged ahead of it in this transaction, which is what makes committing a
    carve-out rejection safe. A neutral core called from inside a wider transaction a composing
    caller (M4) already owns must never make this decision itself — see `_reject_version_conflict`
    and `_reject_no_receipt`'s own docstrings for why they raise without committing.
    """
    if error is None or (isinstance(error, ZikaronError) and error.code in _CARVE_OUT_CODES):
        await db.commit()
    else:
        await db.rollback()


async def create(db: aiosqlite.Connection, *, gist: str, content: str, session_id: str) -> Memory:
    """Insert a new `memory` row at `version=1`, `tier='journal'`, `active=1`.

    This is the row primitive `zikaron_remember` (M6) writes through, after its own dedup search
    and `gist_max_tokens` bound have already run — this function itself enforces neither, since
    both need the tokenizer or the FTS/vector index this milestone's fence excludes. `content`
    and `gist` non-emptiness is enforced by the table's own `CHECK` constraints, which SQLite
    raises as `sqlite3.IntegrityError` rather than a `ZikaronError` — a boundary this milestone
    leaves to its caller, since M6 owns the tool-facing `bounds` rejection for an agent-supplied
    value.

    Does not emit a `remember` event: see this package's own docstring for why. Mints no receipt
    either — invariant 9's `own_write` source is for a row the caller can *already* write, and a
    row that did not exist a moment ago needs no licence to create. Takes no `CallParams`,
    unlike every other verb here, precisely because it authorizes nothing and logs nothing.

    Opens and commits its own transaction — invariant 2's "exactly one SQLite transaction" for a
    mutation with no rejection path to also commit. Call `_create_within_transaction` directly
    instead if composing this into a wider transaction a caller (M4) already owns; calling this
    function from inside one would raise `OperationalError`, since SQLite refuses a nested
    `BEGIN`.
    """
    await db.execute("BEGIN")
    error: BaseException | None = None
    try:
        created = await _create_within_transaction(
            db, gist=gist, content=content, session_id=session_id
        )
    except BaseException as caught:
        error = caught
        raise
    finally:
        await _commit_or_roll_back(db, error)
    return created


async def _fetch_within_transaction(
    db: aiosqlite.Connection, *, uuids: list[str], ctx: CallParams
) -> tuple[list[FetchedMemory], list[str]]:
    """`fetch`'s work, assuming the caller already holds an open transaction.

    Neither commits nor rolls back — see `_create_within_transaction`'s docstring for why this
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
        memory = await _load(db, uuid)
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
                at=_now(),
                source=ReceiptSource.FETCH,
            )
        else:
            missing.append(uuid)
        await _log_event(
            db,
            ctx=ctx,
            kind=EventKind.FETCH,
            memory_uuid=uuid,
            detail={
                "version": memory.version if memory is not None else None,
                "found": found,
            },
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

    Opens and commits its own transaction. Call `_fetch_within_transaction` directly instead if
    composing this into a wider transaction a caller already owns — see `create`'s docstring for
    why calling this function itself from inside one would fail.

    Returns:
        `(records, missing)` — `records` in the order `uuids` first named each distinct uuid,
        and `missing` the subset of distinct uuids that named no row.
    """
    await db.execute("BEGIN")
    error: BaseException | None = None
    try:
        result = await _fetch_within_transaction(db, uuids=uuids, ctx=ctx)
    except BaseException as caught:
        # Every statement inside `_fetch_within_transaction` is a SELECT/upsert/insert with no
        # CHECK constraint a well-formed call can trip — this guards against a driver-level
        # failure (disk I/O, a killed connection) rather than a business-logic rejection, so no
        # fixture in this test module can trigger it without faking the connection itself.
        error = caught
        raise
    finally:
        await _commit_or_roll_back(db, error)
    return result


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
    which can name several rows in one call; those are M7's own authorization path and would
    need their own rejection helper, not this one.

    Does **not** commit. A composing caller (M4) could stage its own write before ever calling
    into the authorization ladder, and this function has no way to see that from where it sits —
    so it never commits, unconditionally, rather than trying to reason about what came before it.
    The transaction-*owning* wrapper (`create`/`fetch`/`amend`/`retire`) is the only place that
    decides commit-vs-rollback at all, via `_commit_or_roll_back`, which inspects the caught
    error's *code* (this rejection's `VERSION_CONFLICT`, or `NO_READ_RECEIPT` from
    `_reject_no_receipt`) and commits only for those two — see `_commit_or_roll_back`'s own
    docstring.
    """
    await receipts.mint(
        db,
        key=ReceiptKey(
            session_id=ctx.session_id,
            client_kind=ctx.client_kind,
            memory_uuid=current.uuid,
            version=current.version,
        ),
        at=_now(),
        source=ReceiptSource.CONFLICT,
    )
    await _log_event(
        db,
        ctx=ctx,
        kind=EventKind.VERSION_CONFLICT,
        memory_uuid=current.uuid,
        detail={
            "verb": verb,
            "expected_version": presented_version,
            "actual_version": current.version,
        },
    )
    record = await _to_conflict_record(db, current, max_depth=ctx.max_depth)
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
    await _log_event(
        db,
        ctx=ctx,
        kind=EventKind.NO_RECEIPT,
        memory_uuid=uuid,
        detail={"verb": verb, "version_presented": presented_version},
    )
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
    job (an agent-facing bound like `gist_max_tokens` needs the tokenizer M6 supplies); state
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
    current = await _require_existing(db, uuid)
    for other in other_named:
        await _require_existing(db, other)
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


async def _bump_version_and_mint_own_write(
    db: aiosqlite.Connection, *, uuid: str, new_version: int, ctx: CallParams
) -> None:
    """Mint the writer's own-write receipt at `new_version`, then revoke every other receipt for
    `uuid`. Order matters: minting first is what keeps the row from being, for even one
    statement's duration, a written row with no receipt for it at all."""
    await receipts.mint(
        db,
        key=ReceiptKey(
            session_id=ctx.session_id,
            client_kind=ctx.client_kind,
            memory_uuid=uuid,
            version=new_version,
        ),
        at=_now(),
        source=ReceiptSource.OWN_WRITE,
    )
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


async def _amend_within_transaction(
    db: aiosqlite.Connection, *, uuid: str, version: int, rewrite: Rewrite, ctx: CallParams
) -> Memory:
    """`amend`'s work, assuming the caller already holds an open transaction.

    Never commits or rolls back itself, on any path — see `_create_within_transaction`'s
    docstring for the general reason, and `_reject_version_conflict`/`_reject_no_receipt`'s own
    docstrings for why even their rejection paths raise without touching the transaction.
    Invariant 10's rejection carve-out (the audit event, and for a conflict the receipt, survive
    even though the domain mutation does not) is honored by whichever wrapper calls this — via
    `_commit_or_roll_back` — not by this function.
    """
    current = await _authorize_mutation(
        db, named_uuids=(uuid,), version=version, ctx=ctx, verb="amend"
    )
    _require_active(current)
    new_version = current.version + 1
    now = _now()
    await db.execute(
        "UPDATE memory SET gist = ?, content = ?, version = ?, updated_at = ? WHERE uuid = ?",
        (rewrite.gist, rewrite.content, new_version, now, uuid),
    )
    await _bump_version_and_mint_own_write(db, uuid=uuid, new_version=new_version, ctx=ctx)
    return await _require_existing(db, uuid)


async def amend(
    db: aiosqlite.Connection, *, uuid: str, version: int, rewrite: Rewrite, ctx: CallParams
) -> Memory:
    """Full rewrite of `gist`/`content`, bumping `version` (D6, invariant 8).

    Runs the shared authorization rungs, then this verb's own state-legality rung — `amend`
    rejects a row already `active=0` as `inactive_row`, naming its current `state` — then
    mutates in one transaction with the version bump and the receipt revocation/mint.

    Does not emit an `amend` event: see this package's own docstring. M4 wraps this function with
    the chunking preflight and emits the composed event once real size fields exist.

    A `version_conflict` or `no_read_receipt` rejection commits its own receipt and event
    (invariant 10's carve-out for a rejected call) — see `_reject_version_conflict` and
    `_reject_no_receipt`, and `_commit_or_roll_back`, which is what actually decides that here,
    in this wrapper rather than in the neutral core. A `not_found` or `inactive_row` rejection
    has written nothing yet at the point it raises, so it rolls back cleanly with nothing to
    preserve.

    Opens and commits its own transaction. Call `_amend_within_transaction` directly instead if
    composing this into a wider transaction a caller (M4) already owns — see `create`'s docstring
    for why calling this function itself from inside one would fail.

    Raises:
        ZikaronError: `NOT_FOUND` if `uuid` names no row; `VERSION_CONFLICT` if `version` is
            not the row's current one (mints a `conflict` receipt and logs the event before
            raising); `NO_READ_RECEIPT` if the caller holds no matching receipt (logs the event
            before raising); `INACTIVE_ROW` if the row is already `active=0`.
    """
    await db.execute("BEGIN")
    error: BaseException | None = None
    try:
        amended = await _amend_within_transaction(
            db, uuid=uuid, version=version, rewrite=rewrite, ctx=ctx
        )
    except BaseException as caught:
        error = caught
        raise
    finally:
        await _commit_or_roll_back(db, error)
    return amended


async def _retire_within_transaction(
    db: aiosqlite.Connection,
    *,
    uuid: str,
    version: int,
    superseded_by: str | None,
    ctx: CallParams,
) -> Memory:
    """`retire`'s work, assuming the caller already holds an open transaction.

    Never commits or rolls back itself, on any path — see `_amend_within_transaction`'s
    docstring, which states the same contract for the same reason.
    """
    named_uuids = (uuid,) if superseded_by is None else (uuid, superseded_by)
    current = await _authorize_mutation(
        db, named_uuids=named_uuids, version=version, ctx=ctx, verb="retire"
    )
    _require_active(current)
    if superseded_by is not None:
        await supersession.validate_new_edge(
            db, from_uuid=uuid, to_uuid=superseded_by, max_depth=ctx.max_depth
        )
    new_version = current.version + 1
    now = _now()
    await db.execute(
        "UPDATE memory SET active = 0, superseded_by = ?, version = ?, updated_at = ? "
        "WHERE uuid = ?",
        (superseded_by, new_version, now, uuid),
    )
    await _bump_version_and_mint_own_write(db, uuid=uuid, new_version=new_version, ctx=ctx)
    await _log_event(
        db,
        ctx=ctx,
        kind=EventKind.RETIRE,
        memory_uuid=uuid,
        detail={
            "from_version": current.version,
            "to_version": new_version,
            "superseded_by": superseded_by,
        },
    )
    return await _require_existing(db, uuid)


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

    Emits `retire`'s event — the one M3-owned mutation kind, since its `detail` names no
    chunking-derived field (`from_version`, `to_version`, `superseded_by`, none of which need a
    tokenizer or an index).

    Opens and commits its own transaction. Call `_retire_within_transaction` directly instead if
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
        retired = await _retire_within_transaction(
            db, uuid=uuid, version=version, superseded_by=superseded_by, ctx=ctx
        )
    except BaseException as caught:
        error = caught
        raise
    finally:
        await _commit_or_roll_back(db, error)
    return retired
