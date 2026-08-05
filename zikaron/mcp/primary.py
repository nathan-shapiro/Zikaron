"""The five primary-agent tools: `search`, `fetch`, `remember`, `amend`, `retire`.

`architecture.md` §"MCP tool surface (5 tools)" is normative for every signature, return shape and
description below — tool descriptions carry the mechanics (the version precondition, the dedup
payload, retire semantics) deliberately, per D30, since they sit in context at the point of
decision while `agentSpawn`'s prose carries policy. Each tool is a thin translation: build the RPC
params from typed arguments, call the wire method whose name `architecture.md` §"Service RPC
surface" states (`fetch`/`search`/`surface` are RPC-only names; every other tool name matches its
wire method exactly), and hand back whatever the service returned — a conflict shape included,
since a conflict is an ordinary successful response, not a rejection (`errors.py`'s own docstring).

Every tool constructs its own `ClientEnvelope` fresh via `connection.envelope(kind="mcp")`, which
carries whichever session label `connection` has adopted so far — see `connection.py`'s own
docstring on why that adoption, not a fresh per-call environment read, is what
`architecture.md`'s "the client adopts the returned label" actually requires.
"""

from fastmcp import FastMCP

from zikaron.core.errors import ZikaronError
from zikaron.mcp.connection import AmbiguousMutationError, ServiceConnection
from zikaron.mcp.errors import TransportFailureError, response_to_tool_result

_CLIENT_KIND = "mcp"


async def _call(connection: ServiceConnection, method: str, params: dict[str, object]) -> object:
    """One tool call's worth of translation: envelope, send, and turn the response into either a
    plain return value or a raised `ToolError` — the one path every tool below goes through, so a
    change to how a transport failure is reported changes here once rather than five times.

    Catches `ZikaronError` as well as the bare socket exceptions: `connection.request` can raise
    one while *establishing* a connection (a `store_identity` mismatch, or whatever `Store.open`
    raises for a store that exists but will not open — `REINDEXING`, `SCHEMA_INCOMPATIBLE`,
    `BAD_CONFIG`), and `ZikaronError` is a plain `Exception` subclass with no relationship to
    `fastmcp.exceptions.ToolError` on its own — left uncaught, it would reach the model as an
    opaque internal failure rather than the deliberate, message-preserving tool error every other
    rejection surfaces as.
    """
    envelope = connection.envelope(kind=_CLIENT_KIND)
    try:
        response = await connection.request(method, params, envelope=envelope)
    except (OSError, ConnectionError, ZikaronError, AmbiguousMutationError) as error:
        raise TransportFailureError(str(error)) from error
    return response_to_tool_result(response)


