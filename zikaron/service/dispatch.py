"""Method dispatch for the five primary-agent verbs, `health`, and their typed result shapes.

One function per RPC method, each translating a resolved envelope plus raw JSON params into a
call into `core`, and returning a typed `RpcResult` — never a bare `dict[str, object]` — that
`server.py` serializes at the one seam `serialize.RpcResult.as_json` owns. No method here opens a
transaction itself: every `core` entry point already owns its own, per `coding-standards.md` and
every module docstring in `zikaron/core/write`, `retrieval` and `records`.

`health()` is the one method with no envelope at all, dispatched separately by `server.py` before
any of this module's envelope-carrying handlers run.

The five consolidator RPC methods (`memory_plan_groups`, `memory_next_group`,
`memory_apply_merge`, `memory_apply_promote`, `memory_apply_discard`) live in
`dispatch_consolidation.py`: this module would otherwise cross
`coding-standards.md` §1's ~400-line guideline, and the split falls exactly on `architecture.md`'s
own primary-agent-versus-consolidator line. Five RPC methods, not D32's "four consolidator
tools" — `memory_plan_groups` is deliberately excluded from that count (`architecture.md`:
"`memory_plan_groups` is a service RPC and not one of D32's four consolidator tools"), since the
*tool* surface the consolidator model is given and the *RPC* surface behind it are two different
things one figure must not be quoted for both.

**Every method here carries a `memory_` prefix, and it is the same prefix its tool carries** — a
wire method is its tool's name without the leading `zikaron_`. The subsystem segment is what keeps
`memory_search` and `knowledge_search` from being one name that two dispatch tables both claim.
`memory_surface` and `memory_plan_groups` are the methods with no tool, the hook calling the first
directly and the consolidator's own client the second; `health` is the one method with no subsystem,
since it speaks for the service rather than for either store, and it carries no tool either.
"""

import os
from dataclasses import dataclass

import aiosqlite

from zikaron.core.records import memory as records
from zikaron.core.records.memory import Rewrite
from zikaron.core.retrieval.reads import ReadCall
from zikaron.core.retrieval.reads import search as core_search
from zikaron.core.retrieval.reads import surface as core_surface
from zikaron.core.write import tools as write_tools
from zikaron.core.write.tools import Conflict, WriteCall
from zikaron.service.context import ServiceContext
from zikaron.service.envelope import ResolvedEnvelope
from zikaron.service.params import (
    Handler,
    call_params,
    optional_str,
    require_bool,
    require_int,
    require_str,
    require_uuid_list,
)
from zikaron.service.serialize import (
    ConflictRecordJson,
    FetchedMemoryJson,
    NearDuplicateJson,
    RpcResult,
    SearchHitJson,
)


@dataclass(frozen=True, slots=True)
class HealthStatus(RpcResult):
    """`health()`'s result: readiness plus this store's identity, exactly as `architecture.md`
    states it — no `client` envelope in or out, and so no `session_id` field either."""

    ready: bool
    store_path: str
    store_id: str
    embed_model: str
    embed_dim: int
    schema_version: int
    pid: int

    def as_json(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "store_path": self.store_path,
            "store_id": self.store_id,
            "embed_model": self.embed_model,
            "embed_dim": self.embed_dim,
            "schema_version": self.schema_version,
            "pid": self.pid,
        }


def health(ctx: ServiceContext) -> HealthStatus:
    """`health()`: readiness and store identity, resolving no session label.

    `pid` is **this process's own** `os.getpid()`, per `architecture.md`'s
    `{ready, store_path, store_id, embed_model, embed_dim, schema_version, pid}` — never a value a
    caller supplies, which is what makes it useful for a client to log alongside `holder_pid`-style
    diagnostics without trusting anything the caller said about itself. Never fails: a service that
    can answer at all has, by construction, already opened its store (`ServiceContext.assemble`
    raises before the socket is ever opened otherwise), so `ready` is always `True` here — the
    *unreachable* case a client's start-if-absent is polling for is a connection failure this
    function is never called to answer.

    **`ready` speaks for the store, not for the encoder.** The model may still be loading behind a
    service that answers here, and a load that fails does so after the socket is already bound. So
    this is not the place a broken embedder is reported: the request that needs the model is, and
    the service stops itself rather than going on answering `ready` it cannot honour.
    """
    return HealthStatus(
        ready=True,
        store_path=str(ctx.store_path),
        store_id=ctx.store_id,
        embed_model=ctx.store.meta.embed_model,
        embed_dim=ctx.store.meta.embed_dim,
        schema_version=ctx.store.meta.schema_version,
        pid=os.getpid(),
    )


def _write_call(ctx: ServiceContext, envelope: ResolvedEnvelope) -> WriteCall:
    return WriteCall(
        ctx=call_params(envelope, max_depth=ctx.supersession_max_depth),
        index=ctx.index,
        retrieval=ctx.retrieval,
        dedup_threshold=ctx.config.get_float("dedup_threshold"),
        dedup_max=ctx.config.get_int("dedup_max"),
    )


def _read_call(ctx: ServiceContext, envelope: ResolvedEnvelope) -> ReadCall:
    return ReadCall(
        ctx=call_params(envelope, max_depth=ctx.supersession_max_depth),
        settings=ctx.retrieval,
        encoder=ctx.encoder,
    )


