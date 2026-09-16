"""The group-level candidate query: the one external query the system builds from stored prose.

`consolidation.md` §"What `candidates` actually is" and `retrieval.md` §"Query construction" are
normative. Two rules meet here and neither is obvious from the other:

**Whole gists are dropped rather than one being cut in half.** A half-truncated gist is a garbled
query; a shorter well-formed concatenation is not. So the concatenation **stops before** the gist
that would exceed the embedder's input budget, and `n_gists_used` reports how many fitted.

**The budget is checked on the assembled string, never on the sum of the pieces' counts.** A
tokenizer re-tokenizes across every join, so neither count bounds the other — which is the same
rule the write path's chunking preflight and the read path's query preflight both follow, through
the same counter.

Separate from the serve loop because it is the only *retrieval* concern in the serve: it decides
which long-term records a group is shown against, and it would be equally correct if the lifecycle
around it were different.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import aiosqlite

from zikaron.core.consolidation.context import ConsolidationCall
from zikaron.core.consolidation.payload import GroupRecord, RankedRecord
from zikaron.core.indexing import encoder as encoding
from zikaron.core.records import memory as records
from zikaron.core.retrieval import query as query_construction
from zikaron.core.retrieval.eligibility import Consumer, Scope
from zikaron.core.retrieval.query import PreparedQuery
from zikaron.core.retrieval.retrieve import retrieve

#: How many long-term records beyond the anchor one serve delivers. `consolidation.md`: "at most,
# one
#: anchor plus four candidates — the '5 candidate memories' the consolidator prompt promises". A
# fixed
#: number rather than a config key, because it is a claim the shipped prompt makes.
MAX_CANDIDATES: Final = 4

#: What joins the served set's gists into the candidate query. The same single newline an internal
#: query's lexical side uses between `gist` and `content`, so there is one convention; it is part of
#: what the budget is counted over, which is the only reason the choice needs stating at all.
_GIST_JOIN: Final = "\n"


@dataclass(frozen=True, slots=True)
class GroupQuery:
    """The candidate query built from the served set's gists, and how many of them fitted.

    `prepared` is `None` when **no** gist fitted, which is not a fallback but the answer: the
    candidates are the persisted set a later `merge` is authorized to target, so a query assembled
    from the configured prefix and nothing else would authorize whichever records happen to sit
    nearest an empty query. `n_gists_used = 0` is what tells an operator that is what happened.
    """

    prepared: PreparedQuery | None
    n_gists_used: int


async def build_group_query(
    served: Sequence[GroupRecord], *, call: ConsolidationCall
) -> GroupQuery:
    """Concatenate the served set's gists under the embedder's input budget, then embed the result.

    Whole gists are dropped rather than one being cut in half, because a half-truncated gist is a
    garbled query while a shorter well-formed concatenation is not. The concatenation **stops
    before** the gist that would exceed the budget, and the budget is checked on the **assembled**
    string — prefix, separators and all — never as the sum of the pieces' own counts, because a
    tokenizer re-tokenizes across every join and the sum bounds neither direction.

    This is the one place in the system where an *external* query is assembled from stored prose, so
    both arms follow the external rules: the concatenation is embedded through the dense preflight
    and the same concatenation goes through the lexical term constructor.

    Deterministic, because group order is total and the served set is committed state — which is
    what makes a re-serve's narrower query text a defined consequence rather than a surprise.
    """
    encoder = call.index.encoder
    prefix = call.retrieval.embed_prefix_query
    kept: list[str] = []
    for record in served:
        candidate = _GIST_JOIN.join([*kept, record.gist])
        assembled = encoding.assembled_tokens(prefix, candidate, encoder=encoder)
        if assembled > encoder.max_sequence_tokens:
            break
        kept.append(record.gist)
    if not kept:
        return GroupQuery(prepared=None, n_gists_used=0)
    external = await asyncio.to_thread(
        query_construction.external_query,
        _GIST_JOIN.join(kept),
        encoder=encoder,
        prefix=prefix,
        max_terms=call.retrieval.fts_query_max_terms,
    )
    return GroupQuery(prepared=external.prepared, n_gists_used=len(kept))


async def select(
    db: aiosqlite.Connection,
    *,
    group_query: GroupQuery,
    excluded: frozenset[str],
    call: ConsolidationCall,
) -> tuple[RankedRecord, ...]:
    """Up to `MAX_CANDIDATES` further active long-term records, from **one** group-level query.

    One query over the whole served set rather than the union of each member's own top five: that
    union has no cap, no defined order, and would grow with group size.

    `excluded` is the anchor plus **every** member of the group — the frozen plan-time universe, not
    only the served set — because a member the consolidator has already dispositioned is not a
    record to be shown back to it, and a member promoted in place is active long-term and would
    otherwise surface here while not being in the authorization set anyway.

    An empty result is normal rather than an error: early in a store's life the long-term tier is
    empty, so every group is an orphan group with no anchor and no candidates, and the
    consolidator's only available verbs are `promote` and `discard`.
    """
    prepared = group_query.prepared
    if prepared is None:
        return ()
    retrieved = await retrieve(
        db, query=prepared, scope=Scope(Consumer.CONSOLIDATION), settings=call.retrieval
    )
    found: list[RankedRecord] = []
    for ranked in retrieved.pool:
        if ranked.row.uuid in excluded:
            continue
        row = await records.load(db, ranked.row.uuid)
        if row is None:
            # A pooled uuid with no row is a row that vanished between the arm query and this read,
            # which one transaction makes impossible. Dropped rather than guessed at, for the same
            # reason `ranking.rank` drops one: a candidate is a merge *authorization*, so inventing
            # prose for it would authorize a rewrite of something the serve never showed.
            continue
        found.append(RankedRecord(record=GroupRecord.of(row), rank=len(found) + 1))
        if len(found) == MAX_CANDIDATES:
            break
    return tuple(found)