def register_primary_tools(mcp: FastMCP, connection: ServiceConnection) -> None:
    """Decorate all five primary-agent tools onto `mcp`.

    Called at most once per process, from `server.py`'s `build_server("primary")` branch — the one
    seam `architecture.md` §"a consolidator config provably cannot reach `search` or `fetch`" rests
    on: a consolidator process never calls this function at all, so `search`/`fetch`/`remember`/
    `amend`/`retire` are never registered as tools in that process and therefore cannot appear in
    `tools/list` or be dispatched by `tools/call`, regardless of what a model asks for.
    """

    @mcp.tool
    async def zikaron_search(query: str, limit: int = 5, include_retired: bool = False) -> object:
        """Search recorded project knowledge by relevance. **Call this whenever you are about to
        spend real effort** — an unexpected failure, something behaving differently from how it
        reads, or planning and weighing options — not only when memory is what the user asked
        about; the gists injected before a message are only what matched that message. A hit is
        historical evidence rather than a veto: it tells you what to re-check, so fetch the record
        and confirm the conditions still hold before ruling an option out. Returns a
        list of
        `{uuid, gist, tier, state, created_at, updated_at, superseded_by}`, best match first —
        `state` is one of `live`/`superseded`/`retired`, so a demoted row is visible for what it
        is. Carries no version field, and therefore no licence to write: call `zikaron_fetch` on a
        uuid before amending or retiring it. Returns an empty list against an empty store.
        """
        return await _call(
            connection,
            "search",
            {"query": query, "limit": limit, "include_retired": include_retired},
        )

    @mcp.tool
    async def zikaron_fetch(uuids: list[str]) -> object:
        """Fetch full records by uuid (1-50 per call). Returns
        `{records: [{uuid, gist, content, version, tier, active, state, superseded_by,
        superseded_by_latest, superseded_by_latest_state, created_at, updated_at}], missing:
        [uuid, ...]}` — records in the order requested, duplicates collapsed to one, unknown uuids
        reported in `missing` rather than failing the whole call. `superseded_by_latest`/
        `superseded_by_latest_state` resolve the full supersession chain, so a row that says
        "replaced" also says whether the replacement is itself still live. **Mints a read receipt
        for every record returned** — this is the only way to license a write to a row this
        session did not itself just write or just receive back in a conflict payload; read a
        record's full content here before calling `zikaron_amend`/`zikaron_retire` on it.
        """
        return await _call(connection, "fetch", {"uuids": uuids})

    @mcp.tool
    async def zikaron_remember(gist: str, content: str) -> object:
        """Record a new memory unconditionally. Returns `{uuid, version, near_duplicates: [{uuid,
        gist, cosine, rank}]}` — the new row is always written and always live, and
        `near_duplicates` (at most a few, ranked) names existing rows that resemble it closely
        enough to be worth comparing, never an assertion that they are duplicates: read both gists
        yourself before deciding. To resolve a genuine duplicate, `zikaron_amend` the older row
        with anything this one adds, then `zikaron_retire` this new row with `superseded_by` set
        to the older uuid — until you do, both stay live. Mints an own-write receipt for the new
        row, so you may amend or retire it yourself later in this session without fetching it
        first.
        """
        return await _call(connection, "remember", {"gist": gist, "content": content})

    @mcp.tool
    async def zikaron_amend(uuid: str, version: int, gist: str, content: str) -> object:
        """Fully rewrite an existing record's gist and content. Requires `version` to be the
        value you most recently read for this exact uuid — from `zikaron_fetch`, from
        `zikaron_remember`'s own return for a row you just created, or from an earlier conflict
        payload for this uuid — never a version merely seen in a `zikaron_search` row, which
        carries none. Returns `{uuid, version}` on success, or `{conflict: true, current: {...}}`
        if `version` is no longer current: `current` is the record as it now stands, with a fresh
        receipt already minted at its version, so you can re-decide and retry in one more call
        rather than fetching again first.
        """
        return await _call(
            connection,
            "amend",
            {"uuid": uuid, "version": version, "gist": gist, "content": content},
        )

    @mcp.tool
    async def zikaron_retire(uuid: str, version: int, superseded_by: str | None = None) -> object:
        """Soft-delete a record — it is never hard-deleted. Same version precondition as
        `zikaron_amend`. Pass `superseded_by` naming the uuid of the record that replaces this one
        to mark it superseded — it stays retrievable, demoted, and every fetch of it will point at
        its replacement; omit `superseded_by` to retire it outright, which drops it out of default
        search results entirely. `superseded_by` must name a different, live record: it may not
        equal `uuid` itself, may not create a cycle back to this record through some other
        record's own `superseded_by`, and may not already be retired outright — pick a live
        replacement, or retire this record outright instead. Returns `{uuid, version}` on
        success, or `{conflict: true, current: {...}}` on the same version-mismatch terms as
        `zikaron_amend`. Retiring a record other records point to as their replacement is legal
        and simply means that lineage now has no living head — `zikaron_fetch` on those other
        records will say so.
        """
        return await _call(
            connection, "retire", {"uuid": uuid, "version": version, "superseded_by": superseded_by}
        )
