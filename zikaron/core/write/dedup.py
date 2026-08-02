"""D15's write-time dedup: search after the write, hand back candidates, never block it.

`architecture.md`'s `zikaron_remember` contract is normative. After a row is written, this module
runs the same hybrid search the read path runs — reusing the new row's own first-chunk embedding
for the dense arm and its own `gist + content` for the lexical one, so the search costs no second
embed call — and reports up to `dedup_max` near-duplicates at or above `dedup_threshold`, each a
row the agent may choose to resolve by amending it and retiring the one just created. The search
runs **inside the same transaction** as the write it reports on, because it queries the vectors
that write just inserted, and it never rejects: `zikaron_remember` "writes unconditionally, then
reports" is D32's never-lose guarantee, and refusing a write on a dedup match would be exactly the
prevention D15 explicitly declines to do.

**`dedup_threshold` is a floor on `s(new row → candidate)`, and that quantity is exact, not
whatever the dense arm's bounded overfetch happened to surface.** `schema.md` §"Configuration
keys" defines `s(X → Y)` as the *best* cosine between X's first chunk and **any** chunk of Y —
a mathematical fact about the two rows' stored vectors, with no dependence on `fusion_depth` or on
which arm found Y. The fused pool's own hybrid search decides *which* rows are candidates; the
directed cosine, computed exactly, decides whether each candidate clears the floor. A candidate the
dense arm's overfetch loop placed within `fusion_depth` already carries its own exact minimum
distance as `RankedMemory.best_distance` — no second query needed for those. A candidate the
**lexical** arm alone surfaced carries no such value, because the dense arm never scored it inside
the bounded probe; `_exact_directed_cosines` closes that gap through `sqlite-vec`'s own scalar
`vec_distance_L2` function, grouped by candidate and bounded by their own chunk counts rather than
by store size — never the ranked `MATCH`/KNN operator, which has no per-memory `k`, and never a
Python-side recomputation of the metric, which would risk a candidate's eligibility depending on
which arm happened to score it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import aiosqlite

from zikaron.core.events import DedupOfferedDetail
from zikaron.core.records.memory import CallParams, log_event
from zikaron.core.retrieval.arms import cosine_from_distance
from zikaron.core.retrieval.eligibility import Consumer, Scope
from zikaron.core.retrieval.query import PreparedQuery, internal_query
from zikaron.core.retrieval.ranking import RankedMemory
from zikaron.core.retrieval.retrieve import RetrievalSettings, retrieve


@dataclass(frozen=True, slots=True)
class NearDuplicate:
    """One candidate `zikaron_remember` hands back: `architecture.md`'s per-row shape exactly.

    Never an assertion of duplication: a cosine floor is advisory only, since the corpus's own
    measurement of the underlying signal shows a near-miss identifier pair buys only a fraction of
    the separation a plainly distinct token does, so a value on either side of this floor cannot by
    itself tell a duplicate from a twin. This module reports the candidates; the agent reading both
    gists is what can tell them apart.
    """

    uuid: str
    gist: str
    cosine: float
    rank: int


async def _exact_directed_cosines(
    db: aiosqlite.Connection, memory_uuids: Sequence[str], *, query_vector: bytes
) -> Mapping[str, float]:
    """`s(new row → candidate)` for each of `memory_uuids`, computed exactly over every one of
    that candidate's own stored chunks — `schema.md`'s "any chunk of Y" — through `sqlite-vec`'s
    own scalar `vec_distance_L2` function.

    Neither the ranked `MATCH`/KNN operator nor a Python-side recomputation of the metric would do:
    the KNN operator has no per-memory `k`, so pointing it at one specific memory's chunks needs a
    `k` covering however much of the index ranks ahead of them; and decoding stored float32
    coordinates to Python's binary64 and accumulating them by hand would use different rounding
    characteristics than the pinned extension's own native arithmetic, risking a candidate whose
    true score sits at the threshold clearing it or not depending on which arm happened to score
    it — measured identical to the dense arm's own KNN-reported distance for the same stored
    vectors, verified locally against a hand-built example.

    One statement, grouped by `memory_uuid`, over exactly the candidates named — bounded by their
    own chunk counts, never by store size, and never one statement per candidate.

    A candidate absent from the result is one with no stored chunk at all — unreachable for any
    row `retrieve` returned, since invariant 12 pairs every active memory with at least one
    chunk and vector, but not assumed away: this function simply reports nothing for a uuid it
    found no vector for, rather than inventing a distance.
    """
    if not memory_uuids:
        return {}
    placeholders = ", ".join("?" for _ in memory_uuids)
    sql = (
        "SELECT c.memory_uuid, MIN(vec_distance_L2(v.embedding, ?)) "  # noqa: S608
        "FROM memory_chunk c "
        "JOIN memory_vec v ON v.rowid = c.chunk_id "
        f"WHERE c.memory_uuid IN ({placeholders}) "
        "GROUP BY c.memory_uuid"
    )
    rows = await db.execute_fetchall(sql, (query_vector, *memory_uuids))
    return {str(uuid): cosine_from_distance(float(distance)) for uuid, distance in rows}


async def _directed_cosines(
    db: aiosqlite.Connection, pool: Sequence[RankedMemory], *, query: PreparedQuery
) -> Mapping[str, float]:
    """`s(new row → candidate)` for every pooled row, computed exactly rather than only where the
    dense arm's bounded overfetch already happened to provide it.

    A row the dense arm placed within `fusion_depth` already carries its own exact minimum
    distance as `best_distance` — the dense arm's overfetch loop finds the true nearest chunk among
    however many it probed, and stops only once it has proven a surplus or covered the index, so
    that value is not an approximation to refine. Only a row the **lexical** arm alone surfaced
    needs `_exact_directed_cosines`, batched into one call over every such row rather than one
    query each, because the dense arm never scored those rows at all inside the bounded search.
    """
    cosines: dict[str, float] = {}
    lexical_only: list[str] = []
    for ranked in pool:
        if ranked.best_distance is not None:
            cosines[ranked.row.uuid] = cosine_from_distance(ranked.best_distance)
        else:
            lexical_only.append(ranked.row.uuid)
    cosines.update(await _exact_directed_cosines(db, lexical_only, query_vector=query.vector))
    return cosines


@dataclass(frozen=True, slots=True)
class DedupPolicy:
    """The two `[dedup]` config keys `offer` needs, bundled because every call reads them together.

    A caller building this straight from an untrusted source should validate against `schema.md`
    §"Configuration keys"'s own ranges first — `write.tools.WriteCall` is the one place in this
    codebase that does, since it is the type that holds a `DedupPolicy` for the length of one call.
    This type does not re-validate: `EffectiveConfig` already range-checks the resolved config
    these values come from, and repeating that check here would be a second place a configured
    value could be range-checked to disagree with.
    """

    dedup_threshold: float
    dedup_max: int


async def offer(
    db: aiosqlite.Connection,
    *,
    created_uuid: str,
    ctx: CallParams,
    settings: RetrievalSettings,
    policy: DedupPolicy,
) -> tuple[NearDuplicate, ...]:
    """Search for near-duplicates of `created_uuid` and log one `dedup_offered` event per hit.

    Assumes the caller's own open transaction, immediately after the row, its chunks and its
    vectors have been written — `internal_query` reads back the just-inserted `part_index = 0`
    chunk, so this must run after that insert and before commit, in the same transaction invariant
    10 requires for the write it is reporting on.

    Excludes `created_uuid` itself (`Consumer.DEDUP`'s `excludes_self`, since a row is its own
    nearest neighbour) and is restricted to `active = 1` rows across both tiers
    (`eligibility.CONSUMER_FILTERS[DEDUP]`) — the offered resolution is `amend`, which rejects an
    inactive row, so a retired or already-superseded candidate would be an offer the agent cannot
    take.

    `policy.dedup_max = 0` is legal (`schema.md` §Bounds: `0`-`20`) and means every call reports no
    candidates, which this function honors without running the search at all.

    Returns:
        Up to `policy.dedup_max` candidates, at or above `policy.dedup_threshold`, in the pool's
        own total order — deterministic for a fixed store and query, since `ranking.rank` is and
        the exact-cosine computation this function runs beside it is a pure function of the store.
    """
    if policy.dedup_max == 0:
        return ()
    query = await internal_query(
        db, memory_uuid=created_uuid, max_terms=settings.fts_query_max_terms
    )
    retrieved = await retrieve(
        db,
        query=query,
        scope=Scope(Consumer.DEDUP, exclude_uuid=created_uuid),
        settings=settings,
    )
    cosines = await _directed_cosines(db, retrieved.pool, query=query)
    offered: list[NearDuplicate] = []
    for ranked in retrieved.pool:
        cosine = cosines.get(ranked.row.uuid)
        if cosine is None or cosine < policy.dedup_threshold:
            continue
        rank = len(offered) + 1
        offered.append(
            NearDuplicate(uuid=ranked.row.uuid, gist=ranked.row.gist, cosine=cosine, rank=rank)
        )
        if len(offered) == policy.dedup_max:
            break
    await _log_offers(db, offered, created_uuid=created_uuid, ctx=ctx)
    return tuple(offered)


async def _log_offers(
    db: aiosqlite.Connection,
    offered: Sequence[NearDuplicate],
    *,
    created_uuid: str,
    ctx: CallParams,
) -> None:
    """One `dedup_offered` event per candidate, filed under the **candidate's** uuid.

    Not the new row's: `DedupOfferedDetail`'s own docstring states why — the matured-outcome signal
    joins `dedup_offered → amend` on the record an agent might amend, which is the candidate.
    """
    for candidate in offered:
        await log_event(
            db,
            ctx=ctx,
            detail=DedupOfferedDetail(
                created_uuid=created_uuid, cosine=candidate.cosine, rank=candidate.rank
            ),
            memory_uuid=candidate.uuid,
        )
