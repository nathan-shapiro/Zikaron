"""The four consolidator tools, and the `memory_plan_groups` lazy-takeover bridge in front of them.

`architecture.md` §"Consolidator tool surface (4 tools, separate agent)" and its own
§"Consolidation lifecycle" §Planning are both normative here. Three things this module owns and
nothing else in the codebase does, because they exist only at the boundary between a tool call and
the RPC surface behind it:

- **`memory_plan_groups` is a service RPC, not one of the four tools**
  (`dispatch_consolidation.py`'s own docstring says so). No `@mcp.tool` names it; it is called
  internally, by this module, as a prerequisite of forwarding the first `memory_next_group`.
- **The three-state bridge** (`unplanned | ready | failed`) that decides, on every
  `memory_next_group` call, whether `memory_plan_groups` must run first. The state table is in
  `_PlanBridge` below.
- **The wire method names differ from the tool names** for the three write verbs:
  `zikaron_memory_merge` calls `memory_apply_merge`, `zikaron_memory_promote` calls
  `memory_apply_promote`, `zikaron_memory_discard` calls `memory_apply_discard`. Everywhere else a
  wire method is its tool's name without the `zikaron_` prefix; these three carry an extra `apply_`
  because the RPC applies a decision the tool merely names. The mismatch is worth stating because
  deriving one name from the other is the natural thing to do and fails here: a client that did so
  would ask for a method the service does not have and be told only `METHOD_NOT_FOUND`.

Every tool here sends `client.kind = "consolidator"`, never `"mcp"` — the one field that
distinguishes this process's requests from the primary agent's, and what
`dispatch_consolidation.py`'s own `_consolidation_call` checks before doing anything else.
"""

import asyncio
from enum import Enum

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from zikaron.core.errors import ZikaronError
from zikaron.mcp import spill
from zikaron.mcp.connection import AmbiguousMutationError, ServiceConnection
from zikaron.mcp.errors import ServiceRejectionError, TransportFailureError, response_to_tool_result
from zikaron.mcp.spill import SpillPolicy

_CLIENT_KIND = "consolidator"

#: `errors.ErrorCode.STORE_BUSY`'s wire code, named here rather than imported from
#: `zikaron.core.errors` — this module only needs to recognize the one numeric value the bridge
#: reacts to, and importing the whole `ErrorCode` enum for one comparison would pull `zikaron.core`
#: into a module whose entire job is translation, not policy, over a value this project's own
#: `coding-standards.md` §7 already requires never be a bare integer at any *raise* site; this is
#: a *recognition* site reading a value the service already committed to that contract at, so the
#: number is the wire contract itself rather than a literal standing in for one.
_STORE_BUSY_CODE = -32020


class _BridgeState(Enum):
    """The three-state machine `architecture.md` names exactly:

    | state | on forwarded `memory_next_group` | on the outcome |
    |---|---|---|
    | `UNPLANNED` | plan first, forward after success | success->`READY`; busy->stay; else->fail |
    | `READY` | forward directly, plan nothing | - |
    | `FAILED` | answer the recorded failure, forward nothing | terminal |
    """

    UNPLANNED = "unplanned"
    READY = "ready"
    FAILED = "failed"


