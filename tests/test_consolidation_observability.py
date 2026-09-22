"""The guards whose effect is only *sometimes* observable, and the fixtures that make it observable.

Every test here exists because a deliberate one-line mutation of the code it defends **survived**
the rest of the suite. The lesson repeated: a fixture where two rules coincide cannot
tell them apart, so the tiebreak that only decides a tie needs a tie, the scan that only differs
from a gate when rank 1 fails the floor needs rank 1 to fail the floor, and the exclusion that only
bites once a member has become long-term needs a member that has.

Kept together rather than filed beside their subjects, because what they have in common is the
reason they exist — and because a later session adding a fixture should know that the ones here are
shaped the way they are on purpose.
"""

from pathlib import Path

from tests.consolidation_fixtures import consolidator, created_at, detail_of
from zikaron.core.consolidation import grouping, groups, planning, serving, verbs
from zikaron.core.consolidation.groups import GroupStatus
from zikaron.core.consolidation.payload import NamedRow, RunDone, ServedGroup
from zikaron.core.records.memory import Rewrite, Tier
from zikaron.core.retrieval.eligibility import Consumer, Scope
from zikaron.core.retrieval.query import internal_query
from zikaron.core.retrieval.retrieve import retrieve

_A = ("alpha bravo", "charlie delta")
_B = ("echo foxtrot", "golf hotel")


def test_group_order_pins_both_components_of_its_own_sql() -> None:
    """The tiebreak's *mechanism*, asserted alongside the behavioural test below.

    `retrieval.md`'s own lesson: for an invariant whose effect is only sometimes observable — a
    tiebreak the engine may satisfy by accident — assert the mechanism as well as the outcome,
    because a fixture whose timestamps are all distinct will pass either way and SQLite's natural
    order may agree with uuid order by luck.
    """
    assert groups._MEMBER_ORDER == "ORDER BY m.created_at ASC, mem.memory_uuid ASC"


async def test_members_sharing_a_created_at_are_ordered_by_uuid(tmp_path: Path) -> None:
    """The behavioural half. Concurrent writes really do share a `created_at` string, so the uuid is
    part of group order rather than a tiebreak applied where a collision was noticed — and with it
    gone the order of two same-instant members would fall to the query plan.

    Both members are given the **same** timestamp deliberately, which is the only fixture in which
    the second component of the order decides anything at all.
    """
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=1, degrees=2.0)
        await c.harness.set_created_at(first, created_at(1))
        await c.harness.set_created_at(second, created_at(1))
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert len(served.journal_entries) == 2
        assert [record.uuid for record in served.journal_entries] == sorted((first, second))


