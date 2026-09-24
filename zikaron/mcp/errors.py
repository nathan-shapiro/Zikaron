"""Turning one JSON-RPC response object into what a FastMCP tool hands back to the calling model.

The distinction this module exists to make is already fully resolved by the wire response itself,
not by which error code a rejection happens to carry: `architecture.md`'s tool surface returns a
conflict (`{conflict: true, current: ...}`) as an ordinary **successful** RPC result —
`core.write.tools.Amended | Conflict` never raises for a conflict — while every other rejection
(`store_busy`, `no_read_receipt`, `bounds`, …) comes back as a JSON-RPC `error` object. So this
module's whole job is: a `result` becomes the tool's plain return value, and an `error` becomes a
raised `ToolError`, which is what makes FastMCP mark the call `is_error=True` and put the message
in front of the model that made it — exactly the outcome a rejection like `store_busy` or
`no_read_receipt` needs, since those are not shapes any tool's documented return type includes,
unlike a conflict.
"""

from fastmcp.exceptions import ToolError

from zikaron.service.rpc import WireError, parse_response


class ServiceRejectionError(ToolError):
    """One JSON-RPC `error` object, raised so FastMCP reports it to the calling model.

    Carries the wire `code` and `data` verbatim rather than only the message, so a model that
    receives this can see *why* — `store_busy` invites a retry, `no_read_receipt` says which uuids
    need `zikaron_memory_fetch` first — the same information the RPC error payload already states,
    just surfaced through the one channel FastMCP guarantees reaches the model
    (`ToolError`'s own contract: its message is shown "regardless of `mask_error_details`").
    """

    def __init__(self, code: int, message: str, data: dict[str, object] | None) -> None:
        self.code = code
        self.data = data
        detail = f" ({data})" if data else ""
        super().__init__(f"zikaron error {code}: {message}{detail}")


class TransportFailureError(ToolError):
    """The service could not be reached or verified at all — no wire response to interpret.

    Distinct from `ServiceRejectionError` because there is no `code`/`data` to carry: this covers
    `connect_start_if_absent`'s own `ConnectionError` (no server became reachable before its
    deadline) and a `ZikaronError` raised while *establishing* the connection itself (a
    `store_identity` mismatch, or whatever `Store.open`/`Store.create` raise on a store that
    exists but will not open) — failures that happen before any request/response pair exists for
    `ServiceRejection` to describe.
    """


def response_to_tool_result(response: dict[str, object]) -> object:
    """One parsed JSON-RPC response object, as what a tool handler returns to FastMCP.

    Returns the bare `result` value unchanged on success — which may itself be a conflict shape,
    per this module's own docstring — and raises `ServiceRejection` for an `error` object.

    Raises:
        ServiceRejectionError: the response carried an `error` object.
        TypeError: the response is neither a well-formed success (`"result"` present) nor a
            well-formed error (`"error"` present as an object with `"code"`/`"message"`) — a
            protocol-level malformation this module has no data to construct either exception
            from, and which indicates a bug in `zikaron-service` or in `zikaron.mcp.connection`'s
            own framing rather than an ordinary rejection a model should be told to retry.
    """
    parsed = parse_response(response)
    if not isinstance(parsed, WireError):
        return parsed
    raise ServiceRejectionError(parsed.code, parsed.message, parsed.data or None)
