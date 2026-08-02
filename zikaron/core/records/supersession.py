"""The supersession graph's write-time checks: invariant 6.

The graph is a rooted converging forest — out-degree ≤ 1, in-degree unbounded, acyclic — and
`schema.md` states three preconditions checked *at the moment an edge is created*, inside the
same transaction as the write: no self-edge, no cycle, and the target not already retired-outright
at that instant. Two of those three are permanent properties once the edge exists (a self-edge and
a cycle can never appear later, since edges are immutable); the third is a precondition only — the
target becoming retired-outright *afterwards* is new information, not a false claim, so nothing
here re-checks it once the edge is written.
"""

from dataclasses import dataclass
from enum import StrEnum

import aiosqlite

from zikaron.core.errors import ErrorCode, ZikaronError


class BadSupersessionReason(StrEnum):
    """Why `retire`'s `superseded_by` was refused, for the `bad_supersession` payload's `reason`.

    `architecture.md` §Errors names the four cases as prose ("self-edge, cycle, target retired-
    outright, edge already set, or depth cap hit") rather than a stated closed set, so this
    enumeration is this module's own decision about how to discriminate them, not a transcription
    of a design table — unlike `BadMergeTargetReason`, which the design table itself constrains.

    `ALREADY_SUPERSEDED` — "edge already set" — is a member with no raise site in this
    milestone's code: `superseded_by` is immutable once written (invariant 6's third rule), and
    the only row that could attempt a second edge is one already `active=0`, which the primary-
    verb ladder's state-legality rung (`architecture.md` §"Validation precedence") catches as
    `inactive_row` before any supersession check runs at all. It is declared anyway so this
    enumeration matches the design's own five-case list exactly, rather than only the subset this
    milestone's call sites happen to reach.
    """

    SELF_EDGE = "self_edge"
    CYCLE = "cycle"
    TARGET_RETIRED_OUTRIGHT = "target_retired_outright"
    ALREADY_SUPERSEDED = "already_superseded"
    DEPTH_CAP_HIT = "depth_cap_hit"


@dataclass(frozen=True, slots=True)
class _TargetRow:
    uuid: str
    active: bool
    superseded_by: str | None


async def _load_target(db: aiosqlite.Connection, uuid: str) -> _TargetRow | None:
    rows = await db.execute_fetchall(
        "SELECT uuid, active, superseded_by FROM memory WHERE uuid = ?", (uuid,)
    )
    found = list(rows)
    if not found:
        return None
    (found_uuid, active, superseded_by) = found[0]
    return _TargetRow(uuid=str(found_uuid), active=bool(active), superseded_by=superseded_by)


async def _walk_would_cycle(
    db: aiosqlite.Connection, *, from_uuid: str, to_uuid: str, max_depth: int
) -> bool:
    """Whether writing `from_uuid -> to_uuid` would close a cycle, walking `to_uuid`'s own chain.

    `schema.md`: "Before writing A→B, walk B's chain; if it reaches A, reject." The walk is
    capped at `max_depth`, and reaching the cap without resolving is itself an error — a corrupt
    store must not hang a query — reported by the caller via `DEPTH_CAP_HIT`, distinct from an
    actual cycle so an operator is told which one happened.

    Raises:
        ZikaronError: `BAD_SUPERSESSION` with `reason=DEPTH_CAP_HIT` if the walk exhausts
            `max_depth` steps without reaching either `from_uuid` or a row with no successor.
    """
    current = to_uuid
    for _ in range(max_depth):
        if current == from_uuid:
            return True
        row = await _load_target(db, current)
        # The target's own existence was already checked before this walk runs; a superseded_by
        # pointing at a since-deleted row would violate the FK `ON DELETE RESTRICT` this table
        # declares, so `row` being `None` here would mean the store's own foreign key failed to
        # hold — not a case this walk needs to model as reachable.
        if row is None or row.superseded_by is None:
            return False
        current = row.superseded_by
    raise ZikaronError(
        ErrorCode.BAD_SUPERSESSION,
        uuid=from_uuid,
        target=to_uuid,
        reason=BadSupersessionReason.DEPTH_CAP_HIT,
    )


