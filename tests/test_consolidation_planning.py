"""`plan_groups` and the run lifecycle: `zikaron.core.consolidation.planning`, `.runs`.

Default tier, unmarked: a real store, because every claim here is about rows in `consolidation_run`
and `consolidation_group` and about which `consolidate_run` events committed beside them.
"""

import unittest.mock
from pathlib import Path

import aiosqlite
import pytest

from tests.consolidation_fixtures import (
    AGENT_SESSION,
    CONSOLIDATOR_PID,
    CONSOLIDATOR_SESSION,
    consolidator,
    detail_of,
)
from zikaron.core.consolidation import grouping, planning, runs, serving, verbs
from zikaron.core.consolidation.context import RunOwner
from zikaron.core.consolidation.groups import GroupStatus
from zikaron.core.consolidation.payload import Busy, GroupRecord, NamedRow, ServedGroup
from zikaron.core.consolidation.runs import RunStatus, lease_expiry
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.records import receipts
from zikaron.core.records.memory import Tier

_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_B = ("proto codegen also fails locally", "the same drift shows up in the dev container")


def _named(record: GroupRecord) -> NamedRow:
    """One payload record as the `{uuid, expected_version}` pair a verb takes.

    Taken from the payload rather than invented, which is the point: the serve is what mints the
    receipt, so a version a test made up would be testing a call no consolidator could make.
    """
    return NamedRow(uuid=record.uuid, expected_version=record.expected_version)


def test_the_lease_is_exactly_run_lease_past_started_at() -> None:
    """Derived from the stored `started_at` rather than from a second clock read, so the difference
    is exact rather than approximate — which is what lets this be an equality."""
    assert lease_expiry("2026-08-02T09:00:00+00:00", seconds=1800) == "2026-08-02T09:30:00+00:00"


def test_a_lapsed_lease_is_expired_for_every_caller_including_its_owner() -> None:
    """Effective activity is the only run test anywhere in the design, and a stored `'active'` row
    past its lease constrains nobody. Asserted on the value type, because that is where every reader
    gets its answer from — the alternative was a stored transition on a rejection path."""
    run = runs.Run(
        run_id="r",
        owner=RunOwner(session_id="s", pid=1),
        started_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-01T00:30:00+00:00",
        status=RunStatus.ACTIVE,
    )
    assert run.is_effectively_active(at="2026-01-01T00:29:59+00:00")
    assert not run.is_effectively_active(at="2026-01-01T00:30:01+00:00")
    assert run.effective_status(at="2026-01-01T00:30:01+00:00") is RunStatus.EXPIRED
    assert run.effective_status(at="2026-01-01T00:00:01+00:00") is RunStatus.ACTIVE


def test_the_lease_boundary_is_inclusive() -> None:
    """`expires_at ≥ now` is active; expiry is `expires_at < now`. The boundary is stated so a
    one-second difference cannot decide it by accident."""
    run = runs.Run(
        run_id="r",
        owner=RunOwner(session_id="s", pid=1),
        started_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-01T00:30:00+00:00",
        status=RunStatus.ACTIVE,
    )
    assert run.is_effectively_active(at="2026-01-01T00:30:00+00:00")


def test_an_owner_is_the_pair_not_the_session() -> None:
    """Two consolidators launched from one kiro session share a `session_id` *and* a `client_kind`,
    so the pid is what distinguishes them — and value equality is what makes that one comparison."""
    assert RunOwner(session_id="s", pid=1) != RunOwner(session_id="s", pid=2)
    assert RunOwner(session_id="s", pid=1) == RunOwner(session_id="s", pid=1)


@pytest.mark.parametrize(("session_id", "pid"), [("", 1), ("s", 0)])
def test_a_malformed_owner_cannot_be_constructed(session_id: str, pid: int) -> None:
    """The transport rejects a missing envelope `pid` with `bounds`; this type is the reason a layer
    inward may then assume it has one."""
    with pytest.raises(ValueError, match=r"session_id|pid"):
        RunOwner(session_id=session_id, pid=pid)


