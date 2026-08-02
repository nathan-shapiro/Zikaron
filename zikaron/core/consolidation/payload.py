"""The shapes `zikaron_next_group` returns, as three types a caller pattern-matches on.

`architecture.md` §"Consolidator tool surface" is normative for every field here. These are `core`'s
values, not wire objects: the literal `{done: true}` and `{busy: true}` booleans belong to whichever
transport serializes them, because `isinstance(outcome, RunDone)` already *is* that fact at the
Python level and a boolean field repeating it would carry no information the type does not.

Kept apart from the serve loop because the two change for different reasons — a payload field moves
when the tool surface does, while the loop moves when the lifecycle does — and because the ladder
that authorizes the write verbs needs the record shape without needing the loop.
"""

from dataclasses import dataclass

from zikaron.core.consolidation.groups import Shard
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.records.memory import ConflictRecord, Memory, Rewrite


@dataclass(frozen=True, slots=True)
class GroupRecord:
    """One row a serve delivers: `architecture.md`'s `{uuid, expected_version, gist, content,
    created_at}` exactly, for a member, the anchor and a candidate alike.

    `expected_version` is the version whose prose is in **this** payload, re-read at serve time —
    not the version at plan time. The two are different fields for a reason: `version_seen` is
    change detection, while this is the version the receipt was minted at, and delivering current
    prose under a stale version would break D26 while delivering historical prose is impossible,
    since no history is stored.
    """

    uuid: str
    expected_version: int
    gist: str
    content: str
    created_at: str

    @classmethod
    def of(cls, row: Memory) -> "GroupRecord":
        """This row as a payload record, at its current version."""
        return cls(
            uuid=row.uuid,
            expected_version=row.version,
            gist=row.gist,
            content=row.content,
            created_at=row.created_at,
        )


@dataclass(frozen=True, slots=True)
class RankedRecord:
    """One candidate and its rank in `retrieval.md`'s total order.

    The rank is delivered so a run is reproducible from the payload alone, and persisted alongside
    it so the authorization set survives a service restart.
    """

    record: GroupRecord
    rank: int


@dataclass(frozen=True, slots=True)
class ServedGroup:
    """What one delivery hands the consolidator: `zikaron_next_group`'s success shape.

    `anchor` is `None` for an orphan group, and also `None` with `anchor_vacated=True` when a
    planned anchor stopped being targetable before the group was served — two different situations
    that the payload deliberately distinguishes, because the second means "there was a record here
    and it is gone", which is information a model deciding between `merge` and `promote` can use.
    """

    group_id: str
    run_id: str
    anchor: GroupRecord | None
    anchor_vacated: bool
    journal_entries: tuple[GroupRecord, ...]
    candidates: tuple[RankedRecord, ...]
    shard: Shard
    serve_count: int
    n_gists_used: int
    remaining_groups: int


@dataclass(frozen=True, slots=True)
class RunDone:
    """`{done: true}`: this run has nothing left to serve.

    A value rather than `None`, so that "the run is finished" and "something went wrong" cannot be
    the same return. Carries no fields: the run is closed, and every count about it is in its
    `consolidate_run` event.
    """


@dataclass(frozen=True, slots=True)
class Busy:
    """`{busy: true, ...}`: an effectively-active run belongs to a different `(session_id, pid)`.

    A defined, deterministic answer rather than an error and rather than a second plan — the skill
    reports it and stops. `holder_pid` is returned so same-session contention is diagnosable rather
    than silent, which matters now that two consolidators launched from one kiro session share a
    `session_id` *and* a `client_kind`.
    """

    holder_session: str
    holder_pid: int
    expires_at: str


#: `ServedGroup | RunDone | Busy`: `next_group`'s three response shapes as one return type a caller
#: pattern-matches on, rather than three optional fields two of which are always meaningless.
type NextGroupOutcome = ServedGroup | RunDone | Busy