class _PlanBridge:
    """Per-process, in-memory state for the `memory_plan_groups` bridge — never persisted, because a
    fresh MCP server process is a fresh guard by construction (`research/kiro-mcp-lifecycle-probe.
    md`: one process per agent spawn), and the bound this bridge enforces is exactly "one
    successful takeover per **process**."
    """

    def __init__(self) -> None:
        self._state = _BridgeState.UNPLANNED
        self._failure: ServiceRejectionError | TransportFailureError | None = None
        # An `asyncio.Lock`, not a plain flag: FastMCP dispatches each `tools/call` as its own
        # task on one event loop, so two `zikaron_memory_next_group` calls arriving close together
        # can both observe `UNPLANNED` before either one's own `await connection.request(...)` for
        # `memory_plan_groups` actually resumes — the first `await` inside `_connected_socket()`
        # (`_read_store_identity` opening the store) is already a yield point. Without
        # serialization here, both tasks would proceed to their own successful `memory_plan_groups`
        # call, which is two takeovers from one process and a direct violation of "at most one
        # **successful** takeover per client process." The lock makes the whole
        # check-then-act sequence — read state, decide, call, update state — atomic with respect
        # to every other call on this same bridge.
        self._lock = asyncio.Lock()

    async def ensure_planned(self, connection: ServiceConnection) -> None:
        """Run the bridge for one forwarded `memory_next_group` call: do nothing if already
        `READY`, re-raise the terminal failure if `FAILED`, and otherwise call
        `memory_plan_groups` — moving to `READY` on success, staying `UNPLANNED` (so the *next*
        call retries) on `store_busy`, or
        moving to `FAILED` on anything else.

        Raises:
            ServiceRejectionError: `memory_plan_groups` answered a JSON-RPC error — `store_busy`
                (this call's own attempt; the state stays `UNPLANNED` for the next one to retry) or
                any other application error (the state becomes `FAILED`, and every future call on
                this process re-raises the identical failure without calling it again).
            TransportFailureError: the connection to the service itself failed while attempting
                `memory_plan_groups` — including a `ZikaronError` raised while establishing the
                connection itself (a `store_identity` mismatch, or whatever `Store.open` raises
                for an existing-but-unopenable store) — treated the same as any other
                non-`store_busy` failure: `FAILED`, terminal for this process, since neither kind
                of failure is something retrying the identical call inside the same process is
                likely to fix.
            asyncio.CancelledError: the tool call carrying this attempt was cancelled while
                `memory_plan_groups` was in flight — moves the bridge to `FAILED` before re-raising,
                never leaves it `UNPLANNED`. `ServiceConnection.request` itself distinguishes "the
                request never reached the service" from "it may have, and only the response was
                lost" for an ordinary cancellation, but by the time cancellation reaches *this*
                method it has already collapsed to one signal — a bare `CancelledError` — with no
                way to recover which case it was. Treating it as `UNPLANNED` would risk a second,
                genuinely successful takeover if the first one had in fact already committed
                before the cancellation hit, which is exactly the second takeover this bridge's
                own "at most one successful takeover per process" bound exists to rule out; `FAILED`
                is the conservative answer that cannot be wrong in that direction.
        """
        async with self._lock:
            if self._state is _BridgeState.READY:
                return
            if self._state is _BridgeState.FAILED:
                if self._failure is None:
                    # Unreachable: `_state` becomes `FAILED` only in the two `except` blocks
                    # below, each of which sets `_failure` in the same breath. Raised rather than
                    # asserted so the guarantee holds even with assertions stripped (`python -O`).
                    raise RuntimeError("bridge is FAILED but recorded no failure")
                raise self._failure
            try:
                envelope = connection.envelope(kind=_CLIENT_KIND)
                response = await connection.request("memory_plan_groups", {}, envelope=envelope)
                response_to_tool_result(response)
            except asyncio.CancelledError:
                # Whether `memory_plan_groups` had already committed on the service before this
                # cancellation arrived is unknowable from here — see this method's own `Raises`
                # section. `FAILED` is the terminal, conservative answer: it can never permit the
                # second successful takeover a mistaken `UNPLANNED` retry could cause, at the cost
                # of a process that must be re-spawned to try again after a genuinely spurious
                # cancellation, which is the one direction this bound may safely err in.
                self._state = _BridgeState.FAILED
                self._failure = TransportFailureError(
                    "memory_plan_groups was cancelled while in flight; its outcome on the service "
                    "is "
                    "unknown, so this process will not attempt another takeover"
                )
                raise
            except ServiceRejectionError as error:
                if error.code == _STORE_BUSY_CODE:
                    # Stay `UNPLANNED`: `store_busy` is the one outcome `architecture.md` states
                    # as retryable, and a caller's own retry is a fresh forwarded
                    # `memory_next_group`, which calls this method again from the top.
                    raise
                self._state = _BridgeState.FAILED
                self._failure = error
                raise
            except (OSError, ConnectionError, ZikaronError, AmbiguousMutationError) as error:
                wrapped = TransportFailureError(str(error))
                self._state = _BridgeState.FAILED
                self._failure = wrapped
                raise wrapped from error
            else:
                self._state = _BridgeState.READY