async def test_planning_writes_a_run_its_groups_and_their_members(tmp_path: Path) -> None:
    """Membership is frozen at plan time, at each member's plan-time version — change detection
    only, and deliberately not the version any payload will carry."""
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=10.0)
        run = await planning.plan_groups(c.harness.store.connection, call=c.call())
        assert await c.runs() == [
            (run.run_id, CONSOLIDATOR_SESSION, CONSOLIDATOR_PID, RunStatus.ACTIVE)
        ]
        groups = await c.groups()
        assert len(groups) == 1
        assert groups[0][5] is GroupStatus.PENDING
        assert groups[0][6] == 0
        assert await c.member_rows(groups[0][0]) == [
            (first, 1, None, None),
            (second, 1, None, None),
        ]


async def test_planning_emits_one_planned_event_with_the_runs_own_counts(tmp_path: Path) -> None:
    """`n_deferred` is 0 on `planned` and is the only one of the three that can move."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0)
        await c.clear_events()
        run = await planning.plan_groups(c.harness.store.connection, call=c.call())
        assert detail_of(await c.events(), "consolidate_run") == [
            {
                "run_id": run.run_id,
                "phase": "planned",
                "n_groups": 2,
                "n_members": 2,
                "n_deferred": 0,
            }
        ]


async def test_an_empty_journal_plans_a_run_that_is_immediately_complete(tmp_path: Path) -> None:
    """`architecture.md`'s empty-store table: `plan_groups` → a run with zero groups, immediately
    `complete`. Both events are emitted, in order, so the run's whole life is in the log."""
    async with consolidator(tmp_path) as c:
        await c.clear_events()
        run = await planning.plan_groups(c.harness.store.connection, call=c.call())
        assert await c.runs() == [
            (run.run_id, CONSOLIDATOR_SESSION, CONSOLIDATOR_PID, RunStatus.COMPLETE)
        ]
        assert [detail["phase"] for detail in detail_of(await c.events(), "consolidate_run")] == [
            "planned",
            "complete",
        ]


async def test_replanning_closes_an_unexpired_run_as_abandoned(tmp_path: Path) -> None:
    """`plan_groups` closes any pre-existing `active` run and **the lease decides which status**,
    which is what collapses two overlapping rules into one test."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await planning.plan_groups(c.harness.store.connection, call=c.call())
        second = await planning.plan_groups(c.harness.store.connection, call=c.call(op_id="op2"))
        statuses = {run_id: status for run_id, _, _, status in await c.runs()}
        assert statuses[first.run_id] is RunStatus.ABANDONED
        assert statuses[second.run_id] is RunStatus.ACTIVE


async def test_replanning_closes_a_lapsed_run_as_expired(tmp_path: Path) -> None:
    """The same producer, discriminated by one test — and this is the only place `expired` is ever
    written, since every reader derives expiry rather than storing it."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.lapse_lease(first.run_id)
        second = await planning.plan_groups(c.harness.store.connection, call=c.call(op_id="op2"))
        statuses = {run_id: status for run_id, _, _, status in await c.runs()}
        assert statuses[first.run_id] is RunStatus.EXPIRED
        assert statuses[second.run_id] is RunStatus.ACTIVE


