"""`next_group`: `zikaron.core.consolidation.serving`.

Default tier, unmarked: a real store, because a serve is a claim about which rows were delivered,
which statuses moved, which receipts exist and which events committed — none of which a stand-in
can hold.
"""

from pathlib import Path

import pytest

from tests.consolidation_fixtures import (
    AGENT_SESSION,
    CONSOLIDATOR_PID,
    CONSOLIDATOR_SESSION,
    consolidator,
    detail_of,
    dumps,
)
from zikaron.core.consolidation import planning, serving
from zikaron.core.consolidation.candidates import MAX_CANDIDATES
from zikaron.core.consolidation.groups import Disposition, GroupStatus
from zikaron.core.consolidation.payload import Busy, RunDone, ServedGroup
from zikaron.core.consolidation.runs import RunStatus
from zikaron.core.records.memory import Tier

_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_B = ("proto codegen also fails locally", "the same drift shows up in the dev container")
_C = ("gradle picks the newest JDK", "toolchain resolution ignores the pinned version")


async def test_a_serve_delivers_the_journal_entries_in_group_order(tmp_path: Path) -> None:
    """`journal_entries` is the served set in group order, each at the version whose prose it
    carries — re-read at serve time, not the plan-time `version_seen`."""
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=10.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert [record.uuid for record in served.journal_entries] == [first, second]
        assert [record.expected_version for record in served.journal_entries] == [1, 1]
        assert served.anchor is None
        assert served.anchor_vacated is False
        assert served.candidates == ()
        assert (served.shard.index, served.shard.of) == (1, 1)
        assert served.serve_count == 1
        assert served.remaining_groups == 0


async def test_a_serve_mints_a_group_receipt_for_every_delivered_row(tmp_path: Path) -> None:
    """This is how the consolidator satisfies D26 without being given `fetch`: the payload delivers
    full content, so the payload is what mints the licence to write it — scoped to
    `client_kind='consolidator'`, so it licenses nothing for the primary agent."""
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=10.0)
        await serving.next_group(c.harness.store.connection, call=c.call())
        minted = {
            (session, kind, uuid, version, source)
            for session, kind, uuid, version, source in await c.receipts()
            if source == "group"
        }
        assert minted == {
            (CONSOLIDATOR_SESSION, "consolidator", first, 1, "group"),
            (CONSOLIDATOR_SESSION, "consolidator", second, 1, "group"),
        }
        assert not [
            row for row in await c.receipts() if row[0] == AGENT_SESSION and row[4] == "group"
        ]


