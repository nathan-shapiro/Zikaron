"""`remember` / `amend` / `retire`: the three primary-agent write verbs.

Each opens exactly one transaction (invariant 2) by composing a lower layer's own
transaction-owning entry point — `indexing.writes.remember`/`amend` for the two indexed verbs,
`records.memory.retire` for the one
that touches no index. None of the three is reimplemented here; this module supplies the one thing
none of those layers has: D15's dedup search for `remember`, and a typed `Conflict` outcome for
`amend`/`retire` in place of the raised exception.

**Why a conflict is a return value here and not a caught exception re-raised.** `ZikaronError`
stays the row-level layers' own signal — `records.memory` and `indexing.writes` raise it, and
`architecture.md`'s ladder is what decides which code — but the tool surface states
`zikaron_memory_amend`/`zikaron_memory_retire`'s response as a **two-shape return**
(`{uuid, version}` or `{conflict: true, current: ...}`), not as a side-channel error a transport
has to catch specifically to keep responding 200. So this layer catches exactly `VERSION_CONFLICT`
at its own boundary and returns the typed `Conflict` value instead; every other `ZikaronError` —
`NOT_FOUND`, `NO_READ_RECEIPT`, `INACTIVE_ROW`, `BAD_SUPERSESSION`, `BOUNDS`, `STORE_BUSY`,
`INDEX_FAILED` — propagates unchanged, because the tool surface gives none of those a second
response shape to translate into. Serializing `Conflict` to the literal wire object
`{conflict: true, current: ...}` is left to whichever transport calls this layer: the Python
union `Amended | Conflict` (`AmendOutcome`) already carries the fact a caller needs —
`isinstance(outcome, Conflict)` — and a boolean field repeating it on the type itself would add no
information the type does not already convey.
"""

from dataclasses import dataclass
from typing import Final

import aiosqlite

from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.indexing import writes
from zikaron.core.indexing.writes import IndexedCall, IndexingContext
from zikaron.core.records import memory
from zikaron.core.records.memory import CallParams, ConflictRecord, Rewrite
from zikaron.core.retrieval.retrieve import RetrievalSettings
from zikaron.core.store import transactions
from zikaron.core.store.transactions import Work
from zikaron.core.write import dedup
from zikaron.core.write.dedup import DedupPolicy, NearDuplicate

#: `schema.md` §Configuration keys: `dedup_threshold` ranges `[0, 1]` and `dedup_max` ranges
#: `0`-`20`. Bundled here rather than threaded as two loose parameters because every call to
#: `remember` needs both together and neither varies independently of the other's own key.
_DEDUP_THRESHOLD_MIN: Final = 0.0
_DEDUP_THRESHOLD_MAX: Final = 1.0
_DEDUP_MAX_MIN: Final = 0
_DEDUP_MAX_MAX: Final = 20


@dataclass(frozen=True, slots=True)
class WriteCall:
    """Everything one call to a write verb holds constant: identity, the index, and dedup policy.

    The same bundling `IndexedCall`/`ReadCall` use and for the same reason — every entry point here
    needs all four, none changes partway through a call, and keeping dedup's two config values
    loose would invite a call site that read `dedup_max` from one config snapshot and
    `dedup_threshold` from another.

    Raises:
        ValueError: `dedup_threshold` outside `[0, 1]` or `dedup_max` outside `0`-`20` — `schema.md`
            §"Configuration keys"' own ranges, checked here because this type is the one place both
            values are read together and a caller passing either straight from an untrusted source
            would otherwise reach `dedup.offer` unchecked.
    """

    ctx: CallParams
    index: IndexingContext
    retrieval: RetrievalSettings
    dedup_threshold: float
    dedup_max: int

    def __post_init__(self) -> None:
        if not _DEDUP_THRESHOLD_MIN <= self.dedup_threshold <= _DEDUP_THRESHOLD_MAX:
            raise ValueError(
                f"dedup_threshold={self.dedup_threshold} outside "
                f"[{_DEDUP_THRESHOLD_MIN}, {_DEDUP_THRESHOLD_MAX}]"
            )
        if not _DEDUP_MAX_MIN <= self.dedup_max <= _DEDUP_MAX_MAX:
            raise ValueError(
                f"dedup_max={self.dedup_max} outside {_DEDUP_MAX_MIN}-{_DEDUP_MAX_MAX}"
            )

    @property
    def indexed(self) -> IndexedCall:
        """This call as the two indexed verbs (`remember`/`amend`) need it — identity and index,
        with no dedup policy attached, since neither of those layers knows dedup exists."""
        return IndexedCall(ctx=self.ctx, index=self.index)

    @property
    def dedup_policy(self) -> DedupPolicy:
        """This call's two dedup numbers as `write.dedup.offer` takes them, already validated by
        `__post_init__` above rather than re-checked by `DedupPolicy` itself."""
        return DedupPolicy(dedup_threshold=self.dedup_threshold, dedup_max=self.dedup_max)


