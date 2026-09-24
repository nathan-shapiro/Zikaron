"""Newline-delimited JSON-RPC 2.0 framing: the wire shapes, and the protocol's own error range.

`architecture.md` §RPC fixes the transport as "Unix domain socket + newline-delimited JSON-RPC
2.0." This module is the framing only — parsing one line into a request, and a result or a
`ZikaronError` into a response line — with no knowledge of what any method does. `dispatch.py` is
where a method name becomes a call into `core`.

**Two error ranges, never confused.** JSON-RPC 2.0 reserves -32768..-32000 for the protocol itself
and leaves the top hundred codes to the application (`zikaron.core.errors.ErrorCode`,
`-32099..-32000`). This module owns exactly the four *protocol*-level codes below that band — a
line that is not valid JSON, a shape that is not a valid request, a method nobody registered, or
params a handler cannot even attempt to read — none of which is a rejection `core` could ever
raise, because `core` is never reached.
"""

import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Final


#: The five protocol-level codes JSON-RPC 2.0 itself defines, distinct from any Zikaron
#: `ErrorCode` by numeric range alone — a client can tell "the transport rejected this" from "the
#: application rejected this" without inspecting anything but the number.
class ProtocolErrorCode(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


_JSONRPC_VERSION: Final = "2.0"


@dataclass(frozen=True, slots=True)
class RpcRequest:
    """One parsed request line: a method name, its params, and the id to echo back.

    `has_id` distinguishes a genuine JSON-RPC *notification* (the `id` key absent entirely — gets
    no response at all) from an ordinary request whose `id` happens to be explicitly `null` (a
    real request, which still gets a response carrying `"id": null`). `request_id` alone cannot
    make that distinction, since `dict.get("id")` returns `None` for both cases — Zikaron's own
    methods are all request/response and no client is documented as sending a notification, but
    the framing itself should not silently answer one anyway, which is what a response line for a
    request with no `id` key would be.
    """

    method: str
    params: dict[str, object]
    request_id: object
    has_id: bool


class RequestParseError(Exception):
    """A request line could not be turned into an `RpcRequest`.

    Carries the protocol code and a human message, so the caller that catches this has everything
    `encode_error` needs without re-deriving it. `request_id` is the id to echo, when one could be
    recovered from otherwise-malformed input — JSON-RPC 2.0 itself asks for `null` when it cannot.

    `has_id` defaults to `True` — "there is a response to give" — because the two earliest
    failures (invalid JSON; a top level that is not even an object) happen before an `id` key is
    knowable at all, and a truly unparseable line has no notification identity to suppress a
    response for. Every later failure in `parse_request` runs after `has_id` *is* knowable and
    passes the real computed value, so a well-formed notification whose `params` (say) fails
    shape validation is still correctly treated as a notification — not answered, exactly as a
    method-level rejection of the same notification would not be.
    """

    def __init__(
        self,
        code: ProtocolErrorCode,
        message: str,
        *,
        request_id: object = None,
        has_id: bool = True,
    ) -> None:
        self.code: Final = code
        self.message: Final = message
        self.request_id: Final = request_id
        self.has_id: Final = has_id
        super().__init__(message)


def parse_request(line: str) -> RpcRequest:
    """One line of input, as the request it must describe.

    Raises:
        RequestParseError: the line is not valid JSON (`PARSE_ERROR`); the top level is not an
            object, `jsonrpc` is not exactly `"2.0"`, or `method` is not a non-empty string
            (`INVALID_REQUEST`); or `params`, when present, is not an object (`INVALID_PARAMS`) —
            JSON-RPC 2.0 permits an array for positional params, but no Zikaron method takes them,
            so a request that sent one could not be dispatched regardless and is rejected here
            rather than by every handler individually.
    """
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as error:
        raise RequestParseError(ProtocolErrorCode.PARSE_ERROR, str(error)) from error
    if not isinstance(parsed, dict):
        raise RequestParseError(ProtocolErrorCode.INVALID_REQUEST, "request is not a JSON object")
    has_id = "id" in parsed
    request_id = parsed.get("id")
    if parsed.get("jsonrpc") != _JSONRPC_VERSION:
        raise RequestParseError(
            ProtocolErrorCode.INVALID_REQUEST,
            'jsonrpc must be "2.0"',
            request_id=request_id,
            has_id=has_id,
        )
    method = parsed.get("method")
    if not isinstance(method, str) or method == "":
        raise RequestParseError(
            ProtocolErrorCode.INVALID_REQUEST,
            "method must be a non-empty string",
            request_id=request_id,
            has_id=has_id,
        )
    params = parsed.get("params", {})
    if not isinstance(params, dict):
        raise RequestParseError(
            ProtocolErrorCode.INVALID_PARAMS,
            "params must be an object",
            request_id=request_id,
            has_id=has_id,
        )
    return RpcRequest(method=method, params=params, request_id=request_id, has_id=has_id)


def encode_result(request_id: object, result: object, *, session_id: str | None = None) -> str:
    """One success response line, newline-terminated.

    `session_id`, when given, is attached as `client.session_id` — a **sibling** of `result`,
    never spliced into it: `architecture.md` states the label belongs "in the response envelope,"
    and `memory_search`'s own documented `result` is a bare list (`[{...}, ...]`), which has no
    key to add one to. Mirroring the request's own `client: {session_id: ...}` shape is what
    keeps the two directions symmetric rather than inventing a second convention for the response
    side.
    """
    payload: dict[str, object] = {"jsonrpc": _JSONRPC_VERSION, "id": request_id, "result": result}
    if session_id is not None:
        payload["client"] = {"session_id": session_id}
    return json.dumps(payload) + "\n"


def encode_error(
    request_id: object,
    code: int,
    message: str,
    data: dict[str, object] | None = None,
    *,
    session_id: str | None = None,
) -> str:
    """One error response line, newline-terminated.

    `code` is a plain `int` rather than either enum, because a response line has to carry either a
    `zikaron.core.errors.ErrorCode` or a `ProtocolErrorCode`, and this module owns the framing for
    both without depending on which one a given call happened to raise.

    `session_id`, when given, is attached as the same top-level `client.session_id` sibling
    `encode_result` uses for a success — never spliced into `data`. `architecture.md`: "Returns
    `client.session_id` in the response envelope — on success and on every error alike," naming
    the response *envelope*, a structural location, not a field inside any particular error's own
    declared `data` shape. Splicing it into `data` instead would put an undocumented extra key
    into every one of the error table's stated shapes — `not_found`'s `{uuid}`, `bounds`'s
    `{field, limit, actual}`, and so on — none of which name `session_id` as one of their fields,
    so a caller pattern-matching on a declared shape would receive a field it never asked about.
    """
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    payload: dict[str, object] = {"jsonrpc": _JSONRPC_VERSION, "id": request_id, "error": error}
    if session_id is not None:
        payload["client"] = {"session_id": session_id}
    return json.dumps(payload) + "\n"


@dataclass(frozen=True, slots=True)
class WireError:
    """One JSON-RPC `error` object as a client reads it, before any client-specific raising.

    `code` is an `int` rather than an `ErrorCode` on purpose: a service newer than this client can
    send a code this build has no member for, and refusing to parse it would turn a rejection a
    caller could still read into a protocol failure.
    """

    code: int
    message: str
    data: dict[str, object]


def parse_response(response: dict[str, object]) -> object | WireError:
    """One parsed response object as either its `result` value or its error.

    Shared by both `ServiceConnection` clients rather than reimplemented per surface — the hook
    keeps its own stdlib-only parse — so `zikaron-mcp` and `zikaron knowledge` cannot come to
    disagree about what a malformed response is. Neither the `ToolError` one raises nor the refusal
    the other prints belongs here, so this returns the error instead of raising it.

    Raises:
        TypeError: the response is neither a well-formed success (`result` present) nor a
            well-formed error (`error` present, an object, carrying an integer `code` and a string
            `message`). That is a defect in the service or in the framing rather than a rejection,
            and there is nothing to construct one from.
    """
    if "result" in response:
        return response["result"]
    error = response.get("error")
    if not isinstance(error, dict):
        raise TypeError(f"response has neither a result nor a well-formed error: {response!r}")
    code = error.get("code")
    message = error.get("message")
    if not isinstance(code, int) or not isinstance(message, str):
        raise TypeError(f"error object is missing code/message: {error!r}")
    data = error.get("data")
    if data is not None and not isinstance(data, dict):
        raise TypeError(f"error.data is present but not an object: {error!r}")
    return WireError(code=code, message=message, data={} if data is None else data)