async def test_a_serve_emits_one_group_served_event_per_delivered_row(tmp_path: Path) -> None:
    """One per member of the served set, one per candidate, one for the anchor when delivered — and
    `version_served` is non-null on every one, which is what a vacated row emitting none buys."""
    async with consolidator(tmp_path) as c:
        anchor = await c.write(
            gist=_C[0], content=_C[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        member = await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        await c.clear_events()
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert served.anchor is not None
        assert served.anchor.uuid == anchor
        events = [
            (uuid, detail["role"], detail["version_served"], detail["serve_count"])
            for kind, uuid, detail in await c.events()
            if kind == "group_served"
        ]
        assert events == [(anchor, "anchor", 1, 1), (member, "member", 1, 1)]


async def test_a_serve_persists_the_authorization_set_with_the_anchor_at_rank_zero(
    tmp_path: Path,
) -> None:
    """`consolidation_group_candidate` — not the events — is what authorizes a later `merge`, and it
    survives a restart because it is state rather than a recomputation."""
    async with consolidator(tmp_path) as c:
        anchor = await c.write(
            gist=_C[0], content=_C[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert await c.authorization_rows(served.group_id) == [(anchor, "anchor", 1, 0)]


async def test_candidates_exclude_the_anchor_and_every_member(tmp_path: Path) -> None:
    """ "Excluding the anchor and every member from the *results*" — every member of the frozen
    plan-time universe, not only the served set, so a row the consolidator has already dispositioned
    is never shown back to it as a candidate."""
    async with consolidator(tmp_path) as c:
        anchor = await c.write(
            gist=_C[0], content=_C[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        other = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=5.0, tier=Tier.LONG_TERM)
        member = await c.write(gist=_A[0], content=_A[1], minute=3, degrees=10.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert served.anchor is not None
        candidate_uuids = [ranked.record.uuid for ranked in served.candidates]
        # Which of the two long-term records anchors is the fused order's business, and both clear
        # the floor here; what this test fixes is the *partition* — every long-term record is either
        # the anchor or a candidate, never both, and no member is ever a candidate.
        assert {served.anchor.uuid, *candidate_uuids} == {anchor, other}
        assert served.anchor.uuid not in candidate_uuids
        assert member not in candidate_uuids
        assert [ranked.rank for ranked in served.candidates] == [1]
        assert served.n_gists_used == 1


async def test_candidates_are_capped_at_four(tmp_path: Path) -> None:
    """ "At most, one anchor plus four candidates" — the five the shipped prompt promises."""
    async with consolidator(tmp_path) as c:
        for index in range(6):
            await c.write(
                gist=f"long term {index} shared word",
                content=f"a long term record {index} shared word",
                minute=index,
                degrees=5.0,
                tier=Tier.LONG_TERM,
            )
        await c.write(gist=_A[0], content=f"{_A[1]} shared word", minute=10, degrees=6.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert len(served.candidates) == MAX_CANDIDATES
        assert [ranked.rank for ranked in served.candidates] == [1, 2, 3, 4]


async def test_the_group_query_stops_before_the_gist_that_would_exceed_the_budget(
    tmp_path: Path,
) -> None:
    """Whole gists are dropped rather than one being cut in half, and `n_gists_used` reports how
    many fitted. Driven by shrinking the encoder's own sequence cap, which is the deployed
    constraint — the fake counts whitespace-delimited tokens, so the arithmetic is hand-computable:
    three special tokens' worth of headroom leaves room for the first two-token gist and not the
    second."""
    async with consolidator(tmp_path, overrides='[embedding]\nembed_prefix_query = ""\n') as c:
        await c.write(gist="alpha one", content="content about alpha", minute=1, degrees=0.0)
        await c.write(gist="beta two", content="content about beta", minute=2, degrees=5.0)
        # Squeezed *after* the writes, so the rows themselves were chunked and embedded normally and
        # the only thing under budget pressure is the serve's own group query.
        c.harness.encoder.max_sequence_tokens = 3
        c.harness.encoder.n_special_tokens = 0
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert len(served.journal_entries) == 2
        assert served.n_gists_used == 1


async def test_no_gist_fitting_serves_no_candidates_at_all(tmp_path: Path) -> None:
    """`n_gists_used = 0` is the answer, not a fallback: `candidates` is the persisted set a later
    `merge` may target, so a query assembled from the prefix and nothing else would authorize
    whichever records happen to sit nearest an empty query."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_C[0], content=_C[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM)
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=90.0)
        c.harness.encoder.max_sequence_tokens = 1
        c.harness.encoder.n_special_tokens = 1
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert served.n_gists_used == 0
        assert served.candidates == ()
        assert await c.authorization_rows(served.group_id) == []


async def test_a_second_worker_in_one_session_with_a_different_pid_gets_busy(
    tmp_path: Path,
) -> None:
    """Ownership is the `(session_id, pid)` pair, never the session alone — since every client of
    one kiro session shares a `session_id` *and* two consolidators of that session share a
    `client_kind`. A defined, deterministic answer rather than an error and rather than a second
    plan."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(first, ServedGroup)
        busy = await serving.next_group(
            c.harness.store.connection, call=c.call(op_id="op2", pid=CONSOLIDATOR_PID + 1)
        )
        assert isinstance(busy, Busy)
        assert busy.holder_session == CONSOLIDATOR_SESSION
        assert busy.holder_pid == CONSOLIDATOR_PID
        assert busy.expires_at == await c.expires_at(first.run_id)
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.ACTIVE]


async def test_an_owner_whose_lease_lapsed_recovers_by_replanning(tmp_path: Path) -> None:
    """The fix for a real dead end. `next_group` treats an effectively-expired run as **absent for
    every caller including its owner**, so crash takeover by a stranger and lease recovery by the
    owner are the same code path — where before, an owner whose lease lapsed found its own run, was
    served a group from it, and was rejected `group_expired` forever."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(first, ServedGroup)
        await c.lapse_lease(first.run_id)
        second = await serving.next_group(c.harness.store.connection, call=c.call(op_id="op2"))
        assert isinstance(second, ServedGroup)
        assert second.run_id != first.run_id
        statuses = {run_id: status for run_id, _, _, status in await c.runs()}
        assert statuses[first.run_id] is RunStatus.EXPIRED
        assert statuses[second.run_id] is RunStatus.ACTIVE


async def test_a_lapsed_run_belonging_to_a_stranger_is_taken_over_by_the_same_path(
    tmp_path: Path,
) -> None:
    """Crash takeover is not a special case: only an *unexpired* run of a different owner is
    `busy`."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        stranger = await serving.next_group(
            c.harness.store.connection, call=c.call(session_id="other-session")
        )
        assert isinstance(stranger, ServedGroup)
        await c.lapse_lease(stranger.run_id)
        mine = await serving.next_group(c.harness.store.connection, call=c.call(op_id="op2"))
        assert isinstance(mine, ServedGroup)
        assert mine.run_id != stranger.run_id


async def test_a_re_serve_increments_the_count_and_refreshes_served_at(tmp_path: Path) -> None:
    """The earliest `served`-but-incomplete group is **re-served, not skipped**, so a consolidator
    cannot walk past a group it found hard by simply calling again. `serve_count` counts deliveries
    *including the first*, so a second delivery reports 2."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await serving.next_group(c.harness.store.connection, call=c.call())
        second = await serving.next_group(c.harness.store.connection, call=c.call(op_id="op2"))
        assert isinstance(first, ServedGroup)
        assert isinstance(second, ServedGroup)
        assert second.group_id == first.group_id
        assert (first.serve_count, second.serve_count) == (1, 2)
        assert [one[6] for one in await c.groups()] == [2]


async def test_a_group_at_the_delivery_cap_is_deferred_and_the_run_finishes(
    tmp_path: Path,
) -> None:
    """Serving is bounded because an unbounded re-serve is a livelock. At `max_group_serves = 2` a
    group is delivered twice and the third call defers it — and its members stay undispositioned, so
    the next run plans them again and the never-lose guard is untouched."""
    async with consolidator(tmp_path, overrides="[consolidation]\nmax_group_serves = 2\n") as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        for index in range(2):
            assert isinstance(
                await serving.next_group(
                    c.harness.store.connection, call=c.call(op_id=f"s{index}")
                ),
                ServedGroup,
            )
        done = await serving.next_group(c.harness.store.connection, call=c.call(op_id="s2"))
        assert isinstance(done, RunDone)
        groups = await c.groups()
        assert groups[0][5] is GroupStatus.DEFERRED
        assert await c.member_rows(groups[0][0]) == [(member, 1, 1, None)]
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.COMPLETE]


async def test_the_completing_run_reports_how_many_groups_it_deferred(tmp_path: Path) -> None:
    """`n_deferred` is the only one of the three counts that moves, and it is read after the
    transition so a `complete` event reflects every group the run ended up deferring."""
    async with consolidator(tmp_path, overrides="[consolidation]\nmax_group_serves = 1\n") as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_C[0], content=_C[1], minute=2, degrees=90.0)
        for index in range(2):
            await serving.next_group(c.harness.store.connection, call=c.call(op_id=f"s{index}"))
        await c.clear_events()
        assert isinstance(
            await serving.next_group(c.harness.store.connection, call=c.call(op_id="s9")), RunDone
        )
        assert detail_of(await c.events(), "consolidate_run") == [
            {
                "run_id": (await c.runs())[0][0],
                "phase": "complete",
                "n_groups": 2,
                "n_members": 2,
                "n_deferred": 2,
            }
        ]


async def test_a_member_that_left_the_journal_is_vacated_and_not_delivered(tmp_path: Path) -> None:
    """It left by another path — a primary agent retired it — so nothing was lost and it blocks no
    completion. Recorded in `disposition`, deliberately **not** in the event log, which is what lets
    `group_served.version_served` be non-null and mean what it says."""
    async with consolidator(tmp_path) as c:
        stays = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        leaves = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=10.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.harness.retire(leaves)
        await c.clear_events()
        served = await serving.next_group(c.harness.store.connection, call=c.call(op_id="op2"))
        assert isinstance(served, ServedGroup)
        assert [record.uuid for record in served.journal_entries] == [stays]
        assert await c.member_rows(served.group_id) == [
            (stays, 1, 1, None),
            (leaves, 1, None, Disposition.VACATED),
        ]
        assert [uuid for kind, uuid, _ in await c.events() if kind == "group_served"] == [stays]


async def test_vacating_every_member_closes_the_group_without_delivering_it(
    tmp_path: Path,
) -> None:
    """Invariant 16's closure property: no committed group is `pending` or `served` with zero
    undispositioned members. `pending → complete` directly, `serve_count` stays 0, and no
    `group_served` is emitted — the group was never delivered, so it never counts as served.

    The loop then continues rather than handing back an empty group, which is the whole reason it
    exists: the earlier design re-served the empty group until the budget ran out and it went
    `deferred`, contradicting this invariant's own completion condition."""
    async with consolidator(tmp_path) as c:
        alone = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.harness.retire(alone)
        await c.clear_events()
        done = await serving.next_group(c.harness.store.connection, call=c.call(op_id="op2"))
        assert isinstance(done, RunDone)
        groups = await c.groups()
        assert (groups[0][5], groups[0][6]) == (GroupStatus.COMPLETE, 0)
        assert [kind for kind, _, _ in await c.events() if kind == "group_served"] == []
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.COMPLETE]


async def test_completion_beats_deferral_when_a_group_at_the_cap_vacates_out(
    tmp_path: Path,
) -> None:
    """The two tests are ordered on purpose: a group whose last member just vacated is *finished*,
    and deferring it instead would leave a group with nothing left to decide looking abandoned for
    the rest of the run and inflating `n_deferred`."""
    async with consolidator(tmp_path, overrides="[consolidation]\nmax_group_serves = 1\n") as c:
        alone = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        await c.harness.retire(alone)
        done = await serving.next_group(c.harness.store.connection, call=c.call(op_id="op2"))
        assert isinstance(done, RunDone)
        groups = await c.groups()
        assert groups[0][5] is GroupStatus.COMPLETE
        assert detail_of(await c.events(), "consolidate_run")[-1]["n_deferred"] == 0


async def test_an_anchor_that_stopped_being_targetable_is_dropped_and_reported(
    tmp_path: Path,
) -> None:
    """Served with `anchor: null` and `anchor_vacated: true` — two situations the payload
    distinguishes on purpose, because "there was a record here and it is gone" is information a
    model choosing between `merge` and `promote` can use. The group stays servable."""
    async with consolidator(tmp_path) as c:
        anchor = await c.write(
            gist=_C[0], content=_C[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        member = await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.harness.retire(anchor)
        served = await serving.next_group(c.harness.store.connection, call=c.call(op_id="op2"))
        assert isinstance(served, ServedGroup)
        assert served.anchor is None
        assert served.anchor_vacated is True
        assert [record.uuid for record in served.journal_entries] == [member]
        assert await c.authorization_rows(served.group_id) == []


async def test_an_orphan_group_reports_no_anchor_and_no_vacating(tmp_path: Path) -> None:
    """`anchor: null` with `anchor_vacated: false` is the other of the two situations."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert served.anchor is None
        assert served.anchor_vacated is False


async def test_a_member_whose_version_moved_is_delivered_at_its_current_version(
    tmp_path: Path,
) -> None:
    """A primary agent's repair reaches the consolidator rather than being hidden from it, which is
    the outcome D11 wants — and the payload carries the version whose prose it actually contains,
    because that is the version the receipt is minted at."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        await c.amend(member, gist=_A[0], content="repaired content for the drift")
        served = await serving.next_group(c.harness.store.connection, call=c.call(op_id="op2"))
        assert isinstance(served, ServedGroup)
        assert served.journal_entries[0].expected_version == 2
        assert served.journal_entries[0].content == "repaired content for the drift"
        assert await c.member_rows(served.group_id) == [(member, 1, 2, None)]


async def test_remaining_groups_counts_the_other_open_groups(tmp_path: Path) -> None:
    """Counted after this serve's transitions and **excluding** the group being delivered, so a
    final group reports 0 and the skill can tell "this is the last one" from the payload alone."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0)
        await c.write(gist=_C[0], content=_C[1], minute=3, degrees=180.0)
        first = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(first, ServedGroup)
        assert first.remaining_groups == 2


async def test_an_empty_store_answers_done(tmp_path: Path) -> None:
    """`architecture.md`'s empty-store table: `next_group` → `{done: true}`. An answer, not an
    error."""
    async with consolidator(tmp_path) as c:
        assert isinstance(
            await serving.next_group(c.harness.store.connection, call=c.call()), RunDone
        )


async def test_two_identical_stores_serve_byte_identical_payloads(tmp_path: Path) -> None:
    """Planning is a pure function of the store plus the effective config, so the same inputs
    produce the same first delivery — asserted on the whole payload minus the ids, which are uuid4
    by construction and are the one thing that legitimately differs."""

    async def first_payload(path: Path) -> str:
        path.mkdir()
        async with consolidator(path) as c:
            for index, (gist, content) in enumerate((_A, _B, _C)):
                await c.write(gist=gist, content=content, minute=index, degrees=index * 10.0)
            served = await serving.next_group(c.harness.store.connection, call=c.call())
            assert isinstance(served, ServedGroup)
            return dumps(
                {
                    "entries": [
                        (record.gist, record.expected_version) for record in served.journal_entries
                    ],
                    "candidates": [
                        (ranked.rank, ranked.record.gist) for ranked in served.candidates
                    ],
                    "shard": (served.shard.index, served.shard.of),
                    "n_gists_used": served.n_gists_used,
                    "remaining_groups": served.remaining_groups,
                }
            )

    assert await first_payload(tmp_path / "one") == await first_payload(tmp_path / "two")


async def test_serving_walks_every_group_of_the_run_in_order(tmp_path: Path) -> None:
    """Groups are processed oldest-first in `(order_key, shard_index)`, which is what makes D29's
    transitive merging true: the store updates as it goes, so a later group can merge into a record
    an earlier group just created."""
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0)
        third = await c.write(gist=_C[0], content=_C[1], minute=3, degrees=180.0)
        delivered: list[str] = []
        for index in range(3):
            served = await serving.next_group(
                c.harness.store.connection, call=c.call(op_id=f"s{index}")
            )
            assert isinstance(served, ServedGroup)
            delivered.append(served.journal_entries[0].uuid)
            await c.harness.store.connection.execute(
                "UPDATE consolidation_group SET status = 'complete' WHERE group_id = ?",
                (served.group_id,),
            )
            await c.harness.store.connection.commit()
        assert delivered == [first, second, third]


@pytest.mark.parametrize("field_name", ["holder_session", "holder_pid", "expires_at"])
def test_the_busy_shape_carries_the_three_fields_the_design_names(field_name: str) -> None:
    """`holder_pid` in particular, so same-session contention is diagnosable rather than silent."""
    busy = Busy(holder_session="s", holder_pid=1, expires_at="2026-01-01T00:00:00+00:00")
    assert hasattr(busy, field_name)