async def test_the_closing_event_describes_the_run_being_closed_not_the_one_being_created(
    tmp_path: Path,
) -> None:
    """Two events of one `op_id` legitimately carry different numbers, and that is the whole reason
    the counts had to be pinned to "the run the transition is about"."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0)
        await c.clear_events()
        second = await planning.plan_groups(c.harness.store.connection, call=c.call(op_id="op2"))
        details = detail_of(await c.events(), "consolidate_run")
        assert [(one["run_id"], one["phase"], one["n_members"]) for one in details] == [
            (first.run_id, "abandoned", 1),
            (second.run_id, "planned", 2),
        ]


async def test_an_explicit_plan_takes_over_a_live_run_held_by_another_worker(
    tmp_path: Path,
) -> None:
    """`plan_groups` is the one entry point that may displace a live worker, and whoever calls it
    wins.

    The reason is that nothing reachable from inside the store separates a dead consolidator from
    one that is merely slow. A lease is a timer, so it cannot. A pid check is better than it looks —
    measured, a consolidator's MCP client normally exits with its own subagent — but it cannot carry
    the decision: it answers whether a process exists, never whether a worker will progress, pid
    reuse can return a false alive, the service and client are not guaranteed a shared pid
    namespace, and whether a *cancelled* turn tears the client down is unmeasured. A human invoking
    the skill a second time is the evidence that does exist, and it arrives here. Refusing would pin
    the store for up to `run_lease` on a worker that has stopped.

    The displaced run is closed **`taken_over`** rather than `abandoned`, which is the distinction
    that would otherwise be unrecoverable: a user retrying in one kiro session presents the *same*
    `session_id` and only a different pid, so nothing else on the row separates "the holder
    restarted its own run" from "the holder was displaced".
    """
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        held = await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.clear_events()
        taker = c.call(op_id="op2", pid=CONSOLIDATOR_PID + 1)
        fresh = await planning.plan_groups(c.harness.store.connection, call=taker)
        assert fresh.run_id != held.run_id
        statuses = {run_id: status for run_id, _, _, status in await c.runs()}
        assert statuses[held.run_id] is RunStatus.TAKEN_OVER
        assert statuses[fresh.run_id] is RunStatus.ACTIVE
        assert [
            (detail["run_id"], detail["phase"])
            for detail in detail_of(await c.events(), "consolidate_run")
        ] == [(held.run_id, "taken_over"), (fresh.run_id, "planned")]


async def test_a_displaced_worker_can_commit_nothing_and_is_told_to_stop(tmp_path: Path) -> None:
    """What makes takeover *safe* rather than merely permitted, and it is a property of the ladder.

    Rung 2 requires a group's run to be owned by the caller **and** effectively active, so the
    displaced worker's next write verb is refused `group_expired` before touching a row — and its
    next `next_group` finds the new run foreign and answers `{busy: true}`, so it stops rather than
    replanning against a live holder. There is no window in which two workers can both write.

    Asserted over **every** kind of state a rejected call could have moved, not only the memory
    row: the old group's member stays undispositioned, the closed run's lease is unchanged, the
    receipt table is unchanged, and no event was appended — `group_expired` is not one of invariant
    10's two carve-out codes, so unlike a version conflict it commits nothing at all.

    Then the harder attack, against the **taker's own new run** rather than the dead one. The
    displaced worker and the taker share `(session_id, client_kind)` completely, because the
    receipt key has no pid — so the taker's serve mints receipts the displaced worker could spend,
    at versions it must present correctly. It presents them against the fresh `group_id` and is
    still refused, because rung 2 runs before rung 5 and the fresh run's owner is not it. That
    pooled-receipt hole is closed by *ordering* rather than by scoping, so the ordering is what
    gets pinned: a `receipts.spend` that raises if it is ever reached proves the call never got
    that far.
    """
    stranger = CONSOLIDATOR_PID + 1
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call(op_id="s1"))
        assert isinstance(served, ServedGroup)
        old_lease = await c.expires_at(served.run_id)
        old_receipts = await c.receipts()

        fresh = await planning.plan_groups(
            c.harness.store.connection, call=c.call(op_id="op2", pid=stranger)
        )
        await c.clear_events()
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[_named(served.journal_entries[0])],
                reason="mid-flight when the store was taken over",
                call=c.call(op_id="d1"),
            )
        assert raised.value.code is ErrorCode.GROUP_EXPIRED
        assert raised.value.data["run_status"] == "taken_over"
        assert await c.row(member) == ("journal", True, None, 1)
        assert await c.member_rows(served.group_id) == [(member, 1, 1, None)]
        assert await c.expires_at(served.run_id) == old_lease
        assert await c.receipts() == old_receipts
        assert await c.events() == []

        stopped = await serving.next_group(c.harness.store.connection, call=c.call(op_id="s2"))
        assert isinstance(stopped, Busy)
        assert stopped.holder_pid == stranger

        taken = await serving.next_group(
            c.harness.store.connection, call=c.call(op_id="s3", pid=stranger)
        )
        assert isinstance(taken, ServedGroup)
        assert taken.run_id == fresh.run_id
        assert [record.uuid for record in taken.journal_entries] == [member]
        pooled = (
            CONSOLIDATOR_SESSION,
            "consolidator",
            member,
            taken.journal_entries[0].expected_version,
            "group",
        )
        assert pooled in await c.receipts()

        await c.clear_events()
        with (
            unittest.mock.patch.object(
                receipts, "spend", side_effect=AssertionError("rung 5 must not be reached")
            ),
            pytest.raises(ZikaronError) as reraised,
        ):
            await verbs.discard(
                c.harness.store.connection,
                group_id=taken.group_id,
                absorb=[_named(taken.journal_entries[0])],
                reason="a pooled receipt is not authority over another worker's group",
                call=c.call(op_id="d2"),
            )
        assert reraised.value.code is ErrorCode.GROUP_EXPIRED
        assert await c.row(member) == ("journal", True, None, 1)
        assert await c.member_rows(taken.group_id) == [(member, 1, 1, None)]
        assert await c.events() == []


async def test_a_failed_replan_does_not_displace_the_incumbent(tmp_path: Path) -> None:
    """Takeover's own failure mode, and the worst outcome available if it were not atomic.

    `_close_previous` writes the incumbent's `taken_over` transition and its event **before** the
    replacement is created and grouped, so a transient failure in planning — an index write, a
    contended store — must erase all of it. Otherwise a takeover that failed halfway would leave the
    live worker displaced with nothing installed in its place: the store held by nobody, and the
    victim stopped for no reason at all.

    Injected after the close, in `grouping.plan`, which is the first thing that can fail once the
    incumbent is already closed. Every trace of the attempt must be gone — the incumbent still
    `active` at its original lease with its original groups, no second run row, and no `taken_over`
    event.
    """
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        incumbent = await planning.plan_groups(c.harness.store.connection, call=c.call())
        before_runs = await c.runs()
        before_groups = await c.groups()
        before_lease = await c.expires_at(incumbent.run_id)
        await c.clear_events()
        with (
            unittest.mock.patch.object(
                grouping, "plan", side_effect=aiosqlite.OperationalError("disk full")
            ),
            pytest.raises(ZikaronError) as raised,
        ):
            await planning.plan_groups(
                c.harness.store.connection, call=c.call(op_id="op2", pid=CONSOLIDATOR_PID + 1)
            )
        assert raised.value.code is ErrorCode.INDEX_FAILED
        assert await c.runs() == before_runs
        assert await c.groups() == before_groups
        assert await c.expires_at(incumbent.run_id) == before_lease
        assert await c.events() == []


async def test_next_group_still_refuses_a_live_run_it_does_not_own(tmp_path: Path) -> None:
    """Takeover belongs to the explicit RPC alone, and this pins the *model-facing* half of that.

    `next_group` is the path a model drives, and it still answers `{busy: true}` to a stranger — so
    no model can *request* a displacement, which is what D32's tool omission actually buys. It is
    not a claim that no consolidator ever displaces another: the conforming client's own automatic
    `plan_groups`, made before the first serve it forwards, does exactly that — once successfully
    per process. The two are separate paths and only this one is under test here."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        held = await planning.plan_groups(c.harness.store.connection, call=c.call())
        outcome = await serving.next_group(
            c.harness.store.connection, call=c.call(op_id="op2", pid=CONSOLIDATOR_PID + 1)
        )
        assert isinstance(outcome, Busy)
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.ACTIVE]
        assert outcome.expires_at == await c.expires_at(held.run_id)