@dataclass(frozen=True, slots=True)
class RememberResult(RpcResult):
    """`memory_remember`'s success shape: `{uuid, version, near_duplicates}` — always a success;
    a row that did not exist a moment ago cannot lose a race to overwrite itself."""

    uuid: str
    version: int
    near_duplicates: tuple[NearDuplicateJson, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "uuid": self.uuid,
            "version": self.version,
            "near_duplicates": [one.as_json() for one in self.near_duplicates],
        }


async def remember(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> RememberResult:
    """`memory_remember(gist, content) -> {uuid, version, near_duplicates}`."""
    rewrite = Rewrite(gist=require_str(params, "gist"), content=require_str(params, "content"))
    written = await write_tools.remember(db, rewrite=rewrite, call=_write_call(ctx, envelope))
    return RememberResult(
        uuid=written.uuid,
        version=written.version,
        near_duplicates=tuple(NearDuplicateJson(one) for one in written.near_duplicates),
    )


@dataclass(frozen=True, slots=True)
class VersionResult(RpcResult):
    """`{uuid, version}` — `memory_amend`/`memory_retire`'s shared success shape."""

    uuid: str
    version: int

    def as_json(self) -> dict[str, object]:
        return {"uuid": self.uuid, "version": self.version}


@dataclass(frozen=True, slots=True)
class ConflictResult(RpcResult):
    """`{conflict: true, current: CONFLICT_RECORD}` — `memory_amend`/`memory_retire`'s shared
    rejection shape: one object, never a list, unlike the four consolidator verbs' own conflict
    shape below."""

    current: ConflictRecordJson

    def as_json(self) -> dict[str, object]:
        return {"conflict": True, "current": self.current.as_json()}


async def amend(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> VersionResult | ConflictResult:
    """`memory_amend(uuid, version, gist, content) -> {uuid, version} | {conflict, current}`."""
    rewrite = Rewrite(gist=require_str(params, "gist"), content=require_str(params, "content"))
    outcome = await write_tools.amend(
        db,
        uuid=require_str(params, "uuid"),
        version=require_int(params, "version"),
        rewrite=rewrite,
        call=_write_call(ctx, envelope),
    )
    if isinstance(outcome, Conflict):
        return ConflictResult(current=ConflictRecordJson(outcome.current))
    return VersionResult(uuid=outcome.uuid, version=outcome.version)


async def retire(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> VersionResult | ConflictResult:
    """`memory_retire(uuid, version, superseded_by?) -> {uuid, version} | {conflict, current}`."""
    outcome = await write_tools.retire(
        db,
        uuid=require_str(params, "uuid"),
        version=require_int(params, "version"),
        superseded_by=optional_str(params, "superseded_by"),
        call=_write_call(ctx, envelope),
    )
    if isinstance(outcome, Conflict):
        return ConflictResult(current=ConflictRecordJson(outcome.current))
    return VersionResult(uuid=outcome.uuid, version=outcome.version)


@dataclass(frozen=True, slots=True)
class SearchResult(RpcResult):
    """`memory_search`'s success shape: a **bare list** of hits, per `architecture.md`'s
    `-> [{uuid, gist, tier, state, created_at, updated_at, superseded_by}]` — no wrapping key."""

    hits: tuple[SearchHitJson, ...]

    def as_json(self) -> list[object]:
        return [one.as_json() for one in self.hits]


async def search(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> SearchResult:
    """`memory_search(query, limit?, include_retired?) -> [SearchHit, ...]` — a bare list."""
    hits = await core_search(
        db,
        text=require_str(params, "query"),
        call=_read_call(ctx, envelope),
        limit=require_int(params, "limit", default=5),
        include_retired=require_bool(params, "include_retired", default=False),
    )
    return SearchResult(hits=tuple(SearchHitJson(hit) for hit in hits))


@dataclass(frozen=True, slots=True)
class SurfaceResult(RpcResult):
    """`memory_surface`'s success shape: `{text}` — the push path's ready-to-print block."""

    text: str

    def as_json(self) -> dict[str, object]:
        return {"text": self.text}


async def surface(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> SurfaceResult:
    """`memory_surface(prompt, limit?) -> {text}` — the push path's ready-to-print block."""
    text = await core_surface(
        db,
        prompt=require_str(params, "prompt"),
        call=_read_call(ctx, envelope),
        limit=require_int(params, "limit", default=5),
    )
    return SurfaceResult(text=text)


@dataclass(frozen=True, slots=True)
class FetchResult(RpcResult):
    """`memory_fetch`'s success shape: `{records, missing}`."""

    records: tuple[FetchedMemoryJson, ...]
    missing: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "records": [one.as_json() for one in self.records],
            "missing": list(self.missing),
        }


async def fetch(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> FetchResult:
    """`memory_fetch(uuids) -> {records, missing}`."""
    records_found, missing = await records.fetch(
        db,
        uuids=require_uuid_list(params, "uuids"),
        ctx=call_params(envelope, max_depth=ctx.supersession_max_depth),
    )
    return FetchResult(
        records=tuple(FetchedMemoryJson(one) for one in records_found),
        missing=tuple(missing),
    )


#: Every primary-agent method this module handles, by its wire name. `dispatch_consolidation.py`
#: contributes the other five; `server.py` merges both tables and adds `health` separately, since
#: `health` takes no envelope and so does not fit this table's own shape.
PRIMARY_METHODS: dict[str, Handler] = {
    "memory_remember": remember,
    "memory_amend": amend,
    "memory_retire": retire,
    "memory_search": search,
    "memory_surface": surface,
    "memory_fetch": fetch,
}
