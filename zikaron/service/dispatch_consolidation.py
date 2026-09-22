"""Method dispatch for `memory_plan_groups`, `memory_next_group`, and the three consolidator
write methods.

Split from `dispatch.py` on `architecture.md`'s own primary-agent-versus-consolidator line, and
because the combined module would otherwise cross `coding-standards.md` §1's ~400-line guideline.
Every handler here calls `_consolidation_call`, which rejects a non-consolidator envelope as a
declared `BOUNDS` error naming `client.kind` — `server.py` dispatches purely by method name, so an
`mcp`-kind client naming one of these methods directly *is* reachable;
nothing about the method table itself prevents it, since method names and `client.kind` are
independent fields of one request. `ConsolidationCall`'s own `client_kind == "consolidator"`
invariant exists to protect receipt scoping, not to police callers, so `_consolidation_call` checks
before constructing that type rather than letting an avoidable `ValueError` reach `server.py`'s
protocol-level internal-error fallback for a case the design already has a name for.
"""

from dataclasses import dataclass

import aiosqlite

from zikaron.core.consolidation import planning, serving
from zikaron.core.consolidation.context import ConsolidationCall
from zikaron.core.consolidation.payload import (
    Busy,
    GroupConflict,
    MergeTarget,
    NamedRow,
    RunDone,
    ServedGroup,
)
from zikaron.core.consolidation.verbs import discard, merge, promote
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.events import ClientKind
from zikaron.core.records.memory import Rewrite
from zikaron.service.context import ServiceContext
from zikaron.service.envelope import ResolvedEnvelope
from zikaron.service.params import Handler, call_params, require_int, require_object, require_str
from zikaron.service.serialize import (
    ConflictRecordJson,
    GroupRecordJson,
    RankedRecordJson,
    RpcResult,
    ShardJson,
)


def _named_row(params: dict[str, object], name: str) -> NamedRow:
    row = require_object(params, name)
    return NamedRow(
        uuid=require_str(row, "uuid"), expected_version=require_int(row, "expected_version")
    )


def _absorb_list(params: dict[str, object]) -> tuple[NamedRow, ...]:
    raw = params.get("absorb")
    if not isinstance(raw, list):
        raise ZikaronError(ErrorCode.BOUNDS, field="absorb", limit="a list", actual=raw)
    rows: list[NamedRow] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ZikaronError(
                ErrorCode.BOUNDS, field="absorb", limit="a list of objects", actual=item
            )
        rows.append(
            NamedRow(
                uuid=require_str(item, "uuid"),
                expected_version=require_int(item, "expected_version"),
            )
        )
    return tuple(rows)


def _consolidation_call(ctx: ServiceContext, envelope: ResolvedEnvelope) -> ConsolidationCall:
    """A `ConsolidationCall` for this envelope, rejecting a non-consolidator caller as a
    declared, actionable `bounds` error rather than letting it reach `ConsolidationCall`'s own
    `client_kind == "consolidator"` invariant and surface as an opaque internal-error response.

    That invariant exists to protect receipt scoping (`ConsolidationCall.__post_init__`'s own
    docstring), not to police who may call these methods — `server.py` dispatches purely by
    method name, so an `mcp`-kind client naming `memory_apply_merge`/`memory_next_group`/etc.
    directly **is** reachable; nothing about the method table itself prevents it. Checking here,
    before constructing the type whose invariant would otherwise raise a bare `ValueError`, is
    what turns "a caller supplied the wrong client kind" into a response that names the field and
    its problem rather than one indistinguishable from a genuine server bug.

    Raises:
        ZikaronError: `BOUNDS` naming `client.kind` if the envelope's kind is not
            `"consolidator"`.
    """
    if envelope.kind != ClientKind.CONSOLIDATOR.value:
        raise ZikaronError(
            ErrorCode.BOUNDS,
            field="client.kind",
            limit=ClientKind.CONSOLIDATOR.value,
            actual=envelope.kind,
        )
    return ConsolidationCall(
        ctx=call_params(envelope, max_depth=ctx.supersession_max_depth),
        pid=envelope.pid,
        settings=ctx.consolidation,
        retrieval=ctx.retrieval,
        index=ctx.index,
    )