async def test_an_explicit_plan_replaces_a_lapsed_run_for_any_caller(tmp_path: Path) -> None:
    """A lapsed run is `expired` whoever replaces it — that status is about the lease, not the
    caller."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        lapsed = await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.lapse_lease(lapsed.run_id)
        stranger = await planning.plan_groups(
            c.harness.store.connection, call=c.call(op_id="op2", pid=CONSOLIDATOR_PID + 1)
        )
        statuses = {run_id: status for run_id, _, _, status in await c.runs()}
        assert statuses[lapsed.run_id] is RunStatus.EXPIRED
        assert statuses[stranger.run_id] is RunStatus.ACTIVE


async def test_the_owner_replanning_its_own_run_is_abandoned_not_taken_over(tmp_path: Path) -> None:
    """The other half of the two-test branch: same mechanism, different caller, different status.
    Kept apart from `taken_over` because the costs differ — a worker restarting its own run
    discarded nothing it wanted, while a displaced one lost work in progress."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await planning.plan_groups(c.harness.store.connection, call=c.call())
        second = await planning.plan_groups(c.harness.store.connection, call=c.call(op_id="op2"))
        statuses = {run_id: status for run_id, _, _, status in await c.runs()}
        assert statuses[first.run_id] is RunStatus.ABANDONED
        assert statuses[second.run_id] is RunStatus.ACTIVE


