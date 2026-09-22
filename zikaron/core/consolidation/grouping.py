"""D29's grouping algorithm: anchor by retrieval, cluster the orphans, then partition for cohesion.

`design/consolidation.md` §"Mechanism: retrieval is the adjacency function, everywhere" is
normative.

**Planning is a pure function of the store plus the effective config.** Same store, same parameters,
same groups, every time — which is not decoration: a nondeterministic partition changes what the
model is asked, so two runs could reach different long-term records from identical inputs and
neither would be reproducible. Everything here is therefore either a total order or a deterministic
scan, and no step consults a clock, a hash seed or an iteration order the store does not fix.

**The two halves are not symmetric, and that asymmetry is the design.** Journal → long-term
adjacency *is* retrieval, needing only a rank scan and a floor. Journal → journal grouping is
clustering, which needs a threshold, a linkage rule and an ordering — and is the half that gets
dropped. It cannot be avoided, only shrunk: as the long-term tier fills, most entries anchor and
never reach the clustering code at all.

**Mutual-K does not prevent chaining.** Connected components over mutual edges are still single
linkage over those edges, so `A↔B↔C` is one component with or without mutuality: mutuality raises
the bar for an *edge*, and a chain is built from edges that each clear it. The complete-linkage
pass is what prevents it, which is why the `A~B`, `B~C`, `A≁C` case is an acceptance test *of that
pass*. Complete linkage over-splits, deliberately: an over-split costs one extra consolidator call,
because groups are processed oldest-first against a store that updates as it goes and a later group
can still merge into what an earlier one created — while an under-split fuses two unrelated lessons
into one record that is false in both directions.

**No embedding call happens here.** Both arms of every query in this module are internal: the dense
side reuses the querying row's stored first-chunk vector and the lexical side is its own
`gist + content` through the same term constructor an external query uses. That is what lets
planning run inside one transaction and be a function of the store rather than of a second
inference.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import aiosqlite

from zikaron.core.consolidation.context import ConsolidationCall
from zikaron.core.consolidation.groups import Shard
from zikaron.core.retrieval.eligibility import Consumer, Scope
from zikaron.core.retrieval.query import internal_query
from zikaron.core.retrieval.retrieve import retrieve
from zikaron.core.retrieval.similarity import directed_cosines

#: What separates the two halves of `consolidation_group.order_key`. Any character outside the
#: timestamp's own alphabet would do; `|` is the literal the schema's column comment names.
_ORDER_KEY_SEPARATOR: Final = "|"


@dataclass(frozen=True, slots=True)
class Entry:
    """One unconsolidated journal row as the planner sees it: its identity, order and version.

    `version` is the plan-time version, which becomes `consolidation_group_member.version_seen` —
    change detection only. The prose is deliberately absent: the planner decides *which* rows group
    together, and the payload that carries prose is rebuilt at serve time from rows that may have
    moved since.
    """

    uuid: str
    created_at: str
    version: int

    @property
    def order(self) -> tuple[str, str]:
        """This entry's position in group order: `(created_at, uuid)`."""
        return (self.created_at, self.uuid)


@dataclass(frozen=True, slots=True)
class PlannedGroup:
    """One group as the planner produced it, before anything is written.

    A value type rather than rows inserted as they are computed, so that the whole partition exists
    before any of it is persisted — which is what lets invariant 19's set-level condition be a
    property of a computed plan rather than of a half-written table.
    """

    anchor_uuid: str | None
    order_key: str
    shard: Shard
    members: tuple[Entry, ...]


def order_key(members: Sequence[Entry]) -> str:
    """`'earliest_created_at|min_uuid'` of a **pre-shard** group, per the schema's column comment.

    Computed over the pre-shard members so every shard of one group carries the same key, sorts
    adjacently, and is ordered among its siblings by `shard_index` — which is the only reason step
    3's total order needs a third component at all.

    It also identifies the pre-shard group, which is what invariant 19 rests on: cohesive subgroups
    and anchored member sets are disjoint, so no two of them in one run can share a minimum uuid.

    Raises:
        ValueError: `members` is empty. A group with no members has no order and could not be
        served; refusing to name one is what keeps an empty group from being written at all.
    """
    if not members:
        raise ValueError("a group with no members has no order key")
    earliest = min(member.created_at for member in members)
    smallest = min(member.uuid for member in members)
    return f"{earliest}{_ORDER_KEY_SEPARATOR}{smallest}"