async def test_the_anchor_scan_finds_a_record_the_fused_order_ranked_second(
    tmp_path: Path,
) -> None:
    """The scan and a rank-1 gate give **different partitions**, and this is the fixture in which
    they do — so it is the only one that can tell them apart.

    Built so that the fused order and the directed cosine disagree, which is exactly the situation
    `consolidation.md` step 1 says makes the reading load-bearing. The far record shares every
    lexical term with the entry and so takes lexical rank 1, which lifts it above the near record
    under RRF; the near record shares none, and its planned vector puts it 20° from the entry while
    the far record's is 70° away. So rank 1 scores 0.34 and fails the 0.65 floor, while rank 2
    scores 0.94 and clears it: the scan anchors to the near record and a rank-1 gate would orphan
    the entry.
    """
    async with consolidator(tmp_path) as c:
        near = await c.write(
            gist="echo foxtrot", content="golf hotel", minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        far = await c.write(
            gist="alpha bravo",
            content="charlie delta india",
            minute=2,
            degrees=90.0,
            tier=Tier.LONG_TERM,
        )
        await c.write(gist="alpha bravo", content="charlie delta", minute=3, degrees=20.0)
        entries = await grouping.journal_entries(c.harness.store.connection)
        ranked = await _fused_order(c, entries[0])
        assert ranked[0] == far, "the fixture must rank the far record first for this to be a test"
        assert ranked[1] == near
        assert (
            await grouping.anchor_for(c.harness.store.connection, entries[0], call=c.call()) == near
        )


async def _fused_order(c: object, entry: object) -> list[str]:
    """The pool order the anchor scan walks, read through the same construction the scan uses.

    Asserted on in the test above so the fixture's own premise — that the record failing the floor
    ranks *first* — is proven rather than hoped for. A fixture in which rank 1 happened to clear
    the floor would pass under either reading and defend nothing.
    """
    call = c.call()  # type: ignore[attr-defined]
    query = await internal_query(
        c.harness.store.connection,  # type: ignore[attr-defined]
        memory_uuid=entry.uuid,  # type: ignore[attr-defined]
        max_terms=call.retrieval.fts_query_max_terms,
    )
    retrieved = await retrieve(
        c.harness.store.connection,  # type: ignore[attr-defined]
        query=query,
        scope=Scope(Consumer.CONSOLIDATION),
        settings=call.retrieval,
    )
    return [ranked.row.uuid for ranked in retrieved.pool]


async def test_a_serve_refreshes_the_lease(tmp_path: Path) -> None:
    """A delivery is progress, so it buys the lease more time — which is what keeps a consolidator
    working steadily from ever reaching the lapsed-lease path. Asserted on the serve as well as on
    the write verbs, because they are separate call sites and only one of them was covered."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        first = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(first, ServedGroup)
        before = await c.expires_at(first.run_id)
        second = await serving.next_group(c.harness.store.connection, call=c.call(op_id="s2"))
        assert isinstance(second, ServedGroup)
        assert await c.expires_at(first.run_id) > before


async def test_a_member_promoted_in_place_is_not_offered_back_as_a_candidate(
    tmp_path: Path,
) -> None:
    """The exclusion that only bites once a member has become long-term.

    A journal member can never surface as a candidate anyway — the consolidation filter is
    `tier='long_term' AND active=1` — so excluding "every member" appears redundant until a member
    is promoted **in place**, which makes it an active long-term record while leaving it a member
    of the group. On the re-serve it would then be offered back as a candidate for its own group:
    prose the consolidator has already disposed of, and a merge target the authorization set would
    nonetheless have to authorize.
    """
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(
            gist="alpha bravo two", content="charlie delta two", minute=2, degrees=2.0
        )
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert [record.uuid for record in served.journal_entries] == [first, second]
        promoted = await verbs.promote(
            c.harness.store.connection,
            group_id=served.group_id,
            rewrite=Rewrite(gist=_A[0], content=_A[1]),
            absorb=[NamedRow(uuid=first, expected_version=1)],
            call=c.call(op_id="p"),
        )
        assert promoted.uuid == first  # type: ignore[union-attr]
        re_served = await serving.next_group(c.harness.store.connection, call=c.call(op_id="s2"))
        assert isinstance(re_served, ServedGroup)
        assert [record.uuid for record in re_served.journal_entries] == [second]
        assert first not in [ranked.record.uuid for ranked in re_served.candidates]
        assert first not in {uuid for uuid, *_ in await c.authorization_rows(re_served.group_id)}


async def test_a_run_emits_exactly_one_complete_event_however_many_observers_see_it(
    tmp_path: Path,
) -> None:
    """Invariant 17's transitions are guarded updates so they are idempotent under a retry — and
    this is the path where two observers land in one transaction: two groups both vacate out, so
    `close_if_finished` runs after each and the loop's own trailing close runs after that. Only the
    first may transition, and only a transition may emit.

    A second `complete` event would make every signal that counts runs count this one twice.
    """
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        assert len(await c.groups()) == 2
        await c.harness.retire(first)
        await c.harness.retire(second)
        await c.clear_events()
        assert isinstance(
            await serving.next_group(c.harness.store.connection, call=c.call(op_id="s2")), RunDone
        )
        phases = [detail["phase"] for detail in detail_of(await c.events(), "consolidate_run")]
        assert phases == ["complete"]
        assert [group[5] for group in await c.groups()] == [
            GroupStatus.COMPLETE,
            GroupStatus.COMPLETE,
        ]


async def test_the_group_query_charges_the_configured_prefix_against_the_budget(
    tmp_path: Path,
) -> None:
    """The budget is checked on the **assembled** string — prefix, separators and all — never as
    the sum of the pieces' own counts, because a tokenizer re-tokenizes across every join and the
    sum bounds neither direction.

    The prefix is what makes that observable: with a three-token prefix and a five-token cap, the
    first two-token gist fits assembled (3 + 2 = 5) and the second does not (3 + 4 = 7), while a
    check that counted only the gists would keep both and hand the model a sequence it would
    silently truncate. That is the one failure the whole preflight exists to prevent.
    """
    prefix = '[embedding]\nembed_prefix_query = "one two three "\n'
    async with consolidator(tmp_path, overrides=prefix) as c:
        await c.write(gist="alpha one", content="content about alpha", minute=1, degrees=0.0)
        await c.write(gist="beta two", content="content about beta", minute=2, degrees=5.0)
        c.harness.encoder.max_sequence_tokens = 5
        c.harness.encoder.n_special_tokens = 0
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert len(served.journal_entries) == 2
        assert served.n_gists_used == 1


async def test_a_prefix_leaving_no_room_for_any_gist_serves_no_candidates(tmp_path: Path) -> None:
    """The floor of the same rule: `n_gists_used = 0`, and no candidate query is run at all."""
    prefix = '[embedding]\nembed_prefix_query = "one two three "\n'
    async with consolidator(tmp_path, overrides=prefix) as c:
        await c.write(gist=_B[0], content=_B[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM)
        await c.write(gist="alpha one", content="content about alpha", minute=2, degrees=90.0)
        c.harness.encoder.max_sequence_tokens = 3
        c.harness.encoder.n_special_tokens = 0
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert served.n_gists_used == 0
        assert served.candidates == ()
