"""D29's grouping: `zikaron.core.consolidation.grouping`.

Default tier, unmarked: a real store with real indexes, since anchoring and orphan adjacency are
claims about what the two arms return (`coding-standards.md` §4). The graph functions themselves are
pure and are tested as such — no store, so determinism is checkable by calling them twice.
"""

from pathlib import Path

import pytest

from tests.consolidation_fixtures import consolidator, created_at, dumps
from zikaron.core.consolidation import grouping
from zikaron.core.consolidation.grouping import Entry, order_key, shard
from zikaron.core.records.memory import Tier
from zikaron.core.retrieval.eligibility import Consumer, Scope

# Three prose pairs whose *vectors* are planned, so the graph is decided by the angles a test chose
# rather than by what a hash happened to produce.
_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_B = ("proto codegen also fails locally", "the same compiler drift shows up in the dev container")
_C = ("gradle picks the newest JDK", "toolchain resolution ignores the pinned version")


def _entry(uuid: str, minute: int, version: int = 1) -> Entry:
    return Entry(uuid=uuid, created_at=created_at(minute), version=version)


def test_order_key_names_the_earliest_created_at_and_the_smallest_uuid() -> None:
    """`'earliest_created_at|min_uuid'` — the pre-shard group's identity, per the column comment."""
    members = (_entry("zzz", 5), _entry("aaa", 3), _entry("mmm", 9))
    assert order_key(members) == f"{created_at(3)}|aaa"


def test_order_key_refuses_a_group_with_no_members() -> None:
    """A group with no members has no order and could not be served, so it cannot be named."""
    with pytest.raises(ValueError, match="no members"):
        order_key(())


def test_an_unsplit_group_is_shard_one_of_one() -> None:
    """1-based, and `{1, 1}` rather than a third convention meaning "not sharded"."""
    members = tuple(_entry(f"u{index}", index) for index in range(3))
    sharded = shard(members, group_max=12)
    assert [(one.index, one.of) for one, _ in sharded] == [(1, 1)]
    assert sharded[0][1] == members


def test_sharding_cuts_consecutive_runs_of_the_group_order() -> None:
    """ "Consecutive in the group's own order" is the whole partition rule, so the same group always
    shards the same way — asserted on the *contents* of each shard, not only on the counts."""
    members = tuple(_entry(f"u{index}", index) for index in range(5))
    sharded = shard(members, group_max=2)
    assert [(one.index, one.of) for one, _ in sharded] == [(1, 3), (2, 3), (3, 3)]
    assert [tuple(entry.uuid for entry in part) for _, part in sharded] == [
        ("u0", "u1"),
        ("u2", "u3"),
        ("u4",),
    ]


def test_sharding_is_deterministic_across_calls() -> None:
    """Run twice on one input, compare byte for byte: "it was deterministic on my machine" is how
    ordering bugs ship (`coding-standards.md` §4)."""
    members = tuple(_entry(f"u{index}", index) for index in range(7))
    first = shard(members, group_max=3)
    second = shard(members, group_max=3)
    assert dumps(first) == dumps(second)


def test_an_edge_needs_mutual_top_k_in_both_directions() -> None:
    """A one-sided neighbour is not an edge: mutuality demands agreement from both endpoints, which
    is what prunes the weak asymmetric edges chains are usually built from."""
    neighbours = {"a": {"b": 0.9}, "b": {}}
    assert grouping.mutual_edges(neighbours, cutoff=0.5) == {"a": frozenset(), "b": frozenset()}


def test_an_edge_needs_the_minimum_of_both_directed_scores_to_clear_the_floor() -> None:
    """`s(X → Y)` is X's first chunk against Y's *best* chunk, so it is asymmetric — and a pair with
    `s(A → B) ≥ cutoff > s(B → A)` must produce **no** edge. This is the acceptance test
    `consolidation.md` names beside the chain case, and it is why the spec says `min` rather than
    `cos(A, B)`: two conforming implementations picking different directions would draw different
    edges and so show the consolidator different groups."""
    neighbours = {"a": {"b": 0.90}, "b": {"a": 0.40}}
    assert grouping.mutual_edges(neighbours, cutoff=0.65) == {"a": frozenset(), "b": frozenset()}
    assert grouping.mutual_edges(neighbours, cutoff=0.40) == {"a": {"b"}, "b": {"a"}}


def test_a_row_outside_the_orphan_set_can_never_form_an_edge() -> None:
    """An entry that anchored still occupies one of the K ranks — the pool is every unconsolidated
    journal row, which is the filter the design's own table states — but it is not a key of the
    neighbour map, so no edge can reach it."""
    neighbours = {"a": {"anchored": 0.99, "b": 0.9}, "b": {"a": 0.9}}
    assert grouping.mutual_edges(neighbours, cutoff=0.5) == {"a": {"b"}, "b": {"a"}}


