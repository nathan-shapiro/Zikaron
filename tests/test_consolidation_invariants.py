"""Invariant tests for the consolidation verbs: `schema.md` invariants 12-17 and 19, plus 2 and 10.

`coding-standards.md` §4 makes these first-class and non-optional: each is named for the invariant
it defends and each **fails if that invariant is violated**. Several of the properties are also
exercised incidentally by the behaviour tests in the sibling files; these exist so that a later
session can find the guard by the invariant's number rather than by guessing which behaviour
happened to cover it.

Invariants 2 and 10 are cross-cutting: the indexing, write-tool and consolidation layers each
re-assert them for their own verbs rather than assuming a lower layer covered them, because every
new write path is a new way to violate them.
"""

import inspect
import unittest.mock
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
import pytest

from tests.consolidation_fixtures import CONSOLIDATOR_PID, consolidator, detail_of
from zikaron.core.consolidation import groups, planning, rowstate, serving, verbs
from zikaron.core.consolidation.groups import Disposition, GroupStatus
from zikaron.core.consolidation.payload import (
    MergeTarget,
    NamedRow,
    RunDone,
    ServedGroup,
)
from zikaron.core.consolidation.runs import RunStatus
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.records.memory import Rewrite, Tier
from zikaron.core.retrieval.eligibility import Consumer, Scope

_RECORD = ("the proto toolchain is pinned", "the pinned version lives in requirements.txt")
_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_B = ("proto codegen also fails locally", "the same drift shows up in the dev container")
_NEW = Rewrite(gist="proto drift, consolidated", content="one pin; the drift bites everywhere")


@dataclass(frozen=True, slots=True)
class _RowState:
    """One reachable `memory` row state, as the three columns every filter here is written over."""

    tier: str
    active: bool
    superseded: bool


@dataclass(frozen=True, slots=True)
class _Admits:
    """What that state is admitted as: a deliverable member, a targetable record, or neither."""

    member: bool
    target: bool


async def _serve(c: object, *, op_id: str = "op1") -> ServedGroup:
    served = await serving.next_group(c.harness.store.connection, call=c.call(op_id=op_id))  # type: ignore[attr-defined]
    assert isinstance(served, ServedGroup)
    return served


def _named(record: object) -> NamedRow:
    return NamedRow(uuid=record.uuid, expected_version=record.expected_version)  # type: ignore[attr-defined]


async def test_invariant_12_every_row_consolidation_creates_has_a_chunk_and_a_vector(
    tmp_path: Path,
) -> None:
    """A memory with zero vectors would be invisible to the dense arm while looking perfectly
    healthy.

    Checked over **every** active memory after a promotion and a merge — the two verbs that author
    prose — rather than over the one row each returned, so a verb that created a row and skipped its
    index would fail here whichever row it was.
    """
    async with consolidator(tmp_path) as c:
        await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve(c)
        assert served.anchor is not None
        await verbs.merge(
            c.harness.store.connection,
            group_id=served.group_id,
            target=MergeTarget(row=_named(served.anchor), rewrite=_NEW),
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="merge"),
        )
        await c.write(gist=_B[0], content=_B[1], minute=3, degrees=90.0)
        second = await _serve(c, op_id="s2")
        await verbs.promote(
            c.harness.store.connection,
            group_id=second.group_id,
            rewrite=Rewrite(gist="another lesson", content="worth keeping on its own"),
            absorb=[_named(second.journal_entries[0])],
            call=c.call(op_id="promote"),
        )
        rows = await c.harness.store.connection.execute_fetchall(
            "SELECT m.uuid, count(v.rowid) FROM memory m "
            "LEFT JOIN memory_chunk ch ON ch.memory_uuid = m.uuid "
            "LEFT JOIN memory_vec v ON v.rowid = ch.chunk_id "
            "WHERE m.active = 1 GROUP BY m.uuid"
        )
        counted = {str(uuid): int(str(count)) for uuid, count in rows}
        assert counted
        assert all(count >= 1 for count in counted.values()), counted


