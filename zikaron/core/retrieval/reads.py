"""The two external read verbs: `search` (pull) and `surface` (push), each one transaction.

`retrieval.md`'s two paths differ in three ways and share everything else. `surface` spends D12's
five-gist budget on a user prompt and returns **ready-to-print text**, so the hook stays dumb;
`search` is a deliberate act by the agent, returns structured rows, and is the only path allowed to
widen eligibility to outright-retired rows. Neither reranks: D23's measured latency curve leaves
exactly one affordable point on the push path, and reranking five candidates is operationally
pointless.

**Each call is one transaction**, and the instrumentation is inside it: both arms, the `chunk_count`
the dense arm's coverage is compared against, the pool load, and the `event` rows. A read that
writes its own instrumentation is a WAL snapshot upgrade, so a write committed by another process
mid-call refuses the upgrade — which is `store_busy`, retryable, and exactly the stale-snapshot case
`architecture.md` §Errors defines that code to cover. Any *other* driver failure has no Zikaron code
and propagates: `index_failed` speaks of index maintenance and a rolled-back write, and a read
performs neither.

`search` mints **no receipt** and returns **no version**, which is the same fact twice. A row the
agent has only seen as a gist is a row it may not write, and holding a version would imply a licence
it has not earned — `architecture.md`: "`fetch` is the only way to license a write to a pre-existing
row, absent an own-write or conflict response for that exact row in this session."
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import aiosqlite

from zikaron.core.errors import ErrorCode, RowState, ZikaronError
from zikaron.core.events import (
    ArmTermination,
    QueryShape,
    SearchDetail,
    SurfaceCallDetail,
    SurfaceDetail,
)
from zikaron.core.indexing.encoder import Encoder
from zikaron.core.records import memory
from zikaron.core.records.memory import CallParams, Tier
from zikaron.core.retrieval import block, query
from zikaron.core.retrieval.arms import ArmOutcome
from zikaron.core.retrieval.eligibility import Consumer, Scope
from zikaron.core.retrieval.query import ExternalQuery
from zikaron.core.retrieval.ranking import RankedMemory
from zikaron.core.retrieval.retrieve import RetrievalSettings, retrieve
from zikaron.core.store import transactions

#: `schema.md` §Bounds: the **output** budget, not retrieval depth. Per-arm depth is `fusion_depth`
#: and lives in configuration precisely so that asking for a different number of results cannot
#: change the ranking algorithm.
LIMIT_MIN: Final = 1
LIMIT_MAX: Final = 50
LIMIT_DEFAULT: Final = 5


@dataclass(frozen=True, slots=True)
class ReadCall:
    """What both read verbs hold constant: who is calling, the parameters, and the artifact.

    The same bundling `IndexedCall` uses and for the same reason — every entry point needs all
    three, none changes partway through a call, and keeping them apart invites a call site that
    pairs one store's encoder with another's context.
    """

    ctx: CallParams
    settings: RetrievalSettings
    encoder: Encoder


@dataclass(frozen=True, slots=True)
class SearchHit:
    """`zikaron_memory_search`'s per-row payload: exactly the seven fields the tool surface states.

    `state` is here so triage can see a demoted row for what it is. `version` is not, and that is
    the tool surface's own decision rather than an omission — see this module's docstring.
    """

    uuid: str
    gist: str
    tier: Tier
    state: RowState
    created_at: str
    updated_at: str
    superseded_by: str | None


def _hit(ranked: RankedMemory) -> SearchHit:
    row = ranked.row
    return SearchHit(
        uuid=row.uuid,
        gist=row.gist,
        tier=row.tier,
        state=row.state,
        created_at=row.created_at,
        updated_at=row.updated_at,
        superseded_by=row.superseded_by,
    )


def _reject_limit(limit: int) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BOUNDS, field="limit", limit=f"{LIMIT_MIN}-{LIMIT_MAX}", actual=limit
    )


def _checked_limit(limit: int) -> int:
    """`limit` if it is within `schema.md` §Bounds, else `bounds` — rung 1 of the ladder.

    Checked here as well as at whatever boundary deserializes the request, for the reason
    `EffectiveConfig` validates itself: "the only caller checks first" is a fact about today's call
    sites rather than a property of this function, and an unchecked `limit` silently changes how
    much of the pool a caller sees.
    """
    if not LIMIT_MIN <= limit <= LIMIT_MAX:
        raise _reject_limit(limit)
    return limit


def _termination(dense: ArmOutcome, lexical: ArmOutcome) -> ArmTermination:
    """Both arms' depth-and-reason pairs, as the one value the two read events share.

    One function because the two kinds report the identical four fields in the identical way, and a
    second transcription is how one kind's `dense_stop_reason` comes to mean something the other's
    does not.
    """
    return ArmTermination(
        dense_depth_reached=dense.depth_reached,
        dense_stop_reason=dense.stop_reason,
        lexical_depth_reached=lexical.depth_reached,
        lexical_stop_reason=lexical.stop_reason,
    )


def _query_shape(external: ExternalQuery) -> QueryShape:
    """What the query cost and whether either arm had to give something up to run it."""
    return QueryShape(
        query_tokens=external.query_tokens,
        query_truncated=external.query_truncated,
        lexical_skipped=external.prepared.lexical.skipped,
    )


async def _prepare(text: str, *, call: ReadCall) -> ExternalQuery:
    """Build both arms of an external query, keeping the embedding off the event loop.

    Outside any transaction, like the write path's own preflight and for the same reason: a cold
    model load costs hundreds of milliseconds, and holding a transaction open across it would make
    every concurrent writer's `busy_timeout` a function of model-load time.
    """
    return await asyncio.to_thread(
        query.external_query,
        text,
        encoder=call.encoder,
        prefix=call.settings.embed_prefix_query,
        max_terms=call.settings.fts_query_max_terms,
    )


def _failure_map(verb: str) -> transactions.FailureMap:
    """Name contention `store_busy` and propagate everything else, per `architecture.md` §Errors.

    A read has no `index_failed`: that code's contract names index maintenance and a rolled-back
    write, so reusing it here would be a lie in both halves, and inventing a `read_failed` would add
    a code no client can act on differently.
    """
    return lambda error: (
        ZikaronError(ErrorCode.STORE_BUSY, verb=verb) if transactions.is_contention(error) else None
    )


async def search(
    db: aiosqlite.Connection,
    *,
    text: str,
    call: ReadCall,
    limit: int = LIMIT_DEFAULT,
    include_retired: bool = False,
) -> tuple[SearchHit, ...]:
    """The pull path: fuse both arms over `text` and return the best `limit` memories.

    `include_retired` widens eligibility to rows nobody replaced — the deliberate-archaeology case —
    and they arrive demoted rather than ranked normally, because it widens *what may appear*, not
    *what is currently true*. An empty store returns an empty tuple, which is an answer rather than
    an error.

    Emits exactly one `search` event, inside the same transaction as the read it describes.

    Raises:
        ZikaronError: `BOUNDS` if `limit` is outside 1-50; `STORE_BUSY` if the store was locked or
            the read's snapshot went stale before its event could be written, which the caller may
            retry; `BAD_SUPERSESSION` if the candidate pool's supersession edges are cyclic.
    """
    budget = _checked_limit(limit)
    external = await _prepare(text, call=call)

    async def work(connection: aiosqlite.Connection) -> tuple[SearchHit, ...]:
        retrieved = await retrieve(
            connection,
            query=external.prepared,
            scope=Scope(Consumer.SEARCH, include_retired=include_retired),
            settings=call.settings,
        )
        returned = retrieved.pool[:budget]
        await memory.log_event(
            connection,
            ctx=call.ctx,
            detail=SearchDetail(
                query_chars=len(text),
                limit=budget,
                fusion_depth=call.settings.fusion_depth,
                arms=_termination(retrieved.dense, retrieved.lexical),
                query=_query_shape(external),
                include_retired=include_retired,
                n_returned=len(returned),
                uuids=tuple(ranked.row.uuid for ranked in returned),
            ),
            memory_uuid=None,
        )
        return tuple(_hit(ranked) for ranked in returned)

    return await transactions.in_one_transaction(db, work, failure=_failure_map("search"))


async def _log_surface(
    db: aiosqlite.Connection, *, rows: Sequence[RankedMemory], call: ReadCall
) -> None:
    """One `surface` row per returned memory, after the call's own `surface_call` row.

    Zero rows when nothing was eligible, which is why `surface_call` exists at all: without a
    per-call row a quiet push and a push that never happened would be the same absence of evidence.
    """
    for position, ranked in enumerate(rows, start=1):
        await memory.log_event(
            db,
            ctx=call.ctx,
            detail=SurfaceDetail(
                rank=position,
                fused_score=ranked.fused_score,
                demoted=ranked.demoted,
                demotion=ranked.row.demotion,
            ),
            memory_uuid=ranked.row.uuid,
        )


async def surface(
    db: aiosqlite.Connection, *, prompt: str, call: ReadCall, limit: int = LIMIT_DEFAULT
) -> str:
    """The push path: the block to inject for one user message, or the empty string.

    Takes no `include_retired`: `schema.md` gives it to `search` alone, so push's predicate is the
    base one — under which superseded rows are eligible and demoted, which is what D25's measurement
    requires and what the block's label then explains.

    Emits one `surface_call` event always, including when nothing was returned, followed by one
    `surface` event per returned memory sharing its `op_id`.

    Returns:
        Ready-to-print text, or `""` when nothing was eligible — no header, no empty block.

    Raises:
        ZikaronError: as `search`, minus `include_retired`'s widening.
    """
    budget = _checked_limit(limit)
    external = await _prepare(prompt, call=call)

    async def work(connection: aiosqlite.Connection) -> str:
        retrieved = await retrieve(
            connection,
            query=external.prepared,
            scope=Scope(Consumer.SURFACE),
            settings=call.settings,
        )
        returned = retrieved.pool[:budget]
        await memory.log_event(
            connection,
            ctx=call.ctx,
            detail=SurfaceCallDetail(
                prompt_chars=len(prompt),
                limit=budget,
                fusion_depth=call.settings.fusion_depth,
                arms=_termination(retrieved.dense, retrieved.lexical),
                query=_query_shape(external),
                n_returned=len(returned),
                n_demoted=sum(1 for ranked in returned if ranked.demoted),
            ),
            memory_uuid=None,
        )
        await _log_surface(connection, rows=returned, call=call)
        return block.render(returned)

    return await transactions.in_one_transaction(db, work, failure=_failure_map("surface"))