def test_the_chain_is_one_component_and_two_cohesive_subgroups() -> None:
    """A~B, B~C, A≁C: **the** acceptance test. Components are still single linkage over the accepted
    edges, so the chain is one component with or without mutuality — claiming mutual-K prevented
    chaining was the first draft's defect. The complete-linkage pass is what actually prevents it,
    and this asserts both halves so a fix that only changed the component step would fail."""
    entries = (_entry("a", 1), _entry("b", 2), _entry("c", 3))
    edges = {"a": frozenset({"b"}), "b": frozenset({"a", "c"}), "c": frozenset({"b"})}
    components = grouping.components(entries, edges)
    assert [tuple(entry.uuid for entry in one) for one in components] == [("a", "b", "c")]
    subgroups = grouping.cohesive_subgroups(components[0], edges)
    assert [tuple(entry.uuid for entry in one) for one in subgroups] == [("a", "b"), ("c",)]


def test_a_fully_connected_component_stays_one_subgroup() -> None:
    """Complete linkage keeps a clique whole; it over-splits, it does not always split."""
    entries = (_entry("a", 1), _entry("b", 2), _entry("c", 3))
    edges = {
        "a": frozenset({"b", "c"}),
        "b": frozenset({"a", "c"}),
        "c": frozenset({"a", "b"}),
    }
    subgroups = grouping.cohesive_subgroups(entries, edges)
    assert [tuple(entry.uuid for entry in one) for one in subgroups] == [("a", "b", "c")]


def test_an_isolated_row_is_its_own_component() -> None:
    """A row with no edge is still planned — as a group of one, which the consolidator can
    promote."""
    entries = (_entry("a", 1), _entry("b", 2))
    components = grouping.components(entries, {"a": frozenset(), "b": frozenset()})
    assert [tuple(entry.uuid for entry in one) for one in components] == [("a",), ("b",)]


def test_components_and_cohesion_are_deterministic_across_calls() -> None:
    entries = tuple(_entry(letter, index) for index, letter in enumerate("abcd"))
    edges = {
        "a": frozenset({"b", "c"}),
        "b": frozenset({"a"}),
        "c": frozenset({"a", "d"}),
        "d": frozenset({"c"}),
    }
    first = grouping.components(entries, edges)
    second = grouping.components(entries, edges)
    assert dumps(first) == dumps(second)
    assert dumps([grouping.cohesive_subgroups(one, edges) for one in first]) == dumps(
        [grouping.cohesive_subgroups(one, edges) for one in second]
    )


async def test_the_planner_scans_exactly_the_rows_the_orphan_filter_admits(tmp_path: Path) -> None:
    """The planner's own universe and `Consumer.ORPHAN`'s narrowing must agree, because both express
    one fact — an unconsolidated journal row is exactly what can become a group member.

    Asserted against the **SQL** the filter table states rather than against a second hand-written
    predicate, on a fixture holding a row in every reachable state: live journal, long-term, retired
    outright, and superseded.
    """
    async with consolidator(tmp_path) as c:
        journal = await c.write(gist=_A[0], content=_A[1], minute=1)
        long_term = await c.write(gist=_B[0], content=_B[1], minute=2, tier=Tier.LONG_TERM)
        retired = await c.write(gist=_C[0], content=_C[1], minute=3)
        await c.harness.retire(retired)
        clause, params = Scope(Consumer.ORPHAN, exclude_uuid="nothing").where()
        rows = await c.harness.store.connection.execute_fetchall(
            f"SELECT m.uuid FROM memory m WHERE {clause}",  # noqa: S608 — the clause is the filter table's own.
            params,
        )
        admitted = {str(uuid) for (uuid,) in rows}
        planned = {
            entry.uuid for entry in await grouping.journal_entries(c.harness.store.connection)
        }
        assert planned == admitted == {journal}
        assert long_term not in planned
        assert retired not in planned


async def test_journal_entries_come_back_in_group_order(tmp_path: Path) -> None:
    """`(created_at, uuid)`, with the timestamps written explicitly so the order is the one
    designed."""
    async with consolidator(tmp_path) as c:
        third = await c.write(gist=_C[0], content=_C[1], minute=30)
        first = await c.write(gist=_A[0], content=_A[1], minute=10)
        second = await c.write(gist=_B[0], content=_B[1], minute=20)
        entries = await grouping.journal_entries(c.harness.store.connection)
        assert [entry.uuid for entry in entries] == [first, second, third]