async def test_invariant_13_the_lexical_index_stays_unchunked_after_a_merge(tmp_path: Path) -> None:
    """FTS5 is unchunked; `vec0` is chunked. The asymmetry is easy to break by reflex, so it is
    asserted on the shape of **both** indexes after a verb that rebuilds them — and asserted in a
    way that fails if either half is lost.

    Counting one `memory_fts` row is not enough on its own: an external-content table has one row
    per content row whatever was indexed, so that count would still pass if the merge had indexed
    only the gist, or only the first dense chunk, and dropped the content's tail. So the fixture
    forces the content across several dense chunks and then matches a term appearing **only in the
    last paragraph**: the dense side must show more than one chunk, and the lexical side must still
    find a term from the far end of the prose in that one document.
    """
    tail_marker = "zqxjvw"
    paragraph = " ".join(f"word{index}" for index in range(50))
    merged = Rewrite(
        gist="proto drift, consolidated",
        content=f"{paragraph}\n\n{paragraph}\n\nfinal paragraph mentions {tail_marker} once",
    )
    async with consolidator(tmp_path, overrides="[indexing]\nchunk_max_tokens = 64\n") as c:
        record = await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve(c)
        assert served.anchor is not None
        await verbs.merge(
            c.harness.store.connection,
            group_id=served.group_id,
            target=MergeTarget(row=_named(served.anchor), rewrite=merged),
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="merge"),
        )
        chunks = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory_chunk WHERE memory_uuid = ?", (record,)
        )
        assert int(str(next(iter(chunks))[0])) > 1, "the fixture must split the dense side"
        fts_rows = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory_fts "
            "WHERE rowid = (SELECT rowid FROM memory WHERE uuid = ?)",
            (record,),
        )
        assert int(str(next(iter(fts_rows))[0])) == 1
        matched = await c.harness.store.connection.execute_fetchall(
            "SELECT m.uuid FROM memory_fts JOIN memory m ON m.rowid = memory_fts.rowid "
            "WHERE memory_fts MATCH ?",
            (tail_marker,),
        )
        assert [str(uuid) for (uuid,) in matched] == [record]


def test_invariant_14_no_verb_accepts_an_internal_handle() -> None:
    """`uuid` is the only handle exposed to the primary agent; `group_id` and `run_id` reach the
    consolidator only, and **no verb accepts `run_id` at all** — it is a correlation id, not a
    handle.

    Asserted on the signatures, because that is where the property lives: a verb that took a
    `run_id` would be authorizing on something the design says authorizes nothing, and a verb that
    took a `rowid` or a `chunk_id` would have exposed an internal one.
    """
    forbidden = {"run_id", "rowid", "chunk_id", "event_id"}
    for verb in (verbs.merge, verbs.promote, verbs.discard, serving.next_group):
        parameters = set(inspect.signature(verb).parameters)
        assert not parameters & forbidden, verb.__name__
    assert "group_id" in set(inspect.signature(verbs.merge).parameters)


def test_invariant_14_the_served_payload_exposes_no_internal_handle() -> None:
    """The other half: what comes back. `run_id` is present and deliberately so — the carve-out the
    invariant now states — while no field of any delivered record names a rowid or a chunk id."""
    record_fields = set(ServedGroup.__dataclass_fields__)
    assert "run_id" in record_fields
    assert not record_fields & {"rowid", "chunk_id"}


async def test_invariant_15_one_effectively_active_run_per_store(tmp_path: Path) -> None:
    """Enforced by its only producer: `plan_groups` closes every `active` row before creating
    another, so no instant exists at which two runs are effectively active."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        for index in range(3):
            await planning.plan_groups(c.harness.store.connection, call=c.call(op_id=f"p{index}"))
            active = [status for _, _, _, status in await c.runs() if status is RunStatus.ACTIVE]
            assert len(active) == 1


async def test_invariant_16_a_group_completes_only_when_every_member_is_dispositioned(
    tmp_path: Path,
) -> None:
    """`status='complete'` requires zero members with `disposition IS NULL`. Asserted from the other
    direction too: with a member still open the group stays `served`, so one write verb does not
    close a group."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=2.0)
        served = await _serve(c)
        await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(served.journal_entries[0])],
            reason="noise",
            call=c.call(op_id="d1"),
        )
        assert (await c.groups())[0][5] is GroupStatus.SERVED
        await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(served.journal_entries[1])],
            reason="noise",
            call=c.call(op_id="d2"),
        )
        assert (await c.groups())[0][5] is GroupStatus.COMPLETE
        assert [member[3] for member in await c.member_rows(served.group_id)] == [
            Disposition.DISCARDED,
            Disposition.DISCARDED,
        ]


