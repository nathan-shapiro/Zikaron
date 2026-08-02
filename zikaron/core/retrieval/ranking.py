"""Fusion, demotion, the total order, and the supersession repair — all pure, no store.

`retrieval.md` §"The fused score, written out", §"Total order" and §"Supersession: eligible,
demoted, and labelled" are normative. Four steps, in this order, and the order is observable:

1. **RRF.** `Σ 1 / (rrf_k + rank)` over the arms that returned the row, ranks 1-based. An arm that
   did not return it contributes nothing — not a term at a notional worst rank.
2. **Penalties.** A demoted row's fused score is multiplied by `supersession_penalty` or
   `retired_penalty`. On the *immediate* edge, not on graph depth: nothing measured says a
   twice-superseded record is more dangerous than a once-superseded one. The two states are mutually
   exclusive, so the penalties never compound.
3. **The total order**, five steps deep, because fused ties are pervasive rather than rare —
   measured: every hybrid query has at least one exact tie, and 12.5% have one *inside the top
   five*, where order fell to whichever arm happened to be appended first.
4. **The supersession repair**, a stable topological pass that puts every retrieved replacement
   ahead of every record it replaced.

The caller cuts to `limit` **after** all four, which is what lets the repair promote a replacement
into the returned set rather than merely reshuffling what already made the cut. That is the case the
measurement is about: a superseded record outranks its own replacement 28-50% of the time on the
polarity stubs, and in those cases the correct answer is provably present and losing.

Nothing here touches the store, so determinism is testable by calling it twice.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from zikaron.core.errors import ErrorCode, RowState, ZikaronError
from zikaron.core.events import Demotion
from zikaron.core.records.memory import Tier
from zikaron.core.records.supersession import BadSupersessionReason
from zikaron.core.retrieval.arms import ArmOutcome, ArmRow

#: Which tier wins a fused tie: consolidated prose has been reviewed by the consolidator, and
#: `~/Memory` reached the same tiebreak independently ("cohesive memory over raw journal line").
_TIER_ORDER: Final[Mapping[Tier, int]] = {Tier.LONG_TERM: 0, Tier.JOURNAL: 1}

#: The recency component for a long-term row. Step 4 is D27's *journal-local* recency tiebreak, so a
#: long-term row skips it and falls through to `uuid` — nothing about a long-term record's age is a
#: claim about its truth. A constant is well defined here precisely because step 3 has already
#: partitioned the remaining ties by tier: two rows still tied at step 4 share a tier, so this value
#: is only ever compared against another long-term row's copy of it.
_NO_RECENCY: Final = -1


@dataclass(frozen=True, slots=True)
class PoolRow:
    """One candidate's row facts — exactly the columns the read path needs, and no more.

    `content` and `version` are deliberately absent. `search` returns neither (a version would imply
    a licence to write that the agent has not earned), the injected block shows only the gist, and
    selecting long text for every row of a fused pool would spend I/O on the latency-critical path
    for prose nobody reads.
    """

    uuid: str
    tier: Tier
    gist: str
    active: bool
    superseded_by: str | None
    created_at: str
    updated_at: str

    @property
    def state(self) -> RowState:
        """This row's display state, per `schema.md` §"Retrieval eligibility"'s three states."""
        if self.active:
            return RowState.LIVE
        if self.superseded_by is not None:
            return RowState.SUPERSEDED
        return RowState.RETIRED

    @property
    def demotion(self) -> Demotion | None:
        """Why this row is demoted, or `None` for a live row that is not."""
        if self.active:
            return None
        return Demotion.SUPERSEDED if self.superseded_by is not None else Demotion.RETIRED


@dataclass(frozen=True, slots=True)
class Penalties:
    """The two demotion multipliers, which are separate config keys with equal defaults.

    Equal by honesty rather than by symmetry: nothing measured distinguishes a superseded row from
    an outright-retired one, so they start equal and can diverge once something does.
    """

    superseded: float
    retired: float

    def factor(self, demotion: Demotion | None) -> float:
        """The multiplier for one row's demotion state — 1.0 for a row that is not demoted."""
        if demotion is None:
            return 1.0
        return self.superseded if demotion is Demotion.SUPERSEDED else self.retired


@dataclass(frozen=True, slots=True)
class RankedMemory:
    """One candidate, scored and placed: the row, its fused score, and where each arm found it.

    `best_rank` is the minimum over the arms that returned it, so a row only one arm found is ranked
    on that arm's number rather than penalized for the other's silence. `best_distance` is the dense
    arm's rolled-up minimum, kept because the three cosine cutoffs are read off it — and only
    meaningful for a query whose vector is unit length, which `query.QueryOrigin` is what tracks.
    """

    row: PoolRow
    fused_score: float
    dense_rank: int | None
    lexical_rank: int | None
    best_distance: float | None

    @property
    def best_rank(self) -> int:
        """The best rank any arm gave this row. Both arms cannot be absent: it would not be here."""
        ranks = [rank for rank in (self.dense_rank, self.lexical_rank) if rank is not None]
        return min(ranks)

    @property
    def demoted(self) -> bool:
        """Whether this row was demoted, which is exactly whether it is inactive."""
        return self.row.demotion is not None


def rrf_score(ranks: Iterable[int], *, rrf_k: int) -> float:
    """Reciprocal Rank Fusion over the ranks one row achieved, in the arms that returned it.

    `Σ 1 / (rrf_k + rank)`, ranks **1-based** — the formula every quality figure in `retrieval.md`
    was measured through. Rebasing to 0 would leave `rrf_k = 60` naming a different denominator, so
    the config default and the measurements would silently stop describing the same pipeline.
    """
    return sum(1.0 / (rrf_k + rank) for rank in ranks)