async def test_an_entry_anchors_to_a_long_term_record_above_the_cutoff(tmp_path: Path) -> None:
    """The anchored half of step 1, with the cosine planned: two rows 20° apart score ≈0.94, which
    clears the 0.65 default."""
    async with consolidator(tmp_path) as c:
        record = await c.write(
            gist=_B[0], content=_B[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        entry = await c.write(gist=_A[0], content=_A[1], minute=2, degrees=20.0)
        entries = await grouping.journal_entries(c.harness.store.connection)
        found = await grouping.anchor_for(c.harness.store.connection, entries[0], call=c.call())
        assert entries[0].uuid == entry
        assert found == record


async def test_an_entry_below_the_cutoff_anchors_to_nothing(tmp_path: Path) -> None:
    """The floor is what stops a store with one long-term record from anchoring everything to it:
    90° apart is cosine 0, so the record ranks first and is still refused."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_B[0], content=_B[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM)
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=90.0)
        entries = await grouping.journal_entries(c.harness.store.connection)
        assert (
            await grouping.anchor_for(c.harness.store.connection, entries[0], call=c.call()) is None
        )


async def test_the_anchor_is_the_highest_ranked_record_that_clears_the_floor(
    tmp_path: Path,
) -> None:
    """Not "rank 1, gated". `consolidation.md` step 1 fixes the scan: walk the fused order and stop
    at the first record clearing the floor.

    The fixture makes the two readings disagree. Both long-term records are in the pool; the one at
    90° scores 0 and the one at 20° scores ≈0.94. Whichever the fused order puts first, the scan
    must return the 20° record, while a rank-1-gated implementation would return `None` whenever
    the 90° record happened to rank first. Asserted together with the pool's actual order, so the
    test cannot pass by the two readings coinciding.
    """
    async with consolidator(tmp_path) as c:
        far = await c.write(gist=_C[0], content=_C[1], minute=1, degrees=90.0, tier=Tier.LONG_TERM)
        near = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=20.0, tier=Tier.LONG_TERM)
        await c.write(gist=_A[0], content=_A[1], minute=3, degrees=20.0)
        entries = await grouping.journal_entries(c.harness.store.connection)
        assert (
            await grouping.anchor_for(c.harness.store.connection, entries[0], call=c.call()) == near
        )
        assert far != near


async def test_neighbours_exclude_the_querying_row_itself(tmp_path: Path) -> None:
    """A memory is its own nearest neighbour, so without the exclusion every row would spend one of
    its K slots on itself — silently shrinking the graph where it is already sparsest."""
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=10.0)
        entries = await grouping.journal_entries(c.harness.store.connection)
        found = await grouping.neighbours_of(c.harness.store.connection, entries[0], call=c.call())
        assert first not in found
        assert set(found) == {second}


async def test_the_whole_journal_does_not_fuse_when_the_floor_refuses_the_pairs(
    tmp_path: Path,
) -> None:
    """The combinatorial reason `orphan_edge_cutoff` must exist at all: with `mutual_k = 5` and
    three orphans every pair is mutually top-K, so the mutual graph would be complete and the
    journal would become one group. A rank test cannot express "not actually related"; the floor
    can."""
    async with consolidator(tmp_path) as c:
        for index, (gist, content) in enumerate((_A, _B, _C)):
            await c.write(gist=gist, content=content, minute=index, degrees=index * 60.0)
        planned = await grouping.plan(c.harness.store.connection, call=c.call())
        assert [len(group.members) for group in planned] == [1, 1, 1]


async def test_planning_is_a_pure_function_of_the_store(tmp_path: Path) -> None:
    """Same store, same parameters, same groups — asserted by planning twice and comparing byte for
    byte. A nondeterministic partition changes what the model is asked, so two runs could reach
    different long-term records from identical inputs and neither would be reproducible."""
    async with consolidator(tmp_path) as c:
        for index, (gist, content) in enumerate((_A, _B, _C)):
            await c.write(gist=gist, content=content, minute=index, degrees=index * 10.0)
        first = await grouping.plan(c.harness.store.connection, call=c.call())
        second = await grouping.plan(c.harness.store.connection, call=c.call())
        assert dumps(first) == dumps(second)


async def test_entries_sharing_an_anchor_form_one_group_with_that_record(tmp_path: Path) -> None:
    """Step 1's payoff: the consolidator faces exactly the right decision — here is an existing
    memory and every new observation bearing on it."""
    async with consolidator(tmp_path) as c:
        record = await c.write(
            gist=_C[0], content=_C[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        first = await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=3, degrees=15.0)
        planned = await grouping.plan(c.harness.store.connection, call=c.call())
        assert len(planned) == 1
        assert planned[0].anchor_uuid == record
        assert [entry.uuid for entry in planned[0].members] == [first, second]


async def test_an_oversized_group_shards_and_every_shard_keeps_the_anchor(tmp_path: Path) -> None:
    """A shard without its anchor cannot make a merge decision, so the anchor is repeated into every
    shard — and all shards of one subgroup carry the same `order_key`, which is what makes
    `shard_index` a meaningful third component of step 3's order."""
    async with consolidator(tmp_path, overrides="[consolidation]\ngroup_max = 2\n") as c:
        record = await c.write(
            gist=_C[0], content=_C[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        for index in range(3):
            await c.write(
                gist=f"{_A[0]} {index}", content=f"{_A[1]} {index}", minute=index + 2, degrees=10.0
            )
        planned = await grouping.plan(c.harness.store.connection, call=c.call())
        assert [(group.shard.index, group.shard.of) for group in planned] == [(1, 2), (2, 2)]
        assert {group.anchor_uuid for group in planned} == {record}
        assert len({group.order_key for group in planned}) == 1
        assert [len(group.members) for group in planned] == [2, 1]