async def test_exactly_one_run_is_active_after_repeated_planning(tmp_path: Path) -> None:
    """Invariant 15, through its only producer: one *effectively-active* run per store. Enforced by
    closing every `active` row before creating another, so the property is a consequence of the
    ordering rather than something a later reader has to tolerate."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        for index in range(4):
            await planning.plan_groups(c.harness.store.connection, call=c.call(op_id=f"op{index}"))
        assert [status for _, _, _, status in await c.runs()].count(RunStatus.ACTIVE) == 1


async def test_two_active_runs_are_refused_rather_than_resolved(tmp_path: Path) -> None:
    """Invariant 15 from the reader's side. The state is unreachable through the API, so the fixture
    writes it directly — and the reader refuses rather than picking one, because an implementation
    that quietly served one of two active runs would keep a broken store working while two
    consolidators mutated one journal."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.insert_second_active_run()
        with pytest.raises(ValueError, match="invariant 15"):
            await runs.stored_active(c.harness.store.connection)


async def test_replanning_loses_no_journal_row(tmp_path: Path) -> None:
    """D29's never-lose guard at its cheapest: a run abandoned before any verb ran leaves every
    member `tier='journal' AND active=1`, so the next plan sees exactly the same rows. That is a
    property of the store rather than of the model's cooperation, which is what makes it
    structural."""
    async with consolidator(tmp_path) as c:
        written = {
            await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0),
            await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0),
        }
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        second = await planning.plan_groups(c.harness.store.connection, call=c.call(op_id="op2"))
        replanned = {
            member[0]
            for group_id, *_ in await c.groups()
            for member in await c.member_rows(group_id)
        }
        assert written <= replanned
        assert second.status is RunStatus.ACTIVE


async def test_a_group_records_its_anchor_and_shard_identity(tmp_path: Path) -> None:
    """Invariant 19's per-row half, and the reason `shard_count` is persisted at all: `of` cannot be
    recomputed at serve time without replanning a group whose membership is frozen, against a store
    that has since moved."""
    async with consolidator(tmp_path, overrides="[consolidation]\ngroup_max = 2\n") as c:
        anchor = await c.write(
            gist=_B[0], content=_B[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        for index in range(3):
            await c.write(
                gist=f"{_A[0]} {index}", content=f"{_A[1]} {index}", minute=index + 2, degrees=5.0
            )
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        groups = await c.groups()
        assert [(one[1], one[3], one[4]) for one in groups] == [(anchor, 1, 2), (anchor, 2, 2)]
        assert len({one[2] for one in groups}) == 1


async def test_the_shards_of_one_subgroup_are_complete_and_consistent(tmp_path: Path) -> None:
    """Invariant 19's set-level condition, stated as the design states it: for the rows of a run
    sharing an `order_key`, every row has the same `shard_count = N`, the multiset of `shard_index`
    values is exactly `{1…N}`, and `N` equals the number of rows in the set."""
    async with consolidator(tmp_path, overrides="[consolidation]\ngroup_max = 2\n") as c:
        await c.write(gist=_B[0], content=_B[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM)
        for index in range(5):
            await c.write(
                gist=f"{_A[0]} {index}", content=f"{_A[1]} {index}", minute=index + 2, degrees=5.0
            )
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        by_key: dict[str, list[tuple[int, int]]] = {}
        for _, _, order_key, shard_index, shard_count, _, _ in await c.groups():
            by_key.setdefault(order_key, []).append((shard_index, shard_count))
        for order_key, shards in by_key.items():
            counts = {count for _, count in shards}
            assert counts == {len(shards)}, order_key
            assert sorted(index for index, _ in shards) == list(range(1, len(shards) + 1))


async def test_a_consolidation_call_refuses_a_client_kind_that_is_not_the_consolidator(
    tmp_path: Path,
) -> None:
    """Receipts are keyed on `client_kind`, and this layer both mints and spends them: minted under
    `mcp`, a serve's receipts would license the **primary** agent to amend rows it never fetched,
    which is the exact hole that column was added to close."""
    async with consolidator(tmp_path) as c:
        with pytest.raises(ValueError, match="client_kind"):
            c.call(session_id=AGENT_SESSION).__class__(
                ctx=c.harness.read_call().ctx,
                pid=CONSOLIDATOR_PID,
                settings=c.call().settings,
                retrieval=c.call().retrieval,
                index=c.call().index,
            )