@dataclass(frozen=True, slots=True)
class Remembered:
    """`zikaron_memory_remember`'s success shape: `architecture.md`'s `{uuid, version,
    near_duplicates}` exactly. There is no conflict shape — a row that did not exist a moment
    ago cannot lose a race to overwrite itself."""

    uuid: str
    version: int
    near_duplicates: tuple[NearDuplicate, ...]


#: `zikaron_memory_remember` always succeeds once past `bounds`/`index_failed`/`store_busy` — a
#: fresh row has no version to conflict on — so this alias exists only for symmetry with the other
#: two verbs' outcome names, and to give a transport one family of return types to match across all
#: three tools rather than a special case for the one verb with no second shape.
type RememberOutcome = Remembered


@dataclass(frozen=True, slots=True)
class Amended:
    """`zikaron_memory_amend`'s success shape: `{uuid, version}`."""

    uuid: str
    version: int


@dataclass(frozen=True, slots=True)
class Conflict:
    """The shared failure shape both `zikaron_memory_amend` and `zikaron_memory_retire` can return:
    `{conflict: true, current: CONFLICT_RECORD}`. One row, never a list — the tool surface's own
    statement that the primary-agent verbs' conflict shape is singular, unlike the four
    consolidator verbs, which can name several rows in one call and so return a list.
    """

    current: ConflictRecord


#: `Amended | Conflict`: `zikaron_memory_amend`'s two response shapes, as one return type a caller
#: pattern-matches rather than a boolean flag plus an optional field either shape would leave
#: sometimes-meaningless.
type AmendOutcome = Amended | Conflict


@dataclass(frozen=True, slots=True)
class Retired:
    """`zikaron_memory_retire`'s success shape: `{uuid, version}` — identical in shape to
    `Amended`, and a separate type anyway, because the two verbs are not interchangeable at any
    call site that matches on the outcome's own type rather than its fields."""

    uuid: str
    version: int


#: `Retired | Conflict`: `zikaron_memory_retire`'s two response shapes, sharing `Conflict` with
#: `amend` because `architecture.md` states one payload shape for both verbs' rejection.
type RetireOutcome = Retired | Conflict


def _to_conflict(error: ZikaronError) -> Conflict:
    """A caught `version_conflict`'s payload, as the tool surface's own `Conflict` shape.

    `records.memory`'s ladder already built the exact `ConflictRecord` `architecture.md` names —
    `current` on a `version_conflict` payload is that one object for a single-row primary-agent
    verb — so this is a type-narrowing read of `error.data`, not a second construction of it.

    Raises:
        TypeError: `error.data["current"]` is not a `ConflictRecord` — unreachable through
            `records.memory`'s own raise site, which is exactly why this is a real `raise` rather
            than a bare `assert`: an assertion can be compiled away, and this check exists to catch
            that raise site changing what it produces, not to document an assumption.
    """
    current = error.data["current"]
    if not isinstance(current, ConflictRecord):
        raise TypeError(f"version_conflict.current was {type(current)!r}, not ConflictRecord")
    return Conflict(current=current)