async def validate_new_edge(
    db: aiosqlite.Connection, *, from_uuid: str, to_uuid: str, max_depth: int
) -> None:
    """Check every write-time *legality* precondition for a new `from_uuid.superseded_by = to_uuid`
    edge — rung 5 of the ladder. Existence of `to_uuid` is rung 2 and must already have been
    checked before this runs (`memory.py`'s `_authorize_mutation` takes `to_uuid` as one of its
    `other_named_uuids` and checks it there, ahead of `from_uuid`'s own version and receipt);
    this function re-loads the row anyway, because the legality checks need its
    `active`/`superseded_by` values and a second `SELECT` inside one transaction is cheaper than
    threading the row through as a parameter that would then let the two functions' read of it
    silently diverge if one caller skipped the first.

    Runs inside the caller's own transaction, before the `UPDATE` that actually writes the edge —
    `schema.md` requires the checks and the write to share one transaction, and this function
    only reads, so the caller commits both once this returns without raising.

    Args:
        from_uuid: the row being retired — `retire`'s `uuid`.
        to_uuid: the replacement — `retire`'s `superseded_by`. Assumed to already exist.
        max_depth: `supersession_max_depth`, the cycle walk's cap.

    Raises:
        ZikaronError: `BAD_SUPERSESSION`, `reason` naming which precondition failed —
            `SELF_EDGE` (`from_uuid == to_uuid`), `TARGET_RETIRED_OUTRIGHT` (`to_uuid` is already
            `active=0 AND superseded_by IS NULL` at this instant), or `CYCLE` (writing the edge
            would close one).
    """
    if from_uuid == to_uuid:
        raise ZikaronError(
            ErrorCode.BAD_SUPERSESSION,
            uuid=from_uuid,
            target=to_uuid,
            reason=BadSupersessionReason.SELF_EDGE,
        )
    target = await _load_target(db, to_uuid)
    if target is None:
        # The ladder's own existence rung runs strictly before this legality rung and is the
        # actual guarantee that `target` is not `None` here; a caller that skipped it is the
        # real bug. Raising `NOT_FOUND` anyway — rather than assuming a non-`None` result and
        # letting a caller's own mistake surface as an `AttributeError` three lines down — keeps
        # a skipped-rung bug loud and Zikaron-shaped either way.
        raise ZikaronError(ErrorCode.NOT_FOUND, uuid=to_uuid)
    if not target.active and target.superseded_by is None:
        raise ZikaronError(
            ErrorCode.BAD_SUPERSESSION,
            uuid=from_uuid,
            target=to_uuid,
            reason=BadSupersessionReason.TARGET_RETIRED_OUTRIGHT,
        )
    if await _walk_would_cycle(db, from_uuid=from_uuid, to_uuid=to_uuid, max_depth=max_depth):
        raise ZikaronError(
            ErrorCode.BAD_SUPERSESSION,
            uuid=from_uuid,
            target=to_uuid,
            reason=BadSupersessionReason.CYCLE,
        )


class RootState(StrEnum):
    """A supersession chain's root, as `fetch` reports it in `superseded_by_latest_state`.

    Only two of `RowState`'s three members are reachable here: the walk always terminates at a
    root — a row with `superseded_by IS NULL` — and a root is by definition either live
    (`active=1`) or a terminal component (`active=0 AND superseded_by IS NULL`, invariant 6's own
    "a root is live or terminal, and both are legal"). `superseded` describes a *non*-root node,
    so it can never be the state a walk to the root reports.
    """

    LIVE = "live"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class ResolvedHead:
    """The result of walking a chain to its root: invariant 7's `superseded_by_latest` pair."""

    uuid: str
    state: RootState


async def resolve_latest(
    db: aiosqlite.Connection, *, start_uuid: str, max_depth: int
) -> ResolvedHead | None:
    """Walk `start_uuid.superseded_by` to the component root, and report the root's own state.

    Invariant 7: "the component root, reached by walking `superseded_by` to a row with
    `superseded_by IS NULL`, capped as above." The walk is unambiguous because out-degree is
    ≤ 1, which is the property that makes "latest" well defined even though in-degree is not
    bounded.

    Returns:
        `None` if `start_uuid` is itself a root (`superseded_by IS NULL`) — `fetch` and the
        conflict payload only populate `superseded_by_latest` when `superseded_by` itself is
        non-null, so a caller of *this* function is expected to check that first rather than
        have it silently return the start row as its own "latest".
        Otherwise the root's uuid and whether that root is `live` or `retired`.

    Raises:
        ZikaronError: `BAD_SUPERSESSION` with `reason=DEPTH_CAP_HIT` if the walk exceeds
            `max_depth` steps — the same cap and the same failure shape as write-time cycle
            detection, since an unbounded walk on a read path is exactly the hang invariant 6's
            cap exists to prevent, and a corrupt graph is no less corrupt for being read rather
            than written.
    """
    start = await _load_target(db, start_uuid)
    if start is None or start.superseded_by is None:
        return None
    current = start.superseded_by
    for _ in range(max_depth):
        row = await _load_target(db, current)
        if row is None:
            # `superseded_by`'s own FK is `ON DELETE RESTRICT`, so a row this walk is currently
            # standing on cannot have vanished between being pointed at and being read — nothing
            # in this milestone can construct a store where this branch fires without deleting a
            # row out from under a live foreign key, which SQLite itself refuses to allow.
            return None
        if row.superseded_by is None:
            state = RootState.LIVE if row.active else RootState.RETIRED
            return ResolvedHead(uuid=row.uuid, state=state)
        current = row.superseded_by
    raise ZikaronError(
        ErrorCode.BAD_SUPERSESSION,
        uuid=start_uuid,
        target=current,
        reason=BadSupersessionReason.DEPTH_CAP_HIT,
    )