async def _call(
    connection: ServiceConnection,
    method: str,
    params: dict[str, object],
    *,
    spill_policy: SpillPolicy,
) -> object:
    """One tool call's worth of translation — identical in shape to `primary.py`'s own `_call`,
    duplicated rather than shared because the one thing that differs, `client.kind`, is exactly
    the module-level constant each file already declares for its own tool set; sharing would mean
    threading that constant through a shared helper's own parameter list for two call sites.

    **Every consolidator result passes through the spill check here**, not only
    `memory_next_group`'s.
    A `merge`/`promote`/`discard` conflict carries the full prose of every conflicting row, which
    is the other shape large enough to be refused — and gating on the verb would leave that one to
    be discovered the way the first one was. That the primary client has no such check is this
    duplication earning its keep: spilling is a property of the consolidator mode, and here that
    is structural rather than a branch.
    """
    envelope = connection.envelope(kind=_CLIENT_KIND)
    try:
        response = await connection.request(method, params, envelope=envelope)
    except (OSError, ConnectionError, ZikaronError, AmbiguousMutationError) as error:
        raise TransportFailureError(str(error)) from error
    result = response_to_tool_result(response)
    try:
        return await asyncio.to_thread(spill.apply, result, policy=spill_policy, tool=method)
    except spill.PayloadLineTooLongError as error:
        # `errors.py`'s own rule: `ToolError` is the one exception type whose message reaches the
        # model regardless of `mask_error_details`. A refusal whose whole value is naming a uuid
        # must not be the one failure that arrives as a generic internal error.
        raise ToolError(str(error)) from error
    except OSError as error:
        raise ToolError(f"could not write this result to a file: {error}") from error


