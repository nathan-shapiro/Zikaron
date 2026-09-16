"""Method dispatch for knowledge search, and the shape it answers in.

One method, in its own module rather than in `dispatch.py`, because it is a different subsystem
rather than a sixth primary-agent verb: it reads the knowledge-base registry and each corpus's own
database, and touches none of the memory store's tables beyond that registry.

**The result forwards `core`'s own payload instead of restating its shape.** Every other wire shape
here is a dataclass whose `as_json` builds the object field by field, which is what keeps a renamed
field a type error rather than a `KeyError`. This one cannot be: the response's byte cap is enforced
by measuring the encoded answer, so the object that is measured and the object that is sent have to
be the same one — and building it twice is exactly how the measurement comes to describe something
other than what was delivered.
"""

from dataclasses import dataclass

import aiosqlite

from zikaron.core.knowledge import groups
from zikaron.service.context import ServiceContext
from zikaron.service.envelope import ResolvedEnvelope
from zikaron.service.params import Handler, optional_str_list, require_int, require_str
from zikaron.service.serialize import RpcResult

#: What `limit_per_kb` means when a caller does not say. Stated here as well as in the tool's own
#: signature because a direct RPC caller never passes through that signature.
DEFAULT_LIMIT_PER_KB = 5


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult(RpcResult):
    """`zikaron_knowledge_search`'s success shape: `{groups, groups_dropped,
    known_knowledge_bases}` — the last empty unless a name matched no corpus."""

    response: groups.SearchResponse

    def as_json(self) -> dict[str, object]:
        return self.response.payload()


async def knowledge_search(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,  # noqa: ARG001 — every handler takes one; this method records no event.
    params: dict[str, object],
) -> KnowledgeSearchResult:
    """`knowledge_search(query, knowledge_bases?, limit_per_kb?)
    -> {groups, groups_dropped, known_knowledge_bases}`."""
    request = groups.SearchRequest(
        text=require_str(params, "query"),
        limit_per_kb=require_int(params, "limit_per_kb", default=DEFAULT_LIMIT_PER_KB),
        names=optional_str_list(params, "knowledge_bases"),
    )
    response = await groups.search_all(
        ctx.store_directory, db, ctx.config, request, encoder=ctx.encoder
    )
    return KnowledgeSearchResult(response=response)


#: The knowledge methods this module handles, by wire name. `server.py` merges this table with the
#: primary and consolidator ones.
KNOWLEDGE_METHODS: dict[str, Handler] = {"knowledge_search": knowledge_search}
