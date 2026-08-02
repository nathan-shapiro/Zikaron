"""The `consolidation_group` aggregate and its two child tables, plus every state transition.

`schema.md` invariants 16, 17 and 19 are normative, and so is `architecture.md` §"Serving". Every
statement that reads or writes `consolidation_group`, `consolidation_group_member` or
`consolidation_group_candidate` is here, so a schema change reaches one module.

**Group order is `(created_at, uuid)` over the members**, named once in `consolidation.md` step 3
and implemented once here: it is the order members are delivered in, the order `remaining_uuids` is
reported in, the order the gist concatenation concatenates in, and the order shards are cut on.
`created_at` alone is not total — concurrent writes share the string — so the uuid is part of the
order rather than a tiebreak applied wherever a collision was noticed.

**Every status transition is a guarded update returning whether it fired.** That is what makes the
transitions idempotent under a retry and what lets two paths reach the same conclusion in one
transaction without writing it twice: invariant 16 gives `→ complete` **two** producers — the write
verb that dispositions the last member, and the serve transaction when serve-time vacating
dispositions it — so "did I actually close this" has to be an answer rather than an assumption.

**Frozen membership and the served set are different things.** `consolidation_group_member` is the
plan-time universe and stays that way; the served set is the payload view of it — the members with
`disposition IS NULL` after serve-time re-validation — and is never a second source of truth.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import uuid4

import aiosqlite

#: Which statuses mean "this group is still open", i.e. the two invariant 16's closure property is
#: stated over and the two `remaining_groups` counts. `deferred` is terminal for the run and
#: `complete` is terminal outright, so neither is open.
OPEN_STATUSES: Final = ("pending", "served")

_GROUP_COLUMNS: Final = (
    "group_id, run_id, anchor_uuid, order_key, shard_index, shard_count, status, "
    "serve_count, served_at"
)

#: The join and ordering that *is* group order. One constant rather than an `ORDER BY` per
#: statement, because five things are defined over this order and a statement ordering by
#: `created_at` alone would agree with the rest on every fixture with distinct timestamps.
_MEMBER_ORDER: Final = "ORDER BY m.created_at ASC, mem.memory_uuid ASC"
_MEMBER_JOIN: Final = (
    "FROM consolidation_group_member mem "
    "JOIN memory m ON m.uuid = mem.memory_uuid "
    "WHERE mem.group_id = ?"
)


class GroupStatus(StrEnum):
    """`consolidation_group.status`'s four values, exactly as `schema.md`'s `CHECK` states them."""

    PENDING = "pending"
    SERVED = "served"
    COMPLETE = "complete"
    DEFERRED = "deferred"


class Disposition(StrEnum):
    """What became of one member.

    `VACATED` is the one that is not a consolidator decision: the row left `tier='journal' AND
    active=1` by another path between plan and serve — a primary agent retired it, or promoted it —
    so it is not delivered, nothing was lost, and it blocks no completion. It **counts as
    dispositioned**, which is what lets vacating the last open member close the group inside the
    serve transaction rather than leaving it waiting for a write verb with nothing left to write.
    """

    MERGED = "merged"
    PROMOTED = "promoted"
    DISCARDED = "discarded"
    VACATED = "vacated"


class CandidateRole(StrEnum):
    """`consolidation_group_candidate.role`: which of the two kinds of long-term record this is."""

    ANCHOR = "anchor"
    CANDIDATE = "candidate"


@dataclass(frozen=True, slots=True)
class Shard:
    """One group's position among the shards of its pre-shard subgroup, both halves persisted.

    **1-based**, so an unsharded group is `{index: 1, of: 1}` rather than a third convention meaning
    "not sharded". `of` cannot be recomputed at serve time — that would mean replanning a subgroup
    whose membership is frozen, against a store that has since moved because earlier groups mutate
    it — so it is stored and returned verbatim.

    Raises:
        ValueError: `of < 1` or `index` outside `1…of`, the same conditions the table's own per-row
            `CHECK`s state. Held here as well so a malformed shard cannot be constructed at all,
            rather than only failing at the `INSERT`: the planner computes these, and a planner that
            can build an impossible one can also build a set that violates invariant 19.
    """

    index: int
    of: int

    def __post_init__(self) -> None:
        if self.of < 1:
            raise ValueError(f"shard_count must be >= 1, got {self.of}")
        if not 1 <= self.index <= self.of:
            raise ValueError(f"shard_index {self.index} outside 1-{self.of}")


@dataclass(frozen=True, slots=True)
class Group:
    """One `consolidation_group` row, exactly as stored."""

    group_id: str
    run_id: str
    anchor_uuid: str | None
    order_key: str
    shard: Shard
    status: GroupStatus
    serve_count: int
    served_at: str | None


@dataclass(frozen=True, slots=True)
class Member:
    """One `consolidation_group_member` row, exactly as stored, plus its ordering facts.

    `created_at` is the member's own `memory.created_at` rather than a column of this table: group
    order is defined over it, and carrying it here is what lets the order be established by one
    statement instead of by a second lookup per member.

    `version_seen` is the plan-time version and is **change detection only**; `version_served` is
    the version whose prose was actually delivered on the most recent serve that delivered this row,
    and is the `expected_version` the payload carried. `version_served IS NULL` iff the row has
    never been delivered — which is what distinguishes a member that vacated on the serve that would
    have delivered it from one delivered earlier and vacated later.
    """

    memory_uuid: str
    created_at: str
    version_seen: int
    version_served: int | None
    disposition: Disposition | None


@dataclass(frozen=True, slots=True)
class AuthorizedRecord:
    """One row of `consolidation_group_candidate`: a long-term record a `merge` may target.

    This table, not the `group_served` events, is the authority — the events are instrumentation. It
    is rewritten on every serve, in the serve's own transaction, so authorization survives a service
    restart without recomputation.
    """

    memory_uuid: str
    role: CandidateRole
    version_served: int
    rank: int


def new_group_id() -> str:
    """A fresh `group_id`. The one handle this package exposes, and only to the consolidator."""
    return str(uuid4())


def _to_group(row: Sequence[object]) -> Group:
    (
        group_id,
        run_id,
        anchor_uuid,
        order_key,
        shard_index,
        shard_count,
        status,
        serve_count,
        served_at,
    ) = row
    return Group(
        group_id=str(group_id),
        run_id=str(run_id),
        anchor_uuid=None if anchor_uuid is None else str(anchor_uuid),
        order_key=str(order_key),
        shard=Shard(index=int(str(shard_index)), of=int(str(shard_count))),
        status=GroupStatus(str(status)),
        serve_count=int(str(serve_count)),
        served_at=None if served_at is None else str(served_at),
    )


async def load(db: aiosqlite.Connection, group_id: str) -> Group | None:
    """One group by id, or `None` if the store holds no such row."""
    rows = await db.execute_fetchall(
        f"SELECT {_GROUP_COLUMNS} FROM consolidation_group WHERE group_id = ?",  # noqa: S608 — a source-level column list; the id is bound.
        (group_id,),
    )
    found = list(rows)
    return None if not found else _to_group(tuple(found[0]))


async def next_candidate(db: aiosqlite.Connection, run_id: str) -> Group | None:
    """The next group of `run_id` a serve should consider, in the order `architecture.md` fixes.

    The earliest `served`-but-incomplete group by `(order_key, shard_index)` first, and only then
    the earliest `pending` one. Re-serving before advancing is the point: a consolidator must not
    be able to walk past a group it found hard simply by calling again.

    **The two-step ordering is provably equivalent to plain `order_key` ordering on today's state
    machine, and is written as the design states it anyway.** Serving always takes the earliest
    remaining group, and every transition out of the candidate set (`→ complete`, `→ deferred`)
    removes a group rather than returning it to `pending` — so among the groups that are still
    `pending` or `served`, the served ones are always an order-prefix, and the `CASE` cannot change
    which row comes back. That equivalence rests on a reachability argument about the whole state
    machine rather than on anything local, so it is the wrong thing to encode: a future transition
    that reopened a group would silently make skipping possible. Disclosed because it means a
    mutation removing the `CASE` survives the suite, and no fixture can honestly make it fail.

    `order_key` is `'earliest_created_at|min_uuid'` of the pre-shard subgroup, so ordering by it is
    ordering by D29's step-3 total order's first two components, and `shard_index` is the third —
    which is the only reason a third component is needed at all, since every shard of one subgroup
    carries the same key.
    """
    rows = await db.execute_fetchall(
        f"SELECT {_GROUP_COLUMNS} FROM consolidation_group "  # noqa: S608 — a source-level column list; the id is bound.
        "WHERE run_id = ? AND status IN ('served', 'pending') "
        "ORDER BY CASE status WHEN 'served' THEN 0 ELSE 1 END, order_key ASC, shard_index ASC "
        "LIMIT 1",
        (run_id,),
    )
    found = list(rows)
    return None if not found else _to_group(tuple(found[0]))


async def members(db: aiosqlite.Connection, group_id: str) -> tuple[Member, ...]:
    """Every member of one group — the frozen plan-time universe — in group order."""
    rows = await db.execute_fetchall(
        # Every fragment is a source-level constant; the group id is the one bound value.
        "SELECT mem.memory_uuid, m.created_at, mem.version_seen, mem.version_served, "
        f"mem.disposition {_MEMBER_JOIN} {_MEMBER_ORDER}",
        (group_id,),
    )
    return tuple(
        Member(
            memory_uuid=str(memory_uuid),
            created_at=str(created_at),
            version_seen=int(str(version_seen)),
            version_served=None if version_served is None else int(str(version_served)),
            disposition=None if disposition is None else Disposition(str(disposition)),
        )
        for memory_uuid, created_at, version_seen, version_served, disposition in rows
    )


async def open_member_uuids(db: aiosqlite.Connection, group_id: str) -> tuple[str, ...]:
    """`remaining_uuids`: this group's members with `disposition IS NULL`, in group order.

    Read from the member table at response time rather than tracked in memory, because that is
    what the design says it is — and because a write verb dispositions rows inside its own
    transaction, so the value must shrink within one call rather than describe its starting state.
    """
    rows = await db.execute_fetchall(
        # Every fragment is a source-level constant; the group id is the one bound value.
        f"SELECT mem.memory_uuid {_MEMBER_JOIN} AND mem.disposition IS NULL {_MEMBER_ORDER}",
        (group_id,),
    )
    return tuple(str(memory_uuid) for (memory_uuid,) in rows)


async def open_group_count(db: aiosqlite.Connection, run_id: str, *, excluding: str) -> int:
    """`remaining_groups`: how many **other** groups of this run are still `pending` or `served`.

    Excludes the group named, because the payload's own contract counts work *not* in the
    consolidator's hands — the delivered group is still open and still has undispositioned members,
    so counting it would make a final group report 1 and leave "is this the last one" unanswerable
    from the payload.
    """
    rows = await db.execute_fetchall(
        "SELECT count(*) FROM consolidation_group "
        "WHERE run_id = ? AND group_id <> ? AND status IN ('pending', 'served')",
        (run_id, excluding),
    )
    return int(str(next(iter(rows))[0]))


@dataclass(frozen=True, slots=True)
class RunCounts:
    """The three counts a `consolidate_run` event reports about one run.

    A value type rather than three integers threaded through, because the event's own contract says
    they describe **the run the transition is about** — and `plan_groups` emits two events about two
    different runs in one call, which is exactly the situation in which three loose integers get
    crossed. It lives with the group aggregate rather than with the run because all three are
    counted over the two group tables, and this module is the only place their SQL may live.
    """

    n_groups: int
    n_members: int
    n_deferred: int


async def run_counts(db: aiosqlite.Connection, run_id: str) -> RunCounts:
    """One run's group and member totals, and how many of its groups are currently `deferred`.

    `n_groups` and `n_members` are fixed at plan time and so repeat unchanged on every later phase
    of one run; `n_deferred` is the only one that moves. Read in one statement so all three
    describe the same instant, which matters because they are reported together on one event row.
    """
    rows = await db.execute_fetchall(
        """
        SELECT
          (SELECT count(*) FROM consolidation_group WHERE run_id = ?),
          (SELECT count(*) FROM consolidation_group_member m
             JOIN consolidation_group g ON g.group_id = m.group_id
            WHERE g.run_id = ?),
          (SELECT count(*) FROM consolidation_group WHERE run_id = ? AND status = 'deferred')
        """,
        (run_id, run_id, run_id),
    )
    n_groups, n_members, n_deferred = next(iter(rows))
    return RunCounts(
        n_groups=int(str(n_groups)),
        n_members=int(str(n_members)),
        n_deferred=int(str(n_deferred)),
    )


async def has_open_groups(db: aiosqlite.Connection, run_id: str) -> bool:
    """Whether any group of this run is still `pending` or `served`.

    The condition invariant 17 makes the run's `active → complete` cause: "whichever transaction
    first observes that no group of the run is `pending` or `served`". `deferred` groups do not
    count — they are terminal for the run, and their members simply return to the next plan.
    """
    rows = await db.execute_fetchall(
        "SELECT EXISTS (SELECT 1 FROM consolidation_group "
        "WHERE run_id = ? AND status IN ('pending', 'served'))",
        (run_id,),
    )
    return bool(next(iter(rows))[0])


async def insert(db: aiosqlite.Connection, group: Group) -> None:
    """Write one planned group. `status` and `serve_count` come from the value, not from a default,
    so a planner that tried to insert an already-served group would be visible here."""
    await db.execute(
        "INSERT INTO consolidation_group "
        "(group_id, run_id, anchor_uuid, order_key, shard_index, shard_count, status, "
        " serve_count, served_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            group.group_id,
            group.run_id,
            group.anchor_uuid,
            group.order_key,
            group.shard.index,
            group.shard.of,
            group.status.value,
            group.serve_count,
            group.served_at,
        ),
    )


async def insert_member(
    db: aiosqlite.Connection, *, group_id: str, memory_uuid: str, version_seen: int
) -> None:
    """Write one planned member: undispositioned, never delivered, at its plan-time version."""
    await db.execute(
        "INSERT INTO consolidation_group_member "
        "(group_id, memory_uuid, version_seen, version_served, disposition, disposed_at) "
        "VALUES (?, ?, ?, NULL, NULL, NULL)",
        (group_id, memory_uuid, version_seen),
    )


async def set_status(
    db: aiosqlite.Connection, *, group_id: str, status: GroupStatus, expected: GroupStatus
) -> bool:
    """Move one group from `expected` to `status`, and report whether it moved.

    Guarded on the *source* status rather than only on the id, because every transition in
    invariant 17's table names one, and a guard on the id alone would let a group another path had
    already closed be reopened as `deferred` — which is exactly the "no reachable state left
    without an exit" property the table is asserting.
    """
    cursor = await db.execute(
        "UPDATE consolidation_group SET status = ? WHERE group_id = ? AND status = ?",
        (status.value, group_id, expected.value),
    )
    return cursor.rowcount > 0


async def record_delivery(
    db: aiosqlite.Connection, *, group_id: str, serve_count: int, served_at: str
) -> None:
    """Set this group to `served` at the given delivery count and timestamp.

    One statement for both transitions invariant 17 gives a delivery — `pending → served` setting
    `serve_count = 1`, and `served → served` incrementing it — because the counter is what
    distinguishes them and the caller has already computed it. `served_at` is refreshed on **every**
    delivery, so it records the most recent one rather than the first.
    """
    await db.execute(
        "UPDATE consolidation_group SET status = ?, serve_count = ?, served_at = ? "
        "WHERE group_id = ?",
        (GroupStatus.SERVED.value, serve_count, served_at, group_id),
    )


async def disposition_members(
    db: aiosqlite.Connection,
    *,
    group_id: str,
    memory_uuids: Sequence[str],
    disposition: Disposition,
    at: str,
) -> int:
    """Mark the named members with `disposition`, and report how many rows actually moved.

    Guarded on `disposition IS NULL`, so a member some other path already dispositioned cannot be
    overwritten — a `vacated` row must not silently become `merged` — and the returned count is what
    a caller checks that against. `discard`'s `{retired: n}` is this number.

    **The guard is unobservable through any call, and that is disclosed rather than tested.** Rung 2
    already refuses an `absorb` uuid that is not an *undispositioned* member, and the serve computes
    the vacating set from the same predicate, so no reachable caller reaches this statement with an
    already-dispositioned uuid. It stays because it is one clause and because the rule it enforces
    is the design's, not this function's: an implementation that later relaxed rung 2 would find the
    disposition still protected. Removing it changes no test's outcome, which is exactly the claim
    being made here rather than one a test could make.
    """
    if not memory_uuids:
        return 0
    placeholders = ", ".join("?" for _ in memory_uuids)
    sql = (
        "UPDATE consolidation_group_member SET disposition = ?, disposed_at = ? "  # noqa: S608 — placeholders only; every uuid is a bound parameter.
        f"WHERE group_id = ? AND memory_uuid IN ({placeholders}) AND disposition IS NULL"
    )
    cursor = await db.execute(sql, (disposition.value, at, group_id, *memory_uuids))
    return cursor.rowcount


async def record_versions_served(
    db: aiosqlite.Connection, *, group_id: str, versions: Mapping[str, int]
) -> None:
    """Record, per member, the version whose prose this serve is delivering.

    Written for exactly the served set, because that is the set whose prose the payload carries and
    whose receipts are minted at these versions. A member the same serve marked `vacated` delivered
    nothing, so its `version_served` is deliberately left as it was — null if it had never been
    delivered, and its earlier value if it had.
    """
    for memory_uuid, version in versions.items():
        await db.execute(
            "UPDATE consolidation_group_member SET version_served = ? "
            "WHERE group_id = ? AND memory_uuid = ?",
            (version, group_id, memory_uuid),
        )


async def replace_authorization(
    db: aiosqlite.Connection, *, group_id: str, records: Sequence[AuthorizedRecord]
) -> None:
    """Rewrite this group's merge authorization set, replacing any previous serve's rows.

    Deleted and reinserted rather than merged, because the set is recomputed from scratch on every
    serve against a store that has moved: a record that no longer ranks, or an anchor that stopped
    being targetable, must stop being authorized. Leaving a stale row behind would authorize a merge
    into a record this serve did not show.
    """
    await db.execute("DELETE FROM consolidation_group_candidate WHERE group_id = ?", (group_id,))
    for record in records:
        await db.execute(
            "INSERT INTO consolidation_group_candidate "
            "(group_id, memory_uuid, role, version_served, rank) VALUES (?, ?, ?, ?, ?)",
            (group_id, record.memory_uuid, record.role.value, record.version_served, record.rank),
        )


async def authorized_uuids(db: aiosqlite.Connection, group_id: str) -> frozenset[str]:
    """Every uuid this group's most recent serve authorized a `merge` to target.

    A set rather than the rows, because that is the whole question rung 2 asks — and the answer must
    carry nothing else: `bad_merge_target`'s payload names a uuid and a reason that does not
    distinguish "does not exist" from "not authorized", so the check cannot become an existence
    oracle for the store.
    """
    rows = await db.execute_fetchall(
        "SELECT memory_uuid FROM consolidation_group_candidate WHERE group_id = ?", (group_id,)
    )
    return frozenset(str(memory_uuid) for (memory_uuid,) in rows)