async def test_invariant_16_no_committed_group_is_open_with_zero_undispositioned_members(
    tmp_path: Path,
) -> None:
    """The closure property, which an earlier draft omitted and whose absence left a group
    permanently uncloseable. Stated as the design states it — over **every** group of the store, at
    a transaction boundary — and driven through the path that reaches it with no write verb having
    run at all: every member of a group vacating at serve time.
    """
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.harness.retire(first)
        assert isinstance(
            await serving.next_group(c.harness.store.connection, call=c.call(op_id="s2")),
            ServedGroup,
        )
        rows = await c.harness.store.connection.execute_fetchall(
            "SELECT g.group_id, g.status, "
            "(SELECT count(*) FROM consolidation_group_member m "
            "  WHERE m.group_id = g.group_id AND m.disposition IS NULL) "
            "FROM consolidation_group g"
        )
        for group_id, status, open_members in rows:
            if str(status) in groups.OPEN_STATUSES:
                assert int(str(open_members)) > 0, str(group_id)


async def test_invariant_17_every_group_transition_the_table_names_is_reachable(
    tmp_path: Path,
) -> None:
    """The group state machine is closed and each transition has a named cause. Every row of the
    table is driven here, and `pending → complete` is the one worth naming: it is the serve
    transaction, when vacating dispositions *every* member, and it leaves `serve_count` at 0
    because nothing was delivered."""
    async with consolidator(tmp_path, overrides="[consolidation]\nmax_group_serves = 2\n") as c:
        # pending -> served (serve_count = 1), then served -> served (2), then served -> deferred.
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await _serve(c)
        assert first.serve_count == 1
        second = await _serve(c, op_id="s2")
        assert second.serve_count == 2
        assert isinstance(
            await serving.next_group(c.harness.store.connection, call=c.call(op_id="s3")), RunDone
        )
        assert (await c.groups())[0][5] is GroupStatus.DEFERRED

    (tmp_path / "second").mkdir(exist_ok=True)
    async with consolidator(tmp_path / "second") as c:
        # pending -> complete: never delivered, serve_count stays 0, no group_served event.
        alone = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.harness.retire(alone)
        await c.clear_events()
        assert isinstance(
            await serving.next_group(c.harness.store.connection, call=c.call(op_id="s2")), RunDone
        )
        group = (await c.groups())[0]
        assert (group[5], group[6]) == (GroupStatus.COMPLETE, 0)
        assert [kind for kind, _, _ in await c.events() if kind == "group_served"] == []


async def test_invariant_17_every_run_transition_the_table_names_is_reachable(
    tmp_path: Path,
) -> None:
    """`— → active` by `plan_groups`; `active → complete` by whichever transaction first observes no
    open group; and `active → expired` / `abandoned` / `taken_over` by `plan_groups`, discriminated
    by the lease and then by ownership. Each is asserted with the `consolidate_run` phase that
    records it, so a transition with no event — or an event with no transition — fails.

    All five rows of the table are driven, `taken_over` included: it is the only one a *foreign*
    caller produces, so a fixture using one owner throughout would leave a quarter of the
    discriminator untested while looking exhaustive.
    """
    stranger = CONSOLIDATOR_PID + 1
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        abandoned = await planning.plan_groups(c.harness.store.connection, call=c.call(op_id="p1"))
        expired = await planning.plan_groups(c.harness.store.connection, call=c.call(op_id="p2"))
        await c.lapse_lease(expired.run_id)
        stolen = await planning.plan_groups(c.harness.store.connection, call=c.call(op_id="p3"))
        completed = await planning.plan_groups(
            c.harness.store.connection, call=c.call(op_id="p4", pid=stranger)
        )
        served = await serving.next_group(
            c.harness.store.connection, call=c.call(op_id="s1", pid=stranger)
        )
        assert isinstance(served, ServedGroup)
        await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(served.journal_entries[0])],
            reason="noise",
            call=c.call(op_id="d", pid=stranger),
        )
        statuses = {run_id: status for run_id, _, _, status in await c.runs()}
        assert statuses[abandoned.run_id] is RunStatus.ABANDONED
        assert statuses[expired.run_id] is RunStatus.EXPIRED
        assert statuses[stolen.run_id] is RunStatus.TAKEN_OVER
        assert statuses[completed.run_id] is RunStatus.COMPLETE
        phases = {
            (str(detail["run_id"]), str(detail["phase"]))
            for detail in detail_of(await c.events(), "consolidate_run")
        }
        assert (abandoned.run_id, "planned") in phases
        assert (abandoned.run_id, "abandoned") in phases
        assert (expired.run_id, "expired") in phases
        assert (stolen.run_id, "taken_over") in phases
        assert (completed.run_id, "complete") in phases