@dataclass(frozen=True, slots=True)
class NamedRow:
    """One `{uuid, expected_version}` pair — how every consolidator verb names a row it touches.

    Targets, absorbed rows and discarded rows alike, never the merge target only. Otherwise a
    primary agent that amends an absorbed journal row after it was planned into a group would have
    its repair silently retired by the consolidator, which is exactly the lost update D26 exists to
    prevent.
    """

    uuid: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class NamedRows:
    """Every row one call names: its `absorb` list, and a merge target where the verb has one.

    Self-validating on the one bound that is independent of store state, which is what makes it rung
    1: **a uuid may appear at most once in `absorb`**. A repeat is malformed on its own terms — the
    list names the rows one call dispositions, so a uuid twice would bump one row's `version` twice
    for one logical action and report an `n_absorbed` that counts it twice. The other half of the
    stated bound, `≤ the group's member count`, needs the store and so is rung 2's, where it follows
    from every element having to be a member of that group. The **minimum** of one row is rung 2's
    `not_in_group` rather than `bounds`, which the error table states directly.

    Raises:
        ZikaronError: `BOUNDS` naming `absorb` if a uuid appears twice.
    """

    absorb: tuple[NamedRow, ...]
    target: NamedRow | None = None

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for row in self.absorb:
            if row.uuid in seen:
                raise ZikaronError(
                    ErrorCode.BOUNDS,
                    field="absorb",
                    limit="each uuid at most once",
                    actual=row.uuid,
                )
            seen.add(row.uuid)

    @property
    def every(self) -> tuple[NamedRow, ...]:
        """Every named row, the target first where there is one.

        One order, used by the existence, version and receipt rungs alike, so that a call naming
        several offending rows reports them in a defined sequence rather than in whichever order a
        dict happened to iterate.
        """
        return (*(() if self.target is None else (self.target,)), *self.absorb)


@dataclass(frozen=True, slots=True)
class MergeTarget:
    """The long-term record a `merge` rewrites: which row, at which version, with what prose.

    One value rather than three parameters, because the three are one instruction — and because the
    row and the prose must not be able to arrive from different places, which is what a call site
    threading `target`, `gist` and `content` separately makes possible.
    """

    row: NamedRow
    rewrite: Rewrite


@dataclass(frozen=True, slots=True)
class GroupConflict:
    """`{conflict: true, current: [...], remaining_uuids: [...]}` — the three verbs' shared
    rejection.

    A **list** of records, unlike the primary-agent verbs' single object: a consolidator call names
    several rows, all versions are validated before anything mutates, and one mismatch returns the
    current record for **every** conflicting uuid so the model can re-decide in one round trip.

    Carries `remaining_uuids` because the caller learns the same remaining state whether its call
    landed or raced. A call rejected by an *error* carries no member list at all — it changed
    nothing, so the list the caller already holds still stands.
    """

    current: tuple[ConflictRecord, ...]
    remaining_uuids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Merged:
    """`zikaron_merge`'s success shape: `{uuid, version, remaining_uuids, group_complete}`."""

    uuid: str
    version: int
    remaining_uuids: tuple[str, ...]
    group_complete: bool


@dataclass(frozen=True, slots=True)
class Promoted:
    """`zikaron_promote`'s success shape — identical in shape to `Merged`, and a separate type.

    Separate for the reason `Amended` and `Retired` are: the two verbs are not interchangeable at
    any call site that matches on the outcome's own type, and a promotion's `uuid` may be a row
    that did not exist before the call while a merge's never is.
    """

    uuid: str
    version: int
    remaining_uuids: tuple[str, ...]
    group_complete: bool


@dataclass(frozen=True, slots=True)
class Discarded:
    """`zikaron_discard`'s success shape: `{retired, remaining_uuids, group_complete}`.

    `retired` is how many member rows this call actually moved, read from the disposition write
    rather than from the length of the argument, so a number the store did not produce cannot be
    reported.
    """

    retired: int
    remaining_uuids: tuple[str, ...]
    group_complete: bool


#: The three verbs' return types. Each is its own success shape or the shared conflict, as a union a
#: caller pattern-matches rather than a boolean flag beside fields that are sometimes meaningless.
type MergeOutcome = Merged | GroupConflict
type PromoteOutcome = Promoted | GroupConflict
type DiscardOutcome = Discarded | GroupConflict