async def remember(db: aiosqlite.Connection, *, rewrite: Rewrite, call: WriteCall) -> Remembered:
    """Write a new memory, then run D15's dedup search over what was just written.

    One transaction: `indexing.writes.remember_within_transaction` (the row, both indexes, the
    own-write receipt, the `remember` event) followed by `write.dedup.offer` — which is why the
    dedup search runs `indexing.writes`'s neutral core directly rather than calling its
    transaction-owning `remember`, exactly as `indexing.writes` itself composes `records.memory`'s
    neutral cores for the same reason. The chunking preflight and the embedding still run outside
    the transaction, in `indexing.writes.prepare`, for the reason that module's own docstring gives.

    Raises:
        ZikaronError: `BOUNDS` if the gist or content is empty or the gist exceeds
            `gist_max_tokens`, refused before anything is written; `INDEX_FAILED` naming the stage,
            or `STORE_BUSY` under contention, either of which leaves nothing behind.
    """
    prepared = await writes.prepare(rewrite, index=call.index)

    async def work(connection: aiosqlite.Connection) -> Remembered:
        written = await writes.remember_within_transaction(
            connection, prepared=prepared, call=call.indexed
        )
        near_duplicates = await dedup.offer(
            connection,
            created_uuid=written.memory.uuid,
            ctx=call.ctx,
            settings=call.retrieval,
            policy=call.dedup_policy,
        )
        return Remembered(
            uuid=written.memory.uuid,
            version=written.memory.version,
            near_duplicates=near_duplicates,
        )

    return await _in_one_transaction(db, work, verb="remember")


async def amend(
    db: aiosqlite.Connection, *, uuid: str, version: int, rewrite: Rewrite, call: WriteCall
) -> AmendOutcome:
    """Full rewrite of an existing memory, or the current record if `version` has moved on.

    Delegates the entire ladder and the atomic reindex to `indexing.writes.amend` — this function
    adds nothing to *how* the write happens, only to *what is returned* when it does not.

    Raises:
        ZikaronError: `BOUNDS`, `NOT_FOUND`, `NO_READ_RECEIPT`, `INACTIVE_ROW`, `INDEX_FAILED`, or
            `STORE_BUSY` — every rejection except `VERSION_CONFLICT`, which this function catches
            and returns as `Conflict` instead of raising, per the tool surface's own two-shape
            contract.
    """
    try:
        written = await writes.amend(
            db, uuid=uuid, version=version, rewrite=rewrite, call=call.indexed
        )
    except ZikaronError as error:
        if error.code is ErrorCode.VERSION_CONFLICT:
            return _to_conflict(error)
        raise
    return Amended(uuid=written.memory.uuid, version=written.memory.version)


async def retire(
    db: aiosqlite.Connection,
    *,
    uuid: str,
    version: int,
    superseded_by: str | None,
    call: WriteCall,
) -> RetireOutcome:
    """Soft-retire a memory, or the current record if `version` has moved on.

    Delegates entirely to `records.memory.retire` — `retire` touches no indexed column
    (`indexing.writes`'s own docstring: "two verbs, not three"), so there is no chunking layer for
    this verb to compose through at all.

    Raises:
        ZikaronError: `NOT_FOUND` (`uuid` or `superseded_by`), `NO_READ_RECEIPT`, `INACTIVE_ROW`,
            `BAD_SUPERSESSION`, or `STORE_BUSY` — every rejection except `VERSION_CONFLICT`, caught
            and returned as `Conflict` for the same reason `amend` catches it.
    """
    try:
        retired = await memory.retire(
            db, uuid=uuid, version=version, superseded_by=superseded_by, ctx=call.ctx
        )
    except ZikaronError as error:
        if error.code is ErrorCode.VERSION_CONFLICT:
            return _to_conflict(error)
        raise
    return Retired(uuid=retired.uuid, version=retired.version)


async def _in_one_transaction(
    db: aiosqlite.Connection, work: Work[Remembered], *, verb: str
) -> Remembered:
    """Run `work` inside one transaction, naming a driver failure exactly as `indexing.writes`
    would for the same kind of work.

    Not a call into that module's own `_in_one_transaction`, which is private on purpose — its
    docstring states that *how a driver failure is named* is `indexing.writes`'s own decision, not
    a shared utility. This function is a second, deliberate instance of the identical decision for
    the identical reason: the work inside this transaction is `indexing.writes`'s own
    `remember_within_transaction` plus `write.dedup.offer`, which touches only rows, receipts and
    events already covered by that reasoning, and nothing this layer adds — the dedup search — is a
    write at all. `architecture.md` §Errors fixes the contract itself: a write names contention
    `store_busy` and everything else `index_failed`, since a read performs no index maintenance and
    so has no `index_failed` to report, and this transaction is a write.
    """
    return await transactions.in_one_transaction(db, work, failure=_failure_map(verb))


def _failure_map(verb: str) -> transactions.FailureMap:
    return lambda error: (
        ZikaronError(ErrorCode.STORE_BUSY, verb=verb)
        if transactions.is_contention(error)
        else ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.INDEX_WRITE)
    )
