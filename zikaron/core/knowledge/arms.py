"""The two retrieval arms over one knowledge base, and the query both of them are built from.

Each arm returns chunk ids at 1-based ranks, and nothing else: fusion consumes ranks, so an arm's
job ends at the order it produced. The dense arm also carries the distance it measured, because the
score a result reports and the key its group is ordered by are both read off that.

**Neither arm needs the overfetch loop the memory store's dense arm has.** That loop exists because
`vec0` cannot filter on another table's columns, so a fixed depth there can yield fewer *eligible*
memories than asked for. A knowledge base has no eligibility predicate — every chunk it holds is a
chunk it will serve — so a single probe at the corpus's own `fusion_depth` is exactly the top of the
index.
"""

from dataclasses import dataclass, replace

import aiosqlite

from zikaron.core.indexing.encoder import Encoder
from zikaron.core.indexing.vectors import deserialize, normalize, serialize
from zikaron.core.retrieval.query import ExternalQuery, external_query


@dataclass(frozen=True, slots=True)
class ArmRow:
    """One chunk an arm returned, at its rank within that arm.

    `rank` is **1-based**: the arm's best chunk is rank 1, which is the base the shipped `rrf_k` was
    measured against. Rebasing to 0 would leave every arm's internal order unchanged while changing
    every fused score, so nothing downstream could notice.

    `distance` is the dense arm's L2 distance from the query, and `None` on the lexical arm — which
    has none and needs none.
    """

    chunk_id: int
    rank: int
    distance: float | None = None


def unit_query(text: str, *, encoder: Encoder, prefix: str, max_terms: int) -> ExternalQuery:
    """Build both arms of a query, with its dense vector scaled to unit length.

    The construction is the store's own — the same token budget, the same truncation rule, the same
    quoted-term lexical expression — with one addition: the vector is normalized.

    **That addition is what makes a reported score a cosine.** `cos = 1 - d^2/2` over `vec0`'s L2
    distance is exact only when both vectors are unit length; the corpus is normalized at write
    time, and normalizing the query closes the other half. Ranking is unaffected either way, since
    distance to unit documents is monotone in cosine for any fixed query vector — so what this buys
    is not a better order but a number a reader can compare across corpora, which is the one
    cross-corpus comparison this design allows.
    """
    built = external_query(text, encoder=encoder, prefix=prefix, max_terms=max_terms)
    unit = serialize(normalize(deserialize(built.prepared.vector), embed_dim=encoder.dim))
    return replace(built, prepared=replace(built.prepared, vector=unit))


async def dense(
    db: aiosqlite.Connection, *, vector: bytes, fusion_depth: int
) -> tuple[ArmRow, ...]:
    """The `fusion_depth` nearest chunks to `vector`, nearest first.

    **The tie-break is applied here rather than in SQL, and it has to be.** A `vec0` nearest-
    neighbour query accepts `ORDER BY distance` and nothing else — a second term raises *only a
    single 'ORDER BY distance' clause is allowed*, measured — so ordering two chunks at an identical
    distance is this function's job. Without it their relative order is the extension's business and
    two runs of one query could disagree.

    **The key column is `chunk_id`, and there is no `rowid` to use instead**: this vector table is
    declared with its own integer primary key, and such a `vec0` table exposes no `rowid` at all.
    """
    rows = await db.execute_fetchall(
        "SELECT chunk_id, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ?",
        (vector, fusion_depth),
    )
    nearest = sorted((float(distance), int(chunk_id)) for chunk_id, distance in rows)
    return tuple(
        ArmRow(chunk_id=chunk_id, rank=rank, distance=distance)
        for rank, (distance, chunk_id) in enumerate(nearest, start=1)
    )


async def lexical(
    db: aiosqlite.Connection, *, expression: str, fusion_depth: int
) -> tuple[ArmRow, ...]:
    """The `fusion_depth` best-matching chunks for `expression`, best first.

    `bm25()` is negative in SQLite with better matches more negative, so ascending is best-first;
    the chunk id breaks the exact ties a single-term query reaches trivially, without which the
    arm's ranks — and so the fused order — would fall to the query plan.

    `bm25()` and `MATCH` both name the table rather than an alias, which is not a style choice:
    FTS5's auxiliary functions reject an alias with a bare `no such column`.
    """
    rows = await db.execute_fetchall(
        "SELECT rowid FROM chunks_fts "
        "WHERE chunks_fts MATCH ? "
        "ORDER BY bm25(chunks_fts) ASC, rowid ASC "
        "LIMIT ?",
        (expression, fusion_depth),
    )
    return tuple(
        ArmRow(chunk_id=int(chunk_id), rank=rank) for rank, (chunk_id,) in enumerate(rows, start=1)
    )
