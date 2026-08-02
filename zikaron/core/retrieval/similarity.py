"""`s(X → Y)`: the one directed score all three cosine cutoffs are defined over.

`schema.md` §"Configuration keys" defines it once — **the best cosine between X's first chunk and
any chunk of Y** — and three keys threshold it: `dedup_threshold` on `s(new row → candidate)`,
`anchor_cutoff` on `s(entry → record)`, and `orphan_edge_cutoff` on the symmetrized
`min(s(A → B), s(B → A))`. One definition, so one implementation: a second one that rounded
differently would put a pair on opposite sides of a floor depending on which caller asked.

**It is a mathematical fact about two rows' stored vectors, not a by-product of a search.** The
fused pool decides *which* rows are candidates at all; this decides whether each clears its floor.
A row the dense arm's overfetch loop placed within `fusion_depth` already carries its own exact
minimum distance, because that loop finds the true nearest chunk among however many it probed and
stops only once it has proven a surplus or covered the index — so that value needs no refining. A
row the **lexical** arm alone surfaced carries none, and closing that gap is what the batched
statement below is for. Leaving it open was a real defect once: it silently excluded every
lexical-only candidate from a threshold test regardless of its true score.

**The arithmetic is the pinned extension's, never ours.** `vec_distance_L2` is the same native
function `vec0`'s KNN path evaluates, measured bit-identical on the same stored vectors. Decoding
float32 coordinates into Python's binary64 and re-summing them by hand has different rounding
characteristics, which is exactly how a pair sitting on a floor comes to clear it under one arm's
scoring and not the other's. Nor the ranked `MATCH`/KNN operator: `vec0`'s `k` is a **global** rank
cutoff, so aiming it at one named memory's chunks needs a `k` covering however much of the index
ranks ahead of them, and can return nothing belonging to the memory it was aimed at.

Every cosine here is exact **only for unit vectors**, which is why `query.QueryOrigin` exists: the
write path L2-normalizes the corpus and an internal query reuses a stored chunk vector, so both
sides are unit length. No external query is ever thresholded.
"""

from collections.abc import Mapping, Sequence

import aiosqlite

from zikaron.core.retrieval.arms import cosine_from_distance
from zikaron.core.retrieval.query import PreparedQuery
from zikaron.core.retrieval.ranking import RankedMemory


async def exact_directed_cosines(
    db: aiosqlite.Connection, memory_uuids: Sequence[str], *, query_vector: bytes
) -> Mapping[str, float]:
    """`s(query → Y)` for each of `memory_uuids`, over every one of that row's own stored chunks.

    One statement, grouped by `memory_uuid`, over exactly the rows named — bounded by their own
    chunk counts rather than by store size, and never one statement per row.

    Assumes the caller's own open transaction, so the vectors read are the same snapshot the
    caller's other reads saw.

    Returns:
        A cosine per uuid that has at least one stored vector. A uuid absent from the result had
        none — unreachable for any active row, since invariant 12 pairs every one with a chunk, and
        reported as absence rather than as an invented distance.
    """
    if not memory_uuids:
        return {}
    placeholders = ", ".join("?" for _ in memory_uuids)
    sql = (
        "SELECT c.memory_uuid, MIN(vec_distance_L2(v.embedding, ?)) "  # noqa: S608 — placeholders only; every uuid is a bound parameter.
        "FROM memory_chunk c "
        "JOIN memory_vec v ON v.rowid = c.chunk_id "
        f"WHERE c.memory_uuid IN ({placeholders}) "
        "GROUP BY c.memory_uuid"
    )
    rows = await db.execute_fetchall(sql, (query_vector, *memory_uuids))
    return {str(uuid): cosine_from_distance(float(distance)) for uuid, distance in rows}


async def directed_cosines(
    db: aiosqlite.Connection, pool: Sequence[RankedMemory], *, query: PreparedQuery
) -> Mapping[str, float]:
    """`s(query → Y)` for every row of a fused pool, exact for all of them rather than for some.

    Reuses the dense arm's own rolled-up minimum distance where it has one and batches a single
    further statement for the rows only the lexical arm surfaced — one call for all of them, not
    one each, because the cost of the missing case must not scale with how many rows are missing it.
    """
    cosines: dict[str, float] = {}
    lexical_only: list[str] = []
    for ranked in pool:
        if ranked.best_distance is not None:
            cosines[ranked.row.uuid] = cosine_from_distance(ranked.best_distance)
        else:
            lexical_only.append(ranked.row.uuid)
    cosines.update(await exact_directed_cosines(db, lexical_only, query_vector=query.vector))
    return cosines