def register_consolidator_tools(
    mcp: FastMCP, connection: ServiceConnection, *, spill_policy: SpillPolicy
) -> None:
    """Decorate all four consolidator tools onto `mcp`.

    Called at most once per process, from `server.py`'s `build_server("consolidator")` branch —
    the seam `architecture.md` §"Consolidator tool surface"'s *"provably cannot reach"* claim
    rests on from this side: this function never decorates those two, or `remember`/`amend`/
    `retire`, so a consolidator process has no tool through which a model could ask for them,
    regardless of what it is prompted to attempt.
    """
    bridge = _PlanBridge()

    @mcp.tool
    async def zikaron_memory_next_group() -> object:
        """Ask for the next group of related memories to consolidate. Returns one of: a served
        group — `{group_id, run_id, anchor, anchor_vacated, journal_entries, candidates, shard,
        serve_count, n_gists_used, remaining_groups}`, where `anchor` (nullable) is the existing
        long-term record this group is built around, `journal_entries` are this group's
        unconsolidated members awaiting a decision, and `candidates` are up to four further
        related long-term records; `{done: true}` when this run has nothing left to serve; or
        `{busy: true, holder_session, holder_pid, expires_at}` when another worker holds this
        store's one consolidation run. Every row named here already carries a read receipt and an
        `expected_version` you must echo back unchanged to
        `zikaron_memory_merge`/`zikaron_memory_promote`/`zikaron_memory_discard`. Groups are
        computed by code; you consume them, you do not choose them.

        `shard` is `{index, of}`, **1-based** — `{index: 1, of: 1}` for a group that was never
        split. `serve_count` is this group's own delivery count **including this delivery**, so a
        first delivery reports 1 and a value greater than 1 means you are seeing a group you have
        already been shown before (a re-serve, if you stopped without dispositioning every
        member). `remaining_groups` counts **other** groups of this run still open — it excludes
        the group this call just delivered — so it reaching 0 means this is the last group left,
        not that none remain at all.
        """
        # First, before anything that can fail: releasing after the planning bridge would skip
        # cleanup on exactly the runs that go wrong. Safe here not because the previous group
        # becomes unreachable — a failed request leaves it fully actionable, and an unfinished one
        # is re-served — but because every route back to it delivers a freshly spilled payload, so
        # no released file is ever the only copy of something still needed. Releasing any *earlier*
        # would delete a payload still in use, since a conflict response spills through this path.
        spill.release_finished(spill_policy)
        await bridge.ensure_planned(connection)
        return await _call(connection, "memory_next_group", {}, spill_policy=spill_policy)

    @mcp.tool
    async def zikaron_memory_merge(
        group_id: str,
        target: dict[str, object],
        gist: str,
        content: str,
        absorb: list[dict[str, object]],
    ) -> object:
        """Rewrite an existing long-term record to absorb part or all of this group,
        superseding the absorbed rows. `target` is `{uuid, expected_version}` naming the long-term
        record to rewrite — it must be this group's anchor or one of its candidates, at the exact
        version `zikaron_memory_next_group` handed you. `absorb` is a list of
        `{uuid, expected_version}`
        naming journal entries delivered in this group and not yet dispositioned, each at the
        exact version you were handed. Returns `{uuid, version, remaining_uuids, group_complete}`
        on success, or `{conflict: true, current: [...], remaining_uuids}` if any named version is
        stale — nothing is mutated on a conflict, and `current` names every conflicting row so you
        can re-decide in one more call. `remaining_uuids` is this group's still-undispositioned
        members after this call; `group_complete` is true only once that list is empty.
        """
        return await _call(
            connection,
            "memory_apply_merge",
            {
                "group_id": group_id,
                "target": target,
                "gist": gist,
                "content": content,
                "absorb": absorb,
            },
            spill_policy=spill_policy,
        )

    @mcp.tool
    async def zikaron_memory_promote(
        group_id: str, gist: str, content: str, absorb: list[dict[str, object]]
    ) -> object:
        """Create a long-term record from part or all of this group, or — if `absorb` names
        exactly one journal row and `gist`/`content` are byte-identical to it — flip that row's
        own tier in place rather than writing a new one. `absorb` is a list of
        `{uuid, expected_version}` naming journal entries delivered in this group and not yet
        dispositioned. Returns `{uuid, version, remaining_uuids, group_complete}` on success, or
        `{conflict: true, current: [...], remaining_uuids}` on the same stale-version terms as
        `zikaron_memory_merge`.
        """
        return await _call(
            connection,
            "memory_apply_promote",
            {"group_id": group_id, "gist": gist, "content": content, "absorb": absorb},
            spill_policy=spill_policy,
        )

    @mcp.tool
    async def zikaron_memory_discard(
        group_id: str, absorb: list[dict[str, object]], reason: str
    ) -> object:
        """Retire journal rows from this group that are not worth keeping — outright, with no
        replacement. `absorb` is a list of `{uuid, expected_version}` naming the rows to discard;
        `reason` is recorded in the event log and nowhere else — the discarded rows' own prose is
        untouched — so keep it short and put no secret in it: that log is a table in this same
        plaintext store. Returns `{retired, remaining_uuids, group_complete}` on success, or
        `{conflict: true, current: [...], remaining_uuids}` on the same stale-version terms as
        `zikaron_memory_merge`.
        """
        return await _call(
            connection,
            "memory_apply_discard",
            {"group_id": group_id, "absorb": absorb, "reason": reason},
            spill_policy=spill_policy,
        )
