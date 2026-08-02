"""The one retrieval algorithm, run by all five consumers, composable into a caller's transaction.

`retrieval.md`: "Every read path — push, pull, write-time dedup, consolidation anchors, orphan edges
— uses the same **base** predicate and the same algorithm, and adds at most one filter." This module
is that algorithm: both arms, the pool load, and the ranking, in that order and nowhere else.

It **neither begins nor commits a transaction**, for the same reason `records` and `indexing` split
their verbs that way: D15's dedup search has to run inside the same transaction as the `remember` it
reports on, since it queries the vectors that write has just inserted. `reads.py` owns the
transaction for the two external verbs; the internal-query consumers own theirs.

What the caller must guarantee is the one thing this module cannot check for itself: that a read
transaction is already open. Both arms and the pool load then see one snapshot, which is what makes
the dense arm's coverage comparison a statement about a single store rather than about two.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Self

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.records.memory import Tier
from zikaron.core.retrieval import arms, ranking
from zikaron.core.retrieval.arms import ArmOutcome
from zikaron.core.retrieval.eligibility import Scope
from zikaron.core.retrieval.query import PreparedQuery
from zikaron.core.retrieval.ranking import Penalties, PoolRow, RankedMemory

#: `memory`'s columns as the read path needs them, in the fixed order `_to_pool_row` unpacks. One
#: constant rather than a literal per statement, so the row shape has one reader. `content` and
#: `version` are absent by design — see `PoolRow`.
_POOL_COLUMNS: Final = "uuid, tier, gist, active, superseded_by, created_at, updated_at"


@dataclass(frozen=True, slots=True)
class RetrievalSettings:
    """Every configuration value the read algorithm consumes, resolved once.

    Bundled because they travel together for the life of a store handle and because `event` rows
    written by one call must all report the parameters that produced them — `architecture.md` reads
    the config once at startup for exactly that reason, and a per-call re-read would let two events
    of one run disagree about the ranking they describe.
    """

    fusion_depth: int
    rrf_k: int
    chunk_overfetch: int
    penalties: Penalties
    fts_query_max_terms: int
    embed_prefix_query: str

    @classmethod
    def from_config(cls, config: EffectiveConfig) -> Self:
        """Read the `[retrieval]` and `[embedding]` keys this algorithm is parameterized by."""
        return cls(
            fusion_depth=config.get_int("fusion_depth"),
            rrf_k=config.get_int("rrf_k"),
            chunk_overfetch=config.get_int("chunk_overfetch"),
            penalties=Penalties(
                superseded=config.get_float("supersession_penalty"),
                retired=config.get_float("retired_penalty"),
            ),
            fts_query_max_terms=config.get_int("fts_query_max_terms"),
            embed_prefix_query=config.get_str("embed_prefix_query"),
        )


@dataclass(frozen=True, slots=True)
class Retrieved:
    """The full ordered candidate pool, plus what each arm reported about how far it got.

    **Not cut to any output budget.** The cut is the caller's last step, after the supersession
    repair, which is what lets the repair promote a replacement into the returned set rather than
    only reshuffling what already made it.
    """

    pool: tuple[RankedMemory, ...]
    dense: ArmOutcome
    lexical: ArmOutcome


def _to_pool_row(row: Sequence[object]) -> PoolRow:
    uuid, tier, gist, active, superseded_by, created_at, updated_at = row
    return PoolRow(
        uuid=str(uuid),
        tier=Tier(str(tier)),
        gist=str(gist),
        active=bool(active),
        superseded_by=None if superseded_by is None else str(superseded_by),
        created_at=str(created_at),
        updated_at=str(updated_at),
    )


async def _load_pool_rows(db: aiosqlite.Connection, uuids: Sequence[str]) -> Mapping[str, PoolRow]:
    """The row facts for every uuid either arm returned, in one statement.

    A lookup by uuid rather than a predicate path, so it adds no filter and is not one of the five
    consumers: eligibility was already decided inside each arm's own query, against the same
    snapshot this read sees.
    """
    if not uuids:
        return {}
    placeholders = ", ".join("?" for _ in uuids)
    sql = f"SELECT {_POOL_COLUMNS} FROM memory WHERE uuid IN ({placeholders})"  # noqa: S608 — placeholders only; every uuid is a bound parameter.
    rows = await db.execute_fetchall(sql, tuple(uuids))
    loaded = [_to_pool_row(tuple(row)) for row in rows]
    return {row.uuid: row for row in loaded}


async def retrieve(
    db: aiosqlite.Connection,
    *,
    query: PreparedQuery,
    scope: Scope,
    settings: RetrievalSettings,
) -> Retrieved:
    """Run both arms over `scope`, fuse them, and return the whole ordered pool.

    Assumes an open transaction. The lexical arm is skipped — and says so, with both of its
    instrumentation fields null — when the query yielded no surviving term; the dense arm always
    runs, so a prompt of pure punctuation still gets an answer.

    Raises:
        ZikaronError: `BAD_SUPERSESSION` with `reason='cycle'` if the pool's supersession edges
            cannot be topologically ordered, which invariant 6 makes impossible in a well-formed
            store.
    """
    dense = await arms.dense_arm(
        db,
        vector=query.vector,
        scope=scope,
        fusion_depth=settings.fusion_depth,
        chunk_overfetch=settings.chunk_overfetch,
    )
    expression = query.lexical.expression
    lexical = (
        ArmOutcome.skipped(fusion_depth=settings.fusion_depth)
        if expression is None
        else await arms.lexical_arm(
            db, expression=expression, scope=scope, fusion_depth=settings.fusion_depth
        )
    )
    seen: dict[str, None] = {}
    for outcome in (dense, lexical):
        for row in outcome.rows:
            seen.setdefault(row.uuid, None)
    rows = await _load_pool_rows(db, tuple(seen))
    pool = ranking.rank(
        dense=dense,
        lexical=lexical,
        rows=rows,
        rrf_k=settings.rrf_k,
        penalties=settings.penalties,
    )
    return Retrieved(pool=pool, dense=dense, lexical=lexical)