def _by_uuid(outcome: ArmOutcome) -> Mapping[str, ArmRow]:
    return {row.uuid: row for row in outcome.rows}


def _journal_recency(rows: Iterable[PoolRow]) -> Mapping[str, int]:
    """Each journal row's position when the pool's timestamps are ordered newest first.

    An index rather than the timestamp itself, so step 4 needs no string inversion and no timestamp
    parsing — `created_at` is opaque text this layer never has to interpret, and a mapping from
    distinct value to descending position is monotone, so comparing indices ascending *is* comparing
    timestamps descending. Ties on the timestamp share an index and fall through to `uuid`, which is
    what step 5 is for.
    """
    journal = [row for row in rows if row.tier is Tier.JOURNAL]
    descending = sorted({row.created_at for row in journal}, reverse=True)
    position = {value: index for index, value in enumerate(descending)}
    return {row.uuid: position[row.created_at] for row in journal}


def _order_key(
    ranked: RankedMemory, recency: Mapping[str, int]
) -> tuple[float, int, int, int, str]:
    """`retrieval.md`'s five-step total order, as one comparable tuple.

    Ascending on every component, so the fused score is negated. The components are, in order: the
    fused score descending; the best rank any arm gave it ascending, since a document one arm ranked
    first is a better bet than one both arms ranked tenth; tier, long-term first; `created_at`
    descending **inside a journal block only**; and `uuid`, which is arbitrary and is the point —
    it guarantees a total order, so the same store and query always produce the same list.
    """
    return (
        -ranked.fused_score,
        ranked.best_rank,
        _TIER_ORDER[ranked.row.tier],
        recency.get(ranked.row.uuid, _NO_RECENCY),
        ranked.row.uuid,
    )


def _repair_supersession(ordered: Sequence[RankedMemory]) -> tuple[RankedMemory, ...]:
    """Reorder so every retrieved replacement precedes every record it replaced.

    Not "immediately above" — that rule is unsatisfiable, because `merge` absorbing `A` and `B` into
    `C` writes `A→C` *and* `B→C`, so no linear order can put `C` immediately above both. The
    realizable rule is precedence, enforced as a stable topological pass: scan in order and emit the
    first not-yet-emitted row whose `superseded_by` target is either absent from the pool or already
    emitted. It handles `A→B→C` transitively, giving `C, B, A`.

    Adjacency is neither preserved nor needed: the injected block gives the agent the replacement's
    uuid explicitly, which is a stronger cue than proximity and is the part that survives a group of
    rows sharing one replacement.

    Raises:
        ZikaronError: `BAD_SUPERSESSION` with `reason='cycle'` if no row is emittable, which
            invariant 6 makes impossible — every row waits on at most one other and the graph is
            acyclic, so the wait-for relation is a forest. Refused rather than worked around: a
            fallback to the pre-repair order would answer from a corrupted graph with a *plausible*
            list, and putting the replacement first is the whole point of the pass.
    """
    in_pool = {ranked.row.uuid for ranked in ordered}
    waiting = list(ordered)
    emitted: list[RankedMemory] = []
    emitted_uuids: set[str] = set()
    while waiting:
        for index, ranked in enumerate(waiting):
            target = ranked.row.superseded_by
            if target is None or target not in in_pool or target in emitted_uuids:
                emitted.append(waiting.pop(index))
                emitted_uuids.add(ranked.row.uuid)
                break
        else:
            stalled = waiting[0].row
            raise ZikaronError(
                ErrorCode.BAD_SUPERSESSION,
                uuid=stalled.uuid,
                target=stalled.superseded_by,
                reason=BadSupersessionReason.CYCLE,
            )
    return tuple(emitted)


def rank(
    *,
    dense: ArmOutcome,
    lexical: ArmOutcome,
    rows: Mapping[str, PoolRow],
    rrf_k: int,
    penalties: Penalties,
) -> tuple[RankedMemory, ...]:
    """Fuse both arms into one ordered pool: RRF, penalties, the total order, then the repair.

    The returned pool is **not** cut to any output budget; the caller cuts it, because the repair
    must run first if it is to promote a replacement into the returned set.

    Args:
        rows: the row facts for every uuid either arm returned. A uuid missing from this mapping is
            a row that vanished between the arm query and the pool load, which one read transaction
            makes impossible; it is dropped rather than guessed at.
    """
    dense_rows = _by_uuid(dense)
    lexical_rows = _by_uuid(lexical)
    scored: list[RankedMemory] = []
    for uuid in [*dense_rows, *(uuid for uuid in lexical_rows if uuid not in dense_rows)]:
        row = rows.get(uuid)
        if row is None:
            continue
        found = [arm[uuid] for arm in (dense_rows, lexical_rows) if uuid in arm]
        fused = rrf_score((arm_row.rank for arm_row in found), rrf_k=rrf_k)
        dense_row = dense_rows.get(uuid)
        lexical_row = lexical_rows.get(uuid)
        scored.append(
            RankedMemory(
                row=row,
                fused_score=fused * penalties.factor(row.demotion),
                dense_rank=None if dense_row is None else dense_row.rank,
                lexical_rank=None if lexical_row is None else lexical_row.rank,
                best_distance=None if dense_row is None else dense_row.distance,
            )
        )
    recency = _journal_recency(ranked.row for ranked in scored)
    ordered = sorted(scored, key=lambda ranked: _order_key(ranked, recency))
    return _repair_supersession(ordered)
