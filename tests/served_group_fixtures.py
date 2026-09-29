"""Store states a consolidation group can be served from **through the dispatch layer**.

`consolidation_fixtures.py` is the `core`-level counterpart, built on `retrieval_fixtures.Harness`;
this one writes through `dispatch.remember` against a `ServiceContext`, which is what a test driving
the RPC surface needs.

**Grouping is emergent, so these states cannot be inserted.** `plan_groups` uses retrieval as its
adjacency function, so a served group exists only because two rows' embeddings were close enough.
`FakeEncoder.planned` is what makes that deterministic, and the angles *are* the fixture: a second
copy of these constants would be a second set of angles to keep inside `orphan_edge_cutoff`.
"""

from tests.fake_encoder import FakeEncoder, unit_at
from tests.service_fixtures import envelope
from zikaron.core.events import ClientKind
from zikaron.core.indexing.chunking import PREFIX_SEPARATOR
from zikaron.service import dispatch
from zikaron.service.context import ServiceContext

#: The primary agent writing the journal rows, and the consolidator that serves them. Two envelopes
#: rather than one, because the consolidator methods refuse an `mcp` envelope on `client.kind` —
#: which is the boundary D32 rests on and not something a fixture should paper over.
AGENT = envelope(session_id="agent-session", kind="mcp", pid=100)
CONSOLIDATOR = envelope(session_id="agent-session", kind=ClientKind.CONSOLIDATOR.value, pid=4242)

# Two prose pairs at a 10-degree angle: cosine ~0.985, comfortably above the default
# `orphan_edge_cutoff` (0.65), and each other's only neighbour, so they satisfy `mutual_k`'s
# default of 5 trivially and form one orphan group deterministically.
_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_B = ("proto codegen also fails locally", "the same compiler drift shows up in the dev container")

# A long-term anchor plus one journal member at a close angle, so the anchored group's `merge`
# target is legally the long-term row rather than a journal member — `merge` only ever accepts a
# row already in the group's persisted anchor/candidate set, never a fellow journal member, so an
# orphan pair (no long-term row at all) has nothing legal to `merge` into.
ANCHOR = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
MEMBER = ("proto codegen also fails locally", "the same compiler drift shows up in the container")


async def set_long_term(ctx: ServiceContext, uuid: str) -> None:
    """Lift one row's tier directly, which is what `promote` exists to do and no test may call yet.

    A planning fixture needs long-term rows to exist before any consolidation verb has run.
    """
    await ctx.store.connection.execute(
        "UPDATE memory SET tier = 'long_term' WHERE uuid = ?", (uuid,)
    )
    await ctx.store.connection.commit()


def plan_embedding(ctx: ServiceContext, gist: str, content: str, degrees: float) -> None:
    """Fix where one record's prose lands on the unit circle, before the write that embeds it."""
    assert isinstance(ctx.encoder, FakeEncoder)
    ctx.encoder.planned[f"{gist}{PREFIX_SEPARATOR}{content}"] = unit_at(degrees, ctx.encoder.dim)


async def write_orphan_pair(ctx: ServiceContext) -> tuple[str, str]:
    """Two journal rows close enough to form one orphan group, with no long-term row at all."""
    for gist, content, degrees in ((*_A, 0.0), (*_B, 10.0)):
        plan_embedding(ctx, gist, content, degrees)
    first = await dispatch.remember(
        ctx.store.connection, ctx, AGENT, {"gist": _A[0], "content": _A[1]}
    )
    second = await dispatch.remember(
        ctx.store.connection, ctx, AGENT, {"gist": _B[0], "content": _B[1]}
    )
    return first.uuid, second.uuid


async def write_anchored_pair(ctx: ServiceContext) -> tuple[str, str]:
    """Returns `(anchor_uuid, member_uuid)` — the anchor already `tier='long_term'`."""
    for gist, content, degrees in ((*ANCHOR, 0.0), (*MEMBER, 10.0)):
        plan_embedding(ctx, gist, content, degrees)
    anchor = await dispatch.remember(
        ctx.store.connection, ctx, AGENT, {"gist": ANCHOR[0], "content": ANCHOR[1]}
    )
    await set_long_term(ctx, anchor.uuid)
    member = await dispatch.remember(
        ctx.store.connection, ctx, AGENT, {"gist": MEMBER[0], "content": MEMBER[1]}
    )
    return anchor.uuid, member.uuid