def shard(
    members: Sequence[Entry], *, group_max: int
) -> tuple[tuple[Shard, tuple[Entry, ...]], ...]:
    """Split one pre-shard group into consecutive shards of at most `group_max` members.

    "Consecutive in the group's own order" is the whole partition rule, so `members` must already be
    in group order — the same order the caller computed `order_key` from — and the same group always
    shards the same way. Indices are 1-based and `of` is the total, so an unsplit group is
    `{index: 1, of: 1}` rather than a third convention meaning "not sharded".

    Both numbers are returned, and both are persisted by the caller, because `of` cannot be
    recovered later: recomputing it would mean replanning a group whose membership is frozen,
    against a store that has since moved.
    """
    total = -(-len(members) // group_max)
    return tuple(
        (
            Shard(index=index, of=total),
            tuple(members[start : start + group_max]),
        )
        for index, start in enumerate(range(0, len(members), group_max), start=1)
    )


async def journal_entries(db: aiosqlite.Connection) -> tuple[Entry, ...]:
    """Every unconsolidated journal row, in group order — the universe this pass partitions.

    Not one of `eligibility`'s five consumers, and deliberately not routed through it: those five
    are *candidate pools* narrowed by the legality condition of the action they are retrieved for,
    while this is the set of rows being *assigned* to groups. The predicate is nonetheless
    identical to `Consumer.ORPHAN`'s narrowing, because both express the same fact — an
    unconsolidated journal row is exactly what can become a group member — and a test asserts the
    two agree on a fixture holding rows in every state, so the two statements cannot drift apart.
    """
    rows = await db.execute_fetchall(
        "SELECT uuid, created_at, version FROM memory "
        "WHERE tier = 'journal' AND active = 1 "
        "ORDER BY created_at ASC, uuid ASC"
    )
    return tuple(
        Entry(uuid=str(uuid), created_at=str(created_at), version=int(str(version)))
        for uuid, created_at, version in rows
    )


async def anchor_for(
    db: aiosqlite.Connection, entry: Entry, *, call: ConsolidationCall
) -> str | None:
    """The long-term record `entry` anchors to, or `None` if none clears `anchor_cutoff`.

    The hybrid decides *which* records are candidates and in what order; the floor decides which of
    them is close enough. The scan takes the **highest-ranked record that clears the floor** rather
    than gating rank 1 alone — `consolidation.md` step 1 fixes that reading, because RRF fuses two
    arms while `s` is a dense quantity, so a record the lexical arm alone surfaced can outrank one
    with a far higher directed cosine, and the two readings give different partitions.

    Candidates are restricted to `tier='long_term' AND active=1` (`Consumer.CONSOLIDATION`): every
    record shown here is one `merge` may be asked to rewrite, and rewriting a historical row is
    incoherent, since `superseded_by` is immutable once set.

    Assumes the caller's own open transaction.
    """
    query = await internal_query(
        db, memory_uuid=entry.uuid, max_terms=call.retrieval.fts_query_max_terms
    )
    retrieved = await retrieve(
        db, query=query, scope=Scope(Consumer.CONSOLIDATION), settings=call.retrieval
    )
    cosines = await directed_cosines(db, retrieved.pool, query=query)
    for ranked in retrieved.pool:
        cosine = cosines.get(ranked.row.uuid)
        if cosine is not None and cosine >= call.settings.anchor_cutoff:
            return ranked.row.uuid
    return None


async def neighbours_of(
    db: aiosqlite.Connection, entry: Entry, *, call: ConsolidationCall
) -> Mapping[str, float]:
    """`entry`'s top-`mutual_k` journal neighbours, each with `s(entry → neighbour)`.

    The candidate pool is `tier='journal' AND active=1` excluding `entry` itself
    (`Consumer.ORPHAN`) — **every** unconsolidated journal row, not only the orphans, because that
    filter *is* the definition of a group member and adding a narrower one would be a filter the
    design's own table does not list. The consequence is worth stating rather than discovering: an
    entry that anchored can occupy one of the K ranks and can never become an edge, since edges are
    drawn only between two orphans. Excluding self is not pedantry either — a memory is its own
    nearest neighbour, so without it every row would spend a slot on itself.

    Returns:
        The top `mutual_k` of the fused pool, mapped to their directed cosines. Rank is what the cut
        is by; the cosine is what the floor is against. A neighbour with no computable cosine — no
        stored vector at all, which invariant 12 makes unreachable for an active row — is omitted
        rather than admitted at an invented score.
    """
    query = await internal_query(
        db, memory_uuid=entry.uuid, max_terms=call.retrieval.fts_query_max_terms
    )
    retrieved = await retrieve(
        db,
        query=query,
        scope=Scope(Consumer.ORPHAN, exclude_uuid=entry.uuid),
        settings=call.retrieval,
    )
    cosines = await directed_cosines(db, retrieved.pool, query=query)
    top = retrieved.pool[: call.settings.mutual_k]
    return {
        ranked.row.uuid: cosines[ranked.row.uuid] for ranked in top if ranked.row.uuid in cosines
    }


def mutual_edges(
    neighbours: Mapping[str, Mapping[str, float]], *, cutoff: float
) -> Mapping[str, frozenset[str]]:
    """The undirected mutual-K graph over the orphans, as an adjacency map.

    An edge `A↔B` exists only when **both** conditions hold: `A` is in `B`'s top-`mutual_k` *and*
    `B` is in `A`'s, and `min(s(A → B), s(B → A)) ≥ cutoff`.

    **The directionality is not pedantry.** `s(X → Y)` is X's first chunk against Y's *best* chunk,
    so it is asymmetric whenever the two rows have different chunk counts — X offers one vector, Y
    offers its best of many. A spec written as `cos(A, B)` would leave two conforming
    implementations free to pick different directions, which changes which edges exist and
    therefore which groups the consolidator is shown. `min` is the right symmetrization for the
    same reason the test already demands mutuality: an edge should require agreement from both
    endpoints, and the conservative direction is the safe one.

    **The floor is not redundant with mutuality.** In a journal of six rows with `mutual_k = 5`
    every row is in every other row's top five, so the mutual graph is complete and the whole
    journal fuses into one group. Rank says *which* neighbours are closest; the floor says
    *whether* they are close.

    Args:
        neighbours: each orphan's own top-K map, keyed by orphan uuid. A uuid appearing only as a
            *value* is not an orphan — an entry that anchored, or one whose own map was never
            computed — so it can never form an edge, which is what restricts the graph to the set
            being clustered without a second filter.
    """
    edges: dict[str, set[str]] = {uuid: set() for uuid in neighbours}
    for source, reachable in neighbours.items():
        for target, forward in reachable.items():
            back = neighbours.get(target, {}).get(source)
            if back is not None and min(forward, back) >= cutoff:
                edges[source].add(target)
                edges[target].add(source)
    return {uuid: frozenset(adjacent) for uuid, adjacent in edges.items()}


def components(
    orphans: Sequence[Entry], edges: Mapping[str, frozenset[str]]
) -> tuple[tuple[Entry, ...], ...]:
    """Connected components of the mutual graph, each in group order, the components themselves too.

    A cheap and correct *prefilter*: anything not in one component can never be grouped. It is not
    the answer, because components are single linkage over the accepted edges — `A↔B` and `B↔C` put
    `A` and `C` together even when they share no edge — which is what `cohesive_subgroups` then
    partitions.

    Deterministic by construction: the seed order is `orphans`' own group order and each component
    is grown by scanning that same order, so no set iteration reaches the result.
    """
    by_uuid = {entry.uuid: entry for entry in orphans}
    seen: set[str] = set()
    found: list[tuple[Entry, ...]] = []
    for entry in orphans:
        if entry.uuid in seen:
            continue
        member_uuids: list[str] = []
        frontier = [entry.uuid]
        seen.add(entry.uuid)
        while frontier:
            current = frontier.pop()
            member_uuids.append(current)
            for adjacent in sorted(edges.get(current, frozenset())):
                if adjacent not in seen and adjacent in by_uuid:
                    seen.add(adjacent)
                    frontier.append(adjacent)
        found.append(tuple(sorted((by_uuid[uuid] for uuid in member_uuids), key=lambda e: e.order)))
    return tuple(found)


def cohesive_subgroups(
    component: Sequence[Entry], edges: Mapping[str, frozenset[str]]
) -> tuple[tuple[Entry, ...], ...]:
    """Partition one component by **complete linkage**, deterministically.

    Order members by `(created_at, uuid)`; seed a subgroup with the earliest unassigned member; add
    a candidate — in that same order — only if it has a mutual edge to **every** member already in
    the subgroup; when nothing more can be added, close it and seed the next subgroup from the
    earliest remaining member. Repeat until every member is assigned.

    One pass per subgroup is enough rather than an approximation: the requirement only ever tightens
    as members are added, so a candidate rejected against a smaller subgroup cannot qualify against
    a larger one.

    On the `A↔B↔C` chain this yields `{A, B}` and `{C}`, which is the acceptance test. The chain has
    to be *prevented* rather than merely detected: `A` and `C` share no edge, so a partition that
    put them together would hand the consolidator one group asserting a relation nothing measured.
    """
    remaining = sorted(component, key=lambda entry: entry.order)
    subgroups: list[tuple[Entry, ...]] = []
    while remaining:
        subgroup = [remaining[0]]
        deferred: list[Entry] = []
        for candidate in remaining[1:]:
            if all(candidate.uuid in edges.get(member.uuid, frozenset()) for member in subgroup):
                subgroup.append(candidate)
            else:
                deferred.append(candidate)
        subgroups.append(tuple(subgroup))
        remaining = deferred
    return tuple(subgroups)


def _anchored_sets(
    entries: Sequence[Entry], anchors: Mapping[str, str]
) -> tuple[tuple[str, tuple[Entry, ...]], ...]:
    """Entries sharing an anchor, as one pre-shard group each, in group order.

    No cohesion pass runs over these, and that asymmetry is deliberate: the anchor *is* the cohesion
    criterion, since every member cleared `anchor_cutoff` against the same record, so the group
    already has a common centre. Complete linkage among the members would split that set on
    member-to-member similarity the decision does not rest on. Step 2's pass exists precisely
    because an orphan set has no common centre.
    """
    grouped: dict[str, list[Entry]] = {}
    for entry in entries:
        anchor = anchors.get(entry.uuid)
        if anchor is not None:
            grouped.setdefault(anchor, []).append(entry)
    return tuple((anchor, tuple(members)) for anchor, members in grouped.items())


async def plan(db: aiosqlite.Connection, *, call: ConsolidationCall) -> tuple[PlannedGroup, ...]:
    """Partition the whole journal into the groups one run will serve, in step 3's total order.

    Anchored groups and cohesive orphan subgroups are computed independently and then sharded by the
    same rule, because both are pre-shard groups. The result is sorted by `(order_key,
    shard_index)`, which is D29's step-3 order: oldest first, with the uuid tiebreak load-bearing
    rather than decorative — concurrent writes really do share a `created_at` string.

    Assumes the caller's own open transaction, since every step reads the store and the plan must
    describe one snapshot of it.

    Returns:
        Every group to be written, possibly empty — an empty journal plans no groups, which is a run
        that is immediately complete rather than an error.
    """
    entries = await journal_entries(db)
    anchors: dict[str, str] = {}
    for entry in entries:
        anchor = await anchor_for(db, entry, call=call)
        if anchor is not None:
            anchors[entry.uuid] = anchor

    orphans = tuple(entry for entry in entries if entry.uuid not in anchors)
    neighbours = {orphan.uuid: await neighbours_of(db, orphan, call=call) for orphan in orphans}
    edges = mutual_edges(neighbours, cutoff=call.settings.orphan_edge_cutoff)

    pre_shard: list[tuple[str | None, tuple[Entry, ...]]] = [
        (anchor, members) for anchor, members in _anchored_sets(entries, anchors)
    ]
    for component in components(orphans, edges):
        pre_shard.extend((None, subgroup) for subgroup in cohesive_subgroups(component, edges))

    planned = [
        PlannedGroup(
            anchor_uuid=anchor,
            order_key=order_key(members),
            shard=shard_of,
            members=shard_members,
        )
        for anchor, members in pre_shard
        for shard_of, shard_members in shard(members, group_max=call.settings.group_max)
    ]
    return tuple(sorted(planned, key=lambda group: (group.order_key, group.shard.index)))