async def test_invariant_17_expiry_is_never_written_by_a_rejected_call(tmp_path: Path) -> None:
    """Every reader derives expiry from `expires_at`; only `plan_groups` stores it. Having a
    rejected call perform the transition would contradict the rule that a rejection writes nothing
    but its audit events, and an earlier draft had both rules."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve(c)
        await c.lapse_lease(served.run_id)
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[_named(served.journal_entries[0])],
                reason="noise",
                call=c.call(op_id="d"),
            )
        assert raised.value.code is ErrorCode.GROUP_EXPIRED
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.ACTIVE]


async def test_invariant_19_shard_identity_is_persisted_complete_and_consistent(
    tmp_path: Path,
) -> None:
    """For the rows of one run sharing an `order_key`: every row has the same `shard_count = N`, the
    multiset of `shard_index` values is exactly `{1…N}`, and `N` equals the number of rows in the
    set.

    Group status is deliberately not part of it — shards are dispositioned independently, so one
    shard may be `complete` while its siblings are `pending`. Driven with one shard already
    completed, so a naive implementation that counted only open siblings would fail.
    """
    async with consolidator(tmp_path, overrides="[consolidation]\ngroup_max = 2\n") as c:
        await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        for index in range(5):
            await c.write(
                gist=f"{_A[0]} {index}", content=f"{_A[1]} {index}", minute=index + 2, degrees=5.0
            )
        served = await _serve(c)
        await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(record) for record in served.journal_entries],
            reason="noise",
            call=c.call(op_id="d"),
        )
        assert (await c.groups())[0][5] is GroupStatus.COMPLETE
        by_key: dict[str, list[int]] = {}
        counts: dict[str, set[int]] = {}
        for _, _, order_key, shard_index, shard_count, _, _ in await c.groups():
            by_key.setdefault(order_key, []).append(shard_index)
            counts.setdefault(order_key, set()).add(shard_count)
        assert by_key
        for order_key, indexes in by_key.items():
            assert counts[order_key] == {len(indexes)}, order_key
            assert sorted(indexes) == list(range(1, len(indexes) + 1)), order_key


async def test_invariant_10_a_verbs_events_commit_with_its_mutation(tmp_path: Path) -> None:
    """No event outside the transaction it describes. Asserted the hard way — by making the last
    write of the transaction fail after the mutation and the events are staged — so a verb that
    committed its audit trail early would leave events describing a mutation the store does not
    have."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve(c)
        await c.clear_events()
        with (
            unittest.mock.patch.object(
                groups,
                "disposition_members",
                side_effect=aiosqlite.OperationalError("disk full"),
            ),
            pytest.raises(ZikaronError) as raised,
        ):
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[_named(served.journal_entries[0])],
                reason="noise",
                call=c.call(op_id="d"),
            )
        assert raised.value.code is ErrorCode.INDEX_FAILED
        assert await c.events() == []
        assert await c.row(member) == ("journal", True, None, 1)
        assert await c.member_rows(served.group_id) == [(member, 1, 1, None)]


async def test_invariant_2_a_failed_verb_leaves_neither_prose_nor_index_behind(
    tmp_path: Path,
) -> None:
    """One logical mutation is exactly one transaction, covering the row, the version bump, both
    indexes, the receipts and the events. Simulated by raising after the target's prose and index
    have been rewritten: the store must show the old state, not a record with new prose and stale
    chunks."""
    async with consolidator(tmp_path) as c:
        record = await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve(c)
        assert served.anchor is not None
        with (
            unittest.mock.patch.object(
                groups,
                "disposition_members",
                side_effect=aiosqlite.OperationalError("disk full"),
            ),
            pytest.raises(ZikaronError),
        ):
            await verbs.merge(
                c.harness.store.connection,
                group_id=served.group_id,
                target=MergeTarget(row=_named(served.anchor), rewrite=_NEW),
                absorb=[_named(served.journal_entries[0])],
                call=c.call(op_id="merge"),
            )
        assert await c.row(record) == ("long_term", True, None, 1)
        prose = await c.harness.store.connection.execute_fetchall(
            "SELECT gist FROM memory WHERE uuid = ?", (record,)
        )
        assert str(next(iter(prose))[0]) == _RECORD[0]
        matched = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory_fts JOIN memory m ON m.rowid = memory_fts.rowid "
            "WHERE memory_fts MATCH ? AND m.uuid = ?",
            ("consolidated", record),
        )
        assert int(str(next(iter(matched))[0])) == 0


