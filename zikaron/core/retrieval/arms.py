"""The two arms, and the four numbers that say how far each one got and why it stopped.

`retrieval.md` §"The dense arm's overfetch loop, and the three ways it can stop" is normative, and
the asymmetry between the arms is the whole content of this module.

**The dense arm cannot filter where it searches.** `vec0` knows nothing about `memory`'s columns, so
eligibility is applied *after* the join, which means a fixed KNN depth can yield fewer eligible
memories than asked for — one long memory occupies many chunk slots, and retired rows consume more.
Hence an overfetch loop that doubles its chunk depth until it has a surplus, has provably read every
chunk, or has spent its four doublings.

**The lexical arm has no such problem.** D28 leaves FTS5 unchunked, so one row is one memory and the
whole arm is a single limited statement over an ordered cursor. Returning fewer rows than it asked
for is therefore a *proven* end of cursor rather than an unknown, which is why `probe_cap_hit` is
unreachable there — a consequence of having no cap, not an assumption about the data.

**Both arms probe for one more memory than they keep**, and that surplus row is never fused. It
exists so that "the bound cut something" is a measured surplus rather than an inference from
equality: without it, a store holding exactly `fusion_depth` eligible memories and a store holding
thousands produce the identical observable while meaning opposite things.

`ArmOutcome` enforces `schema.md` invariant 20 at construction, so an arm that cannot honestly
classify its own termination cannot be built, let alone logged.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

import aiosqlite

from zikaron.core.events import StopReason
from zikaron.core.retrieval.eligibility import MEMORY_ALIAS, Scope

#: How many times the dense arm may double its chunk depth before giving up and saying so. A
#: latency bound: it caps the arm at `fusion_depth * chunk_overfetch * 16` chunks — 6,400 at the
#: defaults — so one pathological query cannot walk an entire large index. Reaching it is not an
#: error; it is `probe_cap_hit`, and it is the field to watch when tuning `chunk_overfetch`.
MAX_DOUBLINGS: Final = 4


class Arm(StrEnum):
    """The two arms, named because invariant 20 constrains them differently.

    Only the dense arm can report `PROBE_CAP_HIT`; one vocabulary, two reachable subsets of it.
    """

    DENSE = "dense"
    LEXICAL = "lexical"


@dataclass(frozen=True, slots=True)
class ArmRow:
    """One memory an arm returned, at its rank within that arm.

    `rank` is **1-based**: the arm's best row is rank 1, which is the base `rrf_k = 60` was measured
    against. `distance` is the dense arm's best (minimum) chunk distance for this memory — D28's
    "`max` over chunks" in the metric the code actually sees — and is `None` on the lexical arm,
    which has no distance and needs none: RRF consumes ranks, not scores.
    """

    uuid: str
    rank: int
    distance: float | None = None


@dataclass(frozen=True, slots=True)
class ArmOutcome:
    """What one arm produced, and the self-evidencing pair invariant 20 constrains.

    `rows` is the arm's contribution to fusion — already cut to `fusion_depth`, so the surplus probe
    row is not here. `depth_reached` is the count of distinct eligible memories the arm produced
    **before** that cut, capped at the probe target, so it ranges over `0 … fusion_depth + 1` and
    the single value `fusion_depth + 1` is exactly the surplus that licenses `depth_reached`.

    Invariant 20 is checked here rather than at the event writer, because the event is the *report*
    and this is the claim: an arm that classified its own termination in a way its recorded depth
    contradicts must not exist to be reported. A skipped arm is the one case where both fields are
    absent, and it is represented by `skipped()` rather than by zeros, since zero and
    `index_exhausted` would together assert that the arm read the index and found nothing.

    Raises:
        ValueError: the depth and the reason disagree, the depth is out of range, or the lexical arm
            claims `probe_cap_hit`.
    """

    arm: Arm
    rows: tuple[ArmRow, ...]
    fusion_depth: int
    depth_reached: int | None
    stop_reason: StopReason | None

    def __post_init__(self) -> None:
        if (self.depth_reached is None) != (self.stop_reason is None):
            raise ValueError(
                f"{self.arm}: depth_reached={self.depth_reached} and "
                f"stop_reason={self.stop_reason} must be null together"
            )
        if self.depth_reached is None or self.stop_reason is None:
            self._require_a_legal_skip()
            return
        probe_target = self.fusion_depth + 1
        if not 0 <= self.depth_reached <= probe_target:
            raise ValueError(f"{self.arm}: depth_reached={self.depth_reached} exceeds probe target")
        cut = self.stop_reason is StopReason.DEPTH_REACHED
        if cut != (self.depth_reached == probe_target):
            raise ValueError(
                f"{self.arm}: stop_reason={self.stop_reason} disagrees with "
                f"depth_reached={self.depth_reached} at fusion_depth={self.fusion_depth}"
            )
        if self.arm is Arm.LEXICAL and self.stop_reason is StopReason.PROBE_CAP_HIT:
            raise ValueError("the lexical arm has no probe to cap")
        if len(self.rows) != min(self.depth_reached, self.fusion_depth):
            raise ValueError(
                f"{self.arm}: {len(self.rows)} rows fused from depth_reached="
                f"{self.depth_reached} at fusion_depth={self.fusion_depth}"
            )
        self._require_one_based_ranks()

    def _require_a_legal_skip(self) -> None:
        """Refuse a null/null outcome that is not the one skip the design defines.

        `retrieval.md` gives skipping exactly one producer — a lexical query whose terms all
        vanished — so two other null/null shapes are representable and both would be false reports.
        A **dense** arm cannot be skipped: it always runs, which is what makes "a prompt of pure
        punctuation still gets an answer" true. And an outcome carrying **rows** while reporting no
        depth claims to have fused memories it never admits retrieving, which is a depth of zero
        told two ways.
        """
        if self.arm is not Arm.LEXICAL:
            raise ValueError(f"{self.arm}: only the lexical arm can be skipped, and it always runs")
        if self.rows:
            raise ValueError(f"{self.arm}: a skipped arm reports no depth, so it can fuse no rows")

    def _require_one_based_ranks(self) -> None:
        """Refuse an arm whose ranks are not exactly `1 … len(rows)`.

        The rank **base** is load-bearing and silently so: rebasing to 0 leaves every arm's internal
        order unchanged while changing every fused score, so `rrf_k = 60` would name a different
        denominator and the config default would stop describing the pipeline every quality figure
        in `retrieval.md` was measured through. Nothing downstream can notice that, because a
        uniformly shifted score ranks the same — which is exactly why it is checked here, where the
        ranks are made, rather than left to a comparison that cannot see it.
        """
        ranks = [row.rank for row in self.rows]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f"{self.arm}: ranks must be 1..{len(ranks)}, got {ranks}")

    @classmethod
    def skipped(cls, *, fusion_depth: int) -> Self:
        """The lexical arm, not run: no rows, and both instrumentation fields null.

        Takes no arm, because there is only one that can be skipped. `retrieval.md` gives this
        exactly one producer — a lexical query whose terms all vanished — and invariant 20's "null
        iff null" clause exists for precisely this case; the dense arm always runs.
        """
        return cls(
            arm=Arm.LEXICAL,
            rows=(),
            fusion_depth=fusion_depth,
            depth_reached=None,
            stop_reason=None,
        )


def cosine_from_distance(distance: float) -> float:
    """`vec0`'s L2 distance as a cosine: `cos = 1 - d^2 / 2`.

    Exact **only when both vectors are unit length**, which is why `query.QueryOrigin` exists: the
    corpus is L2-normalized by the write path, and an internal query reuses a stored chunk vector,
    so the three cosine cutoffs are computed on two unit vectors.

    **Two callers, and only one of them leaves an external query unnormalized.** In the memory
    store, an external query's vector is used as the embedder returned it and no external query is
    ever thresholded — ordering by distance is monotone in cosine for any fixed query vector, so the
    ranking is unaffected and no number is read off it. The knowledge index does read a number off
    it — a result reports a cosine, and group order is decided by one — so it normalizes the query
    before binding it, which is what makes this function's output a cosine there rather than a
    monotone stand-in for one.
    """
    return 1.0 - (distance * distance) / 2.0


def _classify(*, surplus: bool, covered: bool) -> StopReason:
    """Which of the three terminal reasons applies, surplus first so exactly one does.

    Surplus outranks coverage because a surplus *proves* at least one eligible memory was cut,
    whether or not the probe was covered. Coverage then distinguishes the two remaining cases, which
    look identical from the depth alone and mean opposite things: `index_exhausted` says the store
    has no more to give — equality lands here, nothing was cut and nothing more exists — while
    `probe_cap_hit` says completeness is simply unknown, the arm found no surplus and left index
    unprobed.
    """
    if surplus:
        return StopReason.DEPTH_REACHED
    return StopReason.INDEX_EXHAUSTED if covered else StopReason.PROBE_CAP_HIT


async def _chunk_count(db: aiosqlite.Connection) -> int:
    """How many chunks the dense index holds, read inside the caller's own read transaction.

    Inside it, not beside it: this is the denominator of the coverage comparison, so a concurrent
    write moving it between the probe and the comparison would make "the probe read every chunk"
    a claim about two different stores.
    """
    rows = await db.execute_fetchall("SELECT count(*) FROM memory_chunk")
    return int(next(iter(rows))[0])


async def _probe_dense(
    db: aiosqlite.Connection, *, vector: bytes, scope: Scope, chunks: int, limit: int
) -> tuple[ArmRow, ...]:
    """The `chunks` nearest chunks, joined, filtered, and rolled up to `limit` memories.

    The rollup is **minimum distance per memory**, which is D28's "`max` over chunk scores" in the
    metric `vec0` actually returns — same operation, opposite sign — and it is also the
    memory-level dedup D28 calls mandatory rather than an optimization: without it a five-chunk
    memory can occupy all five injected slots.

    `uuid` breaks an exact distance tie, so the arm's rank vector is a function of the store and the
    query rather than of the query plan.
    """
    clause, params = scope.where()
    sql = (
        f"SELECT c.memory_uuid, MIN(v.distance) AS best "  # noqa: S608 — every fragment is a source-level constant; values are bound below.
        f"FROM (SELECT rowid, distance FROM memory_vec WHERE embedding MATCH ? AND k = ?) v "
        f"JOIN memory_chunk c ON c.chunk_id = v.rowid "
        f"JOIN memory {MEMORY_ALIAS} ON {MEMORY_ALIAS}.uuid = c.memory_uuid "
        f"WHERE {clause} "
        f"GROUP BY c.memory_uuid "
        f"ORDER BY best ASC, c.memory_uuid ASC "
        f"LIMIT ?"
    )
    rows = await db.execute_fetchall(sql, (vector, chunks, *params, limit))
    return tuple(
        ArmRow(uuid=str(uuid), rank=rank, distance=float(distance))
        for rank, (uuid, distance) in enumerate(rows, start=1)
    )


async def dense_arm(
    db: aiosqlite.Connection,
    *,
    vector: bytes,
    scope: Scope,
    fusion_depth: int,
    chunk_overfetch: int,
) -> ArmOutcome:
    """Run the dense arm's overfetch loop and classify how it stopped.

    Doubles the chunk depth until it finds a surplus eligible memory, proves it has read every
    chunk, or spends `MAX_DOUBLINGS`. Assumes the caller's own open read transaction, which is what
    makes the coverage comparison sound.

    Returns:
        An `ArmOutcome` whose `rows` are the best `fusion_depth` memories by distance, and whose
        `depth_reached`/`stop_reason` satisfy invariant 20 by construction.
    """
    probe_target = fusion_depth + 1
    total_chunks = await _chunk_count(db)
    chunks = fusion_depth * chunk_overfetch
    doublings = 0
    while True:
        rows = await _probe_dense(db, vector=vector, scope=scope, chunks=chunks, limit=probe_target)
        covered = chunks >= total_chunks
        surplus = len(rows) >= probe_target
        if surplus or covered or doublings == MAX_DOUBLINGS:
            break
        chunks *= 2
        doublings += 1
    return ArmOutcome(
        arm=Arm.DENSE,
        rows=rows[:fusion_depth],
        fusion_depth=fusion_depth,
        depth_reached=len(rows),
        stop_reason=_classify(surplus=surplus, covered=covered),
    )


async def lexical_arm(
    db: aiosqlite.Connection, *, expression: str, scope: Scope, fusion_depth: int
) -> ArmOutcome:
    """Run the lexical arm: one statement, asking for one row past what it will keep.

    `bm25()` is negative in SQLite with better matches more negative, so ascending is best-first;
    `uuid` breaks the exact ties that are trivially reachable on a single-term query, without which
    an arm's ranks — and so the fused order — would fall to the query plan.

    The cost of certainty here is stated rather than hidden: when a query matches many rows of which
    few are eligible, the planner must walk the match set to fill the limit. That walk is bounded by
    the **match set** rather than by the store, and there is no second probe to double.

    Both `bm25()` and `MATCH` name `memory_fts` rather than a join alias, which is not a style
    choice: FTS5's auxiliary functions reject an alias with `no such column`.
    """
    clause, params = scope.where()
    sql = (
        f"SELECT {MEMORY_ALIAS}.uuid "  # noqa: S608 — every fragment is a source-level constant; values are bound below.
        f"FROM memory_fts "
        f"JOIN memory {MEMORY_ALIAS} ON {MEMORY_ALIAS}.rowid = memory_fts.rowid "
        f"WHERE memory_fts MATCH ? AND {clause} "
        f"ORDER BY bm25(memory_fts) ASC, {MEMORY_ALIAS}.uuid ASC "
        f"LIMIT ?"
    )
    probe_target = fusion_depth + 1
    rows = await db.execute_fetchall(sql, (expression, *params, probe_target))
    found = tuple(ArmRow(uuid=str(uuid), rank=rank) for rank, (uuid,) in enumerate(rows, start=1))
    surplus = len(found) >= probe_target
    return ArmOutcome(
        arm=Arm.LEXICAL,
        rows=found[:fusion_depth],
        fusion_depth=fusion_depth,
        depth_reached=len(found),
        # An ordered cursor that returned fewer rows than it asked for reached the end of the match
        # set with every eligible row already counted, so the absence of a surplus *is* coverage
        # here — proven rather than probed. That is why `probe_cap_hit` is unreachable on this arm.
        stop_reason=_classify(surplus=surplus, covered=not surplus),
    )
