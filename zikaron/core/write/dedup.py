"""D15's write-time dedup: search after the write, hand back candidates, never block it.

`architecture.md`'s `zikaron_memory_remember` contract is normative. After a row is written, this
module
runs the same hybrid search the read path runs — reusing the new row's own first-chunk embedding
for the dense arm and its own `gist + content` for the lexical one, so the search costs no second
embed call — and reports up to `dedup_max` near-duplicates at or above `dedup_threshold`, each a
row the agent may choose to resolve by amending it and retiring the one just created. The search
runs **inside the same transaction** as the write it reports on, because it queries the vectors
that write just inserted, and it never rejects: `zikaron_memory_remember` "writes unconditionally,
then
reports" is D32's never-lose guarantee, and refusing a write on a dedup match would be exactly the
prevention D15 explicitly declines to do.

**`dedup_threshold` is a floor on `s(new row → candidate)`, and that quantity is exact, not
whatever the dense arm's bounded overfetch happened to surface.** The definition, and the one
implementation of it every cutoff in the system shares, is `retrieval.similarity` — see that
module for why the arithmetic is delegated to the pinned extension and why a lexical-only candidate
needs a second statement at all. What is *this* module's is only the policy: the fused pool decides
which rows are candidates, `dedup_threshold` decides which of them are offered, and `dedup_max`
decides how many.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import aiosqlite

from zikaron.core.events import DedupOfferedDetail
from zikaron.core.records.memory import CallParams, log_event
from zikaron.core.retrieval.eligibility import Consumer, Scope
from zikaron.core.retrieval.query import internal_query
from zikaron.core.retrieval.retrieve import RetrievalSettings, retrieve
from zikaron.core.retrieval.similarity import directed_cosines


@dataclass(frozen=True, slots=True)
class NearDuplicate:
    """One candidate `zikaron_memory_remember` hands back: `architecture.md`'s per-row shape
    exactly.

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
    cosines = await directed_cosines(db, retrieved.pool, query=query)
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