@pytest.mark.parametrize("form", ["in_place", "new_row"])
async def test_invariant_2_neither_promotion_form_leaves_anything_behind(
    tmp_path: Path, form: str
) -> None:
    """`promote` owns its own transaction and has **two** mutation sequences, so it needs two
    atomicity tests rather than one shared with the other verbs.

    `new_row` inserts a memory and both of its indexes before dispositioning; `in_place` flips a
    tier and a version and rebuilds nothing. A regression that bypassed this verb's own transaction
    wrapper would leave either a long-term record with no group progress, or a flipped tier the
    caller was told had failed — and every happy-path promotion test would still pass. Injected
    after the row mutation and its index work, which is the only point at which the two forms
    differ.
    """
    prose = Rewrite(gist=_A[0], content=_A[1]) if form == "in_place" else _NEW
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve(c)
        before = await c.row(member)
        rows_before = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory"
        )
        await c.clear_events()
        with (
            unittest.mock.patch.object(
                groups,
                "disposition_members",
                side_effect=aiosqlite.OperationalError("disk full"),
            ),
            pytest.raises(ZikaronError) as raised,
        ):
            await verbs.promote(
                c.harness.store.connection,
                group_id=served.group_id,
                rewrite=prose,
                absorb=[_named(served.journal_entries[0])],
                call=c.call(op_id="p"),
            )
        assert raised.value.code is ErrorCode.INDEX_FAILED
        assert await c.events() == []
        assert await c.row(member) == before
        assert await c.member_rows(served.group_id) == [(member, 1, 1, None)]
        rows_after = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory"
        )
        assert int(str(next(iter(rows_after))[0])) == int(str(next(iter(rows_before))[0]))
        orphaned = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory_chunk ch "
            "WHERE NOT EXISTS (SELECT 1 FROM memory m WHERE m.uuid = ch.memory_uuid)"
        )
        assert int(str(next(iter(orphaned))[0])) == 0


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_RowState("journal", active=True, superseded=False), _Admits(member=True, target=False)),
        (_RowState("journal", active=False, superseded=False), _Admits(member=False, target=False)),
        (_RowState("journal", active=False, superseded=True), _Admits(member=False, target=False)),
        (_RowState("long_term", active=True, superseded=False), _Admits(member=False, target=True)),
        (
            _RowState("long_term", active=False, superseded=False),
            _Admits(member=False, target=False),
        ),
        (
            _RowState("long_term", active=False, superseded=True),
            _Admits(member=False, target=False),
        ),
    ],
)
async def test_the_row_state_checks_agree_with_the_filter_table_in_every_state(
    tmp_path: Path, state: "_RowState", expected: "_Admits"
) -> None:
    """A serve and the ladder's rung 6 must apply the **identical** predicate, which is why neither
    re-expresses it: both evaluate the clause `eligibility.CONSUMER_FILTERS` states.

    This asserts the property across every reachable row state, and against the filter table's own
    SQL rather than against a second hand-written predicate — so a change to that table changes
    both sides of the comparison at once, which is the point of reading it rather than transcribing
    it.
    """
    async with consolidator(tmp_path) as c:
        uuid = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        replacement = (
            await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0)
            if state.superseded
            else None
        )
        if not state.active:
            await c.harness.retire(uuid, superseded_by=replacement)
        if state.tier != "journal":
            await c.harness.set_tier(uuid, state.tier)
        member_ok = await rowstate.is_deliverable_member(c.harness.store.connection, uuid)
        assert member_ok is expected.member
        assert await rowstate.is_targetable(c.harness.store.connection, uuid) is expected.target
        for consumer, admitted in (
            (Consumer.ORPHAN, expected.member),
            (Consumer.CONSOLIDATION, expected.target),
        ):
            scope = Scope(
                consumer,
                exclude_uuid="never-this-uuid" if consumer is Consumer.ORPHAN else None,
            )
            clause, params = scope.where()
            rows = await c.harness.store.connection.execute_fetchall(
                f"SELECT count(*) FROM memory m WHERE m.uuid = ? AND {clause}",  # noqa: S608 — the clause is the filter table's own.
                (uuid, *params),
            )
            assert (int(str(next(iter(rows))[0])) == 1) is admitted, consumer