@dataclass(frozen=True, slots=True)
class ServedGroupResult(RpcResult):
    """`memory_next_group`'s success shape, exactly as `architecture.md` states every field —
    `candidates` is a list of **flat** `{uuid, expected_version, gist, content, created_at, rank}`
    objects, never a nested `{record: {...}, rank}`."""

    group_id: str
    run_id: str
    anchor: GroupRecordJson | None
    anchor_vacated: bool
    journal_entries: tuple[GroupRecordJson, ...]
    candidates: tuple[RankedRecordJson, ...]
    shard: ShardJson
    serve_count: int
    n_gists_used: int
    remaining_groups: int

    def as_json(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "run_id": self.run_id,
            "anchor": None if self.anchor is None else self.anchor.as_json(),
            "anchor_vacated": self.anchor_vacated,
            "journal_entries": [one.as_json() for one in self.journal_entries],
            "candidates": [one.as_json() for one in self.candidates],
            "shard": self.shard.as_json(),
            "serve_count": self.serve_count,
            "n_gists_used": self.n_gists_used,
            "remaining_groups": self.remaining_groups,
        }

    @classmethod
    def of(cls, served: ServedGroup) -> "ServedGroupResult":
        return cls(
            group_id=served.group_id,
            run_id=served.run_id,
            anchor=None if served.anchor is None else GroupRecordJson(served.anchor),
            anchor_vacated=served.anchor_vacated,
            journal_entries=tuple(GroupRecordJson(entry) for entry in served.journal_entries),
            candidates=tuple(
                RankedRecordJson(record=ranked.record, rank=ranked.rank)
                for ranked in served.candidates
            ),
            shard=ShardJson(served.shard),
            serve_count=served.serve_count,
            n_gists_used=served.n_gists_used,
            remaining_groups=served.remaining_groups,
        )


@dataclass(frozen=True, slots=True)
class RunDoneResult(RpcResult):
    """`{done: true}` — this run has nothing left to serve."""

    def as_json(self) -> dict[str, object]:
        return {"done": True}


@dataclass(frozen=True, slots=True)
class BusyResult(RpcResult):
    """`{busy: true, holder_session, holder_pid, expires_at}` — an effectively-active run belongs
    to a different `(session_id, pid)`."""

    holder_session: str
    holder_pid: int
    expires_at: str

    def as_json(self) -> dict[str, object]:
        return {
            "busy": True,
            "holder_session": self.holder_session,
            "holder_pid": self.holder_pid,
            "expires_at": self.expires_at,
        }


async def next_group(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],  # noqa: ARG001 — every `Handler` shares this signature; this method
    # takes no params of its own, but the dispatch table's uniform call shape still passes one.
) -> ServedGroupResult | RunDoneResult | BusyResult:
    """`memory_next_group() -> ServedGroup | {done: true} | {busy: true, ...}`."""
    outcome = await serving.next_group(db, call=_consolidation_call(ctx, envelope))
    if isinstance(outcome, RunDone):
        return RunDoneResult()
    if isinstance(outcome, Busy):
        return BusyResult(
            holder_session=outcome.holder_session,
            holder_pid=outcome.holder_pid,
            expires_at=outcome.expires_at,
        )
    return ServedGroupResult.of(outcome)


@dataclass(frozen=True, slots=True)
class PlanGroupsResult(RpcResult):
    """`memory_plan_groups()`'s success shape: `{run_id, status}`."""

    run_id: str
    status: str

    def as_json(self) -> dict[str, object]:
        return {"run_id": self.run_id, "status": self.status}


async def plan_groups(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],  # noqa: ARG001 — see `next_group`'s own note on this signature.
) -> PlanGroupsResult:
    """`memory_plan_groups() -> {run_id, status}` — the explicit takeover RPC.

    Not one of D32's four consolidator tools: reachable only by direct RPC, per
    `architecture.md`'s whole argument for why tool omission is what D32 relies on rather than a
    socket-level boundary.
    """
    run = await planning.plan_groups(db, call=_consolidation_call(ctx, envelope))
    return PlanGroupsResult(run_id=run.run_id, status=str(run.status))


@dataclass(frozen=True, slots=True)
class GroupConflictResult(RpcResult):
    """`{conflict: true, current: [...], remaining_uuids: [...]}` — the three consolidator write
    verbs' shared rejection shape: a **list** of records, unlike the primary-agent verbs' single
    object, since a consolidator call names several rows and one mismatch returns every
    conflicting record."""

    current: tuple[ConflictRecordJson, ...]
    remaining_uuids: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "conflict": True,
            "current": [one.as_json() for one in self.current],
            "remaining_uuids": list(self.remaining_uuids),
        }

    @classmethod
    def of(cls, conflict: GroupConflict) -> "GroupConflictResult":
        return cls(
            current=tuple(ConflictRecordJson(record) for record in conflict.current),
            remaining_uuids=conflict.remaining_uuids,
        )


@dataclass(frozen=True, slots=True)
class MergedResult(RpcResult):
    """`memory_apply_merge`'s success shape: `{uuid, version, remaining_uuids, group_complete}` —
    identical in shape to `PromotedResult`, and a separate type anyway, since the two verbs are
    not interchangeable at any call site that matches on the outcome's own type."""

    uuid: str
    version: int
    remaining_uuids: tuple[str, ...]
    group_complete: bool

    def as_json(self) -> dict[str, object]:
        return {
            "uuid": self.uuid,
            "version": self.version,
            "remaining_uuids": list(self.remaining_uuids),
            "group_complete": self.group_complete,
        }


async def consolidator_merge(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> MergedResult | GroupConflictResult:
    """`memory_apply_merge(group_id, target, gist, content, absorb) -> Merged | GroupConflict`."""
    rewrite = Rewrite(gist=require_str(params, "gist"), content=require_str(params, "content"))
    outcome = await merge(
        db,
        group_id=require_str(params, "group_id"),
        target=MergeTarget(row=_named_row(params, "target"), rewrite=rewrite),
        absorb=_absorb_list(params),
        call=_consolidation_call(ctx, envelope),
    )
    if isinstance(outcome, GroupConflict):
        return GroupConflictResult.of(outcome)
    return MergedResult(
        uuid=outcome.uuid,
        version=outcome.version,
        remaining_uuids=outcome.remaining_uuids,
        group_complete=outcome.group_complete,
    )


@dataclass(frozen=True, slots=True)
class PromotedResult(RpcResult):
    """`memory_apply_promote`'s success shape — identical in shape to `MergedResult`, a separate
    type for the same reason."""

    uuid: str
    version: int
    remaining_uuids: tuple[str, ...]
    group_complete: bool

    def as_json(self) -> dict[str, object]:
        return {
            "uuid": self.uuid,
            "version": self.version,
            "remaining_uuids": list(self.remaining_uuids),
            "group_complete": self.group_complete,
        }


async def consolidator_promote(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> PromotedResult | GroupConflictResult:
    """`memory_apply_promote(group_id, gist, content, absorb) -> Promoted | GroupConflict`."""
    rewrite = Rewrite(gist=require_str(params, "gist"), content=require_str(params, "content"))
    outcome = await promote(
        db,
        group_id=require_str(params, "group_id"),
        rewrite=rewrite,
        absorb=_absorb_list(params),
        call=_consolidation_call(ctx, envelope),
    )
    if isinstance(outcome, GroupConflict):
        return GroupConflictResult.of(outcome)
    return PromotedResult(
        uuid=outcome.uuid,
        version=outcome.version,
        remaining_uuids=outcome.remaining_uuids,
        group_complete=outcome.group_complete,
    )


@dataclass(frozen=True, slots=True)
class DiscardedResult(RpcResult):
    """`memory_apply_discard`'s success shape: `{retired, remaining_uuids, group_complete}`."""

    retired: int
    remaining_uuids: tuple[str, ...]
    group_complete: bool

    def as_json(self) -> dict[str, object]:
        return {
            "retired": self.retired,
            "remaining_uuids": list(self.remaining_uuids),
            "group_complete": self.group_complete,
        }


async def consolidator_discard(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> DiscardedResult | GroupConflictResult:
    """`memory_apply_discard(group_id, absorb, reason) -> Discarded | GroupConflict`."""
    outcome = await discard(
        db,
        group_id=require_str(params, "group_id"),
        absorb=_absorb_list(params),
        reason=require_str(params, "reason"),
        call=_consolidation_call(ctx, envelope),
    )
    if isinstance(outcome, GroupConflict):
        return GroupConflictResult.of(outcome)
    return DiscardedResult(
        retired=outcome.retired,
        remaining_uuids=outcome.remaining_uuids,
        group_complete=outcome.group_complete,
    )


#: The service-RPC surface `architecture.md` §"Service RPC surface" names beyond the five
#: primary-agent verbs: `memory_plan_groups`/`memory_next_group` (both consolidator-gated, though
#: `memory_plan_groups` is reachable by direct RPC rather than through any tool) and the three
#: consolidator write verbs — named on the wire as `memory_apply_merge`/`memory_apply_promote`/
#: `memory_apply_discard`, **not** the bare `merge`/`promote`/`discard` the design's own prose uses
#: when discussing the underlying verb/concept elsewhere (the validation-ladder section, for
#: instance, writes "consolidator verbs (`merge`, `promote`, `discard`)"). Those are two different
#: things: the RPC surface section is the one place the document states the actual wire method name,
#: and it is unambiguous — a client built against it would otherwise receive `METHOD_NOT_FOUND`
#: for every write.
CONSOLIDATOR_METHODS: dict[str, Handler] = {
    "memory_plan_groups": plan_groups,
    "memory_next_group": next_group,
    "memory_apply_merge": consolidator_merge,
    "memory_apply_promote": consolidator_promote,
    "memory_apply_discard": consolidator_discard,
}
